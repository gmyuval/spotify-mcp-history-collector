# DigitalOcean Deployment Guide

Deploy the Spotify MCP History Collector to a DigitalOcean Droplet with
Docker Compose, Caddy (automatic HTTPS), and GitHub Actions CI/CD.

## Architecture

```text
                    Internet
                       │
                       ▼
              ┌────────────────┐
              │   Caddy :443   │  Automatic HTTPS (Let's Encrypt)
              └───────┬────────┘
                      │
         ┌────────────┼────────────────┐
         │            │                │
         ▼            ▼                ▼
   /healthz      /mcp/*          all other routes
   (no auth)   (Bearer token)    (forward_auth)
         │            │                │
         ▼            │        ┌───────▼────────┐
   ┌──────────┐       │        │ oauth2-proxy   │
   │ API:8000 │       │        │ :4180          │
   └──────────┘       │        │ (Google OAuth) │
                      │        └───────┬────────┘
                      │                │ authenticated
         ┌────────────┴────────────────┘
         ▼                     ▼
  ┌──────────────┐     ┌──────────────┐
  │  API :8000   │     │Frontend :8001│
  │  (FastAPI)   │     │  (FastAPI)   │
  └──────┬───────┘     └──────────────┘
         │                     │
         │ DATABASE_URL        │ API_BASE_URL
         │ (VPC private)       │ (Docker network)
         ▼                     │
  ┌──────────────┐             │
  │  DO Managed  │             │
  │  PostgreSQL  │◄────────────┘ (via API)
  └──────────────┘
         ▲
         │ DATABASE_URL
  ┌──────┴───────┐
  │  Collector   │
  │  (worker)    │
  └──────────────┘
```

**Route mapping (Caddy):**

| Path | Backend | Auth |
|------|---------|------|
| `/healthz` | API | None |
| `/oauth2/*` | oauth2-proxy | Google OAuth flow |
| `/mcp/*` | API | Bearer token |
| `/auth/*` | API | Google OAuth (forward_auth) |
| `/admin/*` | API | Google OAuth (forward_auth) |
| `/history/*` | API | Google OAuth (forward_auth) |
| `/*` | Frontend | Google OAuth (forward_auth) |

## Prerequisites

- [doctl](https://docs.digitalocean.com/reference/doctl/how-to/install/)
  authenticated (`doctl auth init`)
- [gh](https://cli.github.com/) CLI authenticated (`gh auth login`)
- Python 3.x available locally (for generating encryption keys)
- An existing DigitalOcean Managed PostgreSQL cluster in Frankfurt (fra1)
- A domain name with DNS managed by DigitalOcean
- A Spotify Developer application
  ([dashboard](https://developer.spotify.com/dashboard))
- A Google OAuth 2.0 application for oauth2-proxy
  (see [Google OAuth setup guide](./google-oauth-setup.md))

## Quick Start (Automated)

The provisioning script handles everything in one command:

```bash
# 1. Fill in your parameters
#    Edit resources/.env.do with:
#      DOMAIN_NAME, SSH_KEY_NAME, SPOTIFY_CLIENT_ID,
#      SPOTIFY_CLIENT_SECRET, DROPLET_SIZE

# 2. Run the provisioning script
bash deploy/provision.sh
```

The script will:

1. Create a Droplet in Frankfurt (same VPC as your database)
2. Configure a cloud firewall (SSH, HTTP, HTTPS only)
3. Add the Droplet to database trusted sources
4. Create a DNS A record for your domain
5. Install Docker on the Droplet
6. Create a `deploy` user for SSH access
7. Clone the repository
8. Create the `spotify_mcp` database
9. Generate and upload `.env.prod` (with auto-generated secrets)
10. Build and start all services
11. Run database migrations
12. Generate a CI/CD deploy key and configure GitHub Secrets

**Remaining manual steps:**
1. Add `https://yourdomain.com/auth/callback` as a Redirect URI in your
   [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Set up Google OAuth credentials and configure them on the droplet
   (see [Google OAuth setup guide](./google-oauth-setup.md))

## Configuration

### `resources/.env.do` (provisioning parameters)

```bash
DOMAIN_NAME=music.example.com
SSH_KEY_NAME=my-ssh-key        # Name from: doctl compute ssh-key list
SPOTIFY_CLIENT_ID=abc123...
SPOTIFY_CLIENT_SECRET=xyz789...
DROPLET_SIZE=s-2vcpu-2gb       # $18/mo — sufficient for all services

# Database connection (existing managed PostgreSQL)
DB_EXTERNAL_HOST=db-host.ondigitalocean.com
DB_PRIVATE_HOST=private-db-host.ondigitalocean.com
DB_PORT=25060
DB_USER=doadmin
DB_PASSWORD=your_db_password
DB_NAME=spotify_mcp
DB_CLUSTER_ID=your-cluster-uuid  # From: doctl databases list
```

### `.env.prod` (generated on the Droplet)

The provisioning script generates this automatically. Key values:

| Variable | Source |
|----------|--------|
| `DOMAIN` | From `DOMAIN_NAME` |
| `DATABASE_URL` | Built from VPC private host + `?ssl=require` |
| `SPOTIFY_CLIENT_ID` | From `.env.do` |
| `SPOTIFY_CLIENT_SECRET` | From `.env.do` |
| `SPOTIFY_REDIRECT_URI` | `https://{DOMAIN}/auth/callback` |
| `TOKEN_ENCRYPTION_KEY` | Auto-generated (Fernet) |
| `ADMIN_TOKEN` | Auto-generated (URL-safe random) |
| `CORS_ALLOWED_ORIGINS` | `https://{DOMAIN}` |
| `OAUTH2_PROXY_COOKIE_SECRET` | Auto-generated (32-byte base64) |
| `GOOGLE_OAUTH_CLIENT_ID` | Manual — from Google Cloud Console |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Manual — from Google Cloud Console |

Email access control is managed via `deploy/authenticated-emails.txt`
(one email per line). See [Google OAuth setup guide](./google-oauth-setup.md)
for complete instructions.

For the full template with all available options, see `.env.prod.example`.

### SSL / asyncpg Note

DigitalOcean Managed PostgreSQL requires SSL (`sslmode=require`).
The asyncpg driver uses a different parameter name: `ssl=require`.
The `DATABASE_URL` in `.env.prod` is configured with `?ssl=require`
which asyncpg understands natively. No application code changes needed.

## Production deployment (GitHub Actions)

Merging into `main` makes a revision eligible for production, but **a merge
alone never deploys production**. Production deployment requires separate
authorization and a manual dispatch of `.github/workflows/deploy.yml` with an
immutable, full 40-character commit SHA that is reachable from `origin/main`.

### Prerequisites

- The change has been merged to `main` and any required repository review and
  checks have completed.
- The operator has separate authorization to change production.
- `gh` is authenticated for this repository, or the operator can use the
  repository's **Actions** tab.
- The exact candidate SHA is known; do not use a branch name, tag, abbreviated
  SHA, or the current checkout.

Confirm the candidate before dispatching:

```bash
DEPLOY_SHA="0123456789abcdef0123456789abcdef01234567"  # replace with the full SHA
git fetch origin main:refs/remotes/origin/main
git rev-parse "$DEPLOY_SHA^{commit}"
git merge-base --is-ancestor "$DEPLOY_SHA" origin/main
```

Both Git commands must succeed. Stop if the SHA is not 40 hexadecimal
characters, does not name a commit, or is not reachable from `origin/main`.

### Dispatch and monitor

Use one of these paths after authorization:

```bash
DISPATCHED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh workflow run deploy.yml --ref main -f commit_sha="$DEPLOY_SHA"

# Identify the new run by both its SHA-bearing title and dispatch time. If more
# than one candidate appears, stop instead of guessing which run to monitor.
RUN_ID=""
for attempt in $(seq 1 30); do
  MATCHING_RUNS=$(gh run list \
    --workflow deploy.yml \
    --event workflow_dispatch \
    --branch main \
    --limit 100 \
    --json databaseId,displayTitle,createdAt \
    --jq ".[] | select(.displayTitle == \"Deploy $DEPLOY_SHA to production\" and .createdAt >= \"$DISPATCHED_AT\") | .databaseId")
  RUN_COUNT=$(printf '%s\n' "$MATCHING_RUNS" | awk 'NF { count++ } END { print count + 0 }')
  if [ "$RUN_COUNT" -eq 1 ]; then
    RUN_ID=$(printf '%s\n' "$MATCHING_RUNS" | awk 'NF { print; exit }')
    break
  fi
  if [ "$RUN_COUNT" -gt 1 ]; then
    echo "ERROR: multiple runs match Deploy $DEPLOY_SHA to production; identify the exact run in GitHub"
    exit 1
  fi
  sleep 2
done
test -n "$RUN_ID" || { echo "ERROR: dispatched run was not found"; exit 1; }

gh run view "$RUN_ID" --json databaseId,displayTitle,event,status,conclusion,url
gh run watch "$RUN_ID" --exit-status
gh run view "$RUN_ID" --json databaseId,displayTitle,status,conclusion,url
```

Or in GitHub, open **Actions** → **Deploy to DigitalOcean** → **Run workflow**,
select the `main` workflow definition, enter `commit_sha` as the full SHA, and
select **Run workflow**. Do not dispatch from a branch or tag. Open the run
whose title is exactly `Deploy <the full SHA> to production`, record its run ID
and URL, and monitor that exact run page. Stop if more than one run could be the
authorized dispatch; never substitute the newest run without verifying its
SHA-bearing title.

The workflow validates the SHA before deployment, runs lint, type checking, and
every service test suite against that exact revision, then captures a clean,
exact production commit in a separate successful job. The deploy job stops if
the production checkout changes after capture, fetches `origin/main`, validates
the requested SHA again, and checks out that exact revision in a clean detached
state. It preserves the existing firewall handling, Compose build, health
checks, migration order, and collector restart sequence.

Monitor the run to a terminal result. A successful deployment has all required
GitHub jobs green and a job summary that records the requested SHA, previous
production SHA, `production` environment, terminal health result, and rollback
posture. Those are the required success evidence; a dispatched or merely
started run is not success.

On any validation, CI, SSH, migration, or health failure, stop. Do not retry by
resetting the Droplet to a branch and do not infer that production is healthy.
Inspect the failed job and its summary, preserve the captured prior SHA, and
obtain separate authorization before a retry or rollback.

### Rollback

The job summary's **Previous production SHA** is only an application-code
rollback candidate, never a complete rollback. Redeploying it does not reverse
database schema or data changes. Determine from the exact failed run whether
migrations may have started or applied. If they may have, or the evidence is
uncertain, stop and obtain a separately accepted database compatibility or
recovery decision or procedure before redispatching older code. This runbook
does not define or perform a database rollback.

If the exact run proves that migrations did not start, separate production
authorization may allow the operator to dispatch the same workflow with the
captured full SHA as `commit_sha`. If a database decision is required, any
older-code redispatch must follow its accepted outcome. In either case, monitor
that exact run to a terminal result using the same success evidence. Do not use
`main`, a branch, a tag, or a local `git reset` as a rollback mechanism.

### GitHub Secrets

Set automatically by `provision.sh`. To update manually:

| Secret | Description |
|--------|-------------|
| `DROPLET_IP` | Droplet public IPv4 |
| `SSH_PRIVATE_KEY` | Ed25519 private key for `deploy` user |

```bash
gh secret set DROPLET_IP --repo gmyuval/spotify-mcp-history-collector --body "YOUR_IP"
gh secret set SSH_PRIVATE_KEY --repo gmyuval/spotify-mcp-history-collector < deploy/.deploy-key
```

## File Reference

| File | Purpose |
|------|---------|
| `docker-compose.prod.yml` | Production service definitions (no local Postgres, Caddy, production uvicorn) |
| `deploy/Caddyfile` | Reverse proxy routes with automatic HTTPS and forward_auth |
| `deploy/authenticated-emails.txt` | Email whitelist for oauth2-proxy (one email per line) |
| `deploy/provision.sh` | One-time automated provisioning script |
| `.github/workflows/deploy.yml` | Manual, immutable-revision production deployment workflow |
| `.env.prod.example` | Template for production environment variables |
| `resources/.env.do` | Provisioning parameters (not committed — gitignored) |
| `docs/google-oauth-setup.md` | Google OAuth setup guide for oauth2-proxy |

## Manual Operations

### SSH to the Droplet

```bash
# As deploy user (for app operations)
ssh deploy@DROPLET_IP

# As root (for system administration)
ssh root@DROPLET_IP
```

### View logs

```bash
ssh deploy@DROPLET_IP
cd /opt/spotify-mcp

# All services
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f

# Specific service
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f api
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f collector
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f frontend
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f caddy
```

### Restart services

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml restart
```

### Run migrations manually

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec api alembic upgrade head
```

### Production deploys and rollback

Use the manual GitHub Actions procedure in
[Production deployment (GitHub Actions)](#production-deployment-github-actions).
Do not deploy or roll back directly over SSH; that bypasses immutable-SHA
validation, required checks, and recorded rollback evidence.

### Check service health

```bash
# From the Droplet
docker compose --env-file .env.prod -f docker-compose.prod.yml ps

# From anywhere
curl https://yourdomain.com/healthz
```

## Cost

| Resource | Monthly Cost |
|----------|-------------|
| Droplet (s-2vcpu-2gb) | $18 |
| Managed PostgreSQL | (existing) |
| Caddy TLS (Let's Encrypt) | Free |
| GitHub Actions CI/CD | Free (public repo) |

## Troubleshooting

### Caddy certificate not provisioning

Ensure:
- Domain DNS A record points to the Droplet IP
- Ports 80 and 443 are open in the cloud firewall
- The `DOMAIN` env var in `.env.prod` matches your domain exactly

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs caddy
```

### Database connection refused

Ensure:
- The Droplet is in the same VPC as the managed database
- The Droplet is added to the database's trusted sources
- `DATABASE_URL` uses the private/VPC hostname and `?ssl=require`

### Collector not starting

The collector depends on the API being healthy first:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs collector
docker compose --env-file .env.prod -f docker-compose.prod.yml exec api curl -sf http://localhost:8000/healthz
```

### Out of memory during Docker build

The Droplet has 1GB swap configured by the provisioning script. If builds
still fail, build one service at a time:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml build api
docker compose --env-file .env.prod -f docker-compose.prod.yml build collector
docker compose --env-file .env.prod -f docker-compose.prod.yml build frontend
```

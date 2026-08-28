# DigitalOcean Deployment Guide

Deploy the Spotify MCP History Collector to a DigitalOcean Droplet with
Docker Compose, Caddy (automatic HTTPS), and GitHub Actions CI/CD.

## Architecture

```text
Internet → Caddy :443
  ├─ open /healthz → API :8000
  ├─ proxy-owned /oauth2/* → oauth2-proxy :4180
  ├─ Caddy-auth bypass /mcp/*, /auth/*, /api/* → API :8000
  ├─ Google-forward-authenticated /admin/* → Frontend :8001
  ├─ open Explorer /, /login, /static/* → Explorer :8002
  └─ Google-forward-authenticated Explorer catch-all → Explorer :8002

API and Collector → DigitalOcean Managed PostgreSQL over DATABASE_URL
Frontend and Explorer → API over the private Compose network
```

**Route mapping (Caddy):**

| Path | Backend | Auth |
|------|---------|------|
| `/healthz` | API | None |
| `/oauth2/*` | oauth2-proxy | Proxy-owned login, callback, sign-out, and session-check behavior |
| `/mcp/*` | API | No Caddy gate; application auth varies by MCP endpoint/version |
| `/auth/login`, `/auth/callback` | API | No Caddy gate; open Spotify OAuth entry and callback |
| `/auth/refresh` | API | No Caddy gate; validates a refresh token from the body or HttpOnly cookie |
| `/auth/logout` | API | No Caddy gate; clears authentication cookies |
| `/auth/exchange-google` | API | No Caddy gate; requires `X-Internal-API-Key` |
| `/api/*` | API | No Caddy gate; JWT Bearer/access cookie or `smcp_` API token, enforced by API endpoints |
| `/admin` | Redirect to `/admin/` | None; destination is protected |
| `/admin/*` | Frontend | Google OAuth (`forward_auth`) |
| `/`, `/login`, `/static/*` | Explorer | None |
| All other paths, including `/history/*` | Explorer | Google OAuth (`forward_auth`) |

The table describes Caddy's routing and authentication boundary. API handlers
remain responsible for their own Bearer-token, JWT, internal-key, and OAuth
flow requirements where the proxy intentionally does not apply Google
`forward_auth`.

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
- The Droplet's trusted Ed25519 `SHA256:` SSH host fingerprint, obtained from
  an authenticated DigitalOcean console before the first SSH connection

## Quick Start (Automated with an authorization checkpoint)

The interactive provisioning script coordinates the full setup in one command:

```bash
# 1. Fill in your parameters
#    Edit resources/.env.do with:
#      DOMAIN_NAME, SSH_KEY_NAME, SPOTIFY_CLIENT_ID,
#      SPOTIFY_CLIENT_SECRET, DROPLET_SIZE,
#      DROPLET_SSH_HOST_FINGERPRINT

# 2. Run the provisioning script
bash deploy/provision.sh
```

When the script creates or locates the Droplet, it requires the trusted
Ed25519 host fingerprint before the first SSH connection. If the value is not
already configured, it asks without echoing the input. In a separate
authenticated DigitalOcean console for that Droplet, obtain it directly from
the server:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

Enter the resulting `SHA256:` value at the prompt, or put the same value in the
gitignored `resources/.env.do` file for a noninteractive run. The trust rule is:
ssh-keyscan is discovery, not authentication. The provisioner accepts only the
offered Ed25519 key whose computed fingerprint exactly matches that independently
trusted value. A missing, malformed, or mismatched value stops the script
before its first SSH connection. The temporary `known_hosts` file is mode
`0600`, every provisioning SSH command requires strict host-key checking
against that file, and the file is removed when the script exits.

Before Step 10 starts any services, a fresh provision pauses at the external
OAuth allowlist checkpoint. In a separate SSH session, populate
`/opt/spotify-mcp-config/authenticated-emails.txt` without printing its
contents, then return to the provisioning command and press Enter. The script
reruns the regular/readable/non-empty preflight before it continues.

In a noninteractive run, the script exits before service startup when the
allowlist is not ready. After a separately authorized operator populates the
file, resume with:

```bash
DEPLOY_SHA="0123456789abcdef0123456789abcdef01234567"  # authorized full SHA
bash deploy/provision.sh --resume-after-allowlist "$DEPLOY_SHA"
```

This narrowly scoped mode locates the existing production Droplet, skips Steps
1-9, requires the requested immutable revision to be reachable from
`origin/main` and to use the external allowlist contract, then refuses to
continue unless it can check out that exact revision with a clean tracked and
untracked tree. It reruns the permission-aware allowlist checkpoint before any
service or database mutation and records the final deployed revision and health
result for the API check performed by initial provisioning. It does not recreate
or reconfigure the infrastructure, database, DNS, or production environment
file.

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
DROPLET_SSH_HOST_FINGERPRINT="SHA256:<trusted-ed25519-fingerprint>"

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
| `INTERNAL_API_KEY` | Auto-generated (URL-safe random; never printed) |
| `CORS_ALLOWED_ORIGINS` | `https://{DOMAIN}` |
| `OAUTH2_PROXY_COOKIE_SECRET` | Auto-generated (32-byte base64) |
| `GOOGLE_OAUTH_CLIENT_ID` | Manual — from Google Cloud Console |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Manual — from Google Cloud Console |

Email access control is managed outside the Git checkout at
`/opt/spotify-mcp-config/authenticated-emails.txt` (one email per line). The
parent directory is owned by `deploy:deploy` with mode `0750`; the file is
owned by `deploy:deploy` with mode `0644` so the non-root oauth2-proxy process
can read it through the read-only bind mount. See the
[Google OAuth setup guide](./google-oauth-setup.md) for complete instructions.

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
immutable, full 40-character commit SHA that is reachable from `origin/main`
and a fresh deployment UUID that identifies this one authorized dispatch.

### One-time external allowlist migration

Before the first deployment that uses the external allowlist mount, a
separately authorized operator must migrate the current server-side allowlist.
Do this while production is still on the legacy revision that tracks
`deploy/authenticated-emails.txt`. The commands below do not print the file or
its digest:

```bash
set -euo pipefail
cd /opt/spotify-mcp
LEGACY_ALLOWLIST="deploy/authenticated-emails.txt"
EXTERNAL_ALLOWLIST="/opt/spotify-mcp-config/authenticated-emails.txt"

test -f "$LEGACY_ALLOWLIST"
test -r "$LEGACY_ALLOWLIST"
test -s "$LEGACY_ALLOWLIST"
sudo install -d -o deploy -g deploy -m 0750 /opt/spotify-mcp-config
sudo install -o deploy -g deploy -m 0644 "$LEGACY_ALLOWLIST" "$EXTERNAL_ALLOWLIST"
test -f "$EXTERNAL_ALLOWLIST"
test -r "$EXTERNAL_ALLOWLIST"
test -s "$EXTERNAL_ALLOWLIST"
test "$(stat -c %s "$LEGACY_ALLOWLIST")" = "$(stat -c %s "$EXTERNAL_ALLOWLIST")"
cmp -s "$LEGACY_ALLOWLIST" "$EXTERNAL_ALLOWLIST"

# Remove the runtime edit from the tracked path and prove the checkout is exact.
git restore --source=HEAD -- "$LEGACY_ALLOWLIST"
test -z "$(git status --porcelain --untracked-files=all)"
```

Stop if any command fails. Do not dispatch the new workflow until the external
file passes both readability and non-empty checks and the Git checkout is
clean. Keep the authorization and monitoring evidence for the separately
authorized deployment; this repository change does not perform the migration.

If a separately authorized rollback selects a legacy Compose revision that
mounts the tracked path, restore the external file to that path after checking
out the legacy revision and before restarting its services:

This procedure is valid only after the operator records the accepted database
compatibility decision for the exact legacy revision. If migrations may have
started or applied and no accepted decision exists, stop. Set
`LEGACY_DEPLOY_SHA` to the separately authorized full revision; never use a
branch, tag, abbreviation, or current checkout.

```bash
set -euo pipefail
cd /opt/spotify-mcp
LEGACY_DEPLOY_SHA="0123456789abcdef0123456789abcdef01234567"
LEGACY_ALLOWLIST="deploy/authenticated-emails.txt"
EXTERNAL_ALLOWLIST="/opt/spotify-mcp-config/authenticated-emails.txt"

test -z "$(git status --porcelain --untracked-files=all)"
if ! [[ "$LEGACY_DEPLOY_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "ERROR: legacy revision must be exactly 40 hexadecimal characters"
  exit 1
fi
git fetch origin main:refs/remotes/origin/main
git cat-file -e "$LEGACY_DEPLOY_SHA^{commit}"
git merge-base --is-ancestor "$LEGACY_DEPLOY_SHA" origin/main
EXPECTED_LEGACY_SHA=$(git rev-parse "$LEGACY_DEPLOY_SHA^{commit}")
LEGACY_MOUNT="./deploy/authenticated-emails.txt:/etc/oauth2-proxy/authenticated-emails.txt:ro"
git show "${EXPECTED_LEGACY_SHA}:docker-compose.prod.yml" | grep -Fqx "      - $LEGACY_MOUNT"
git checkout --detach "$EXPECTED_LEGACY_SHA"
test "$(git rev-parse HEAD)" = "$EXPECTED_LEGACY_SHA"
test -z "$(git status --porcelain --untracked-files=all)"

test -f "$EXTERNAL_ALLOWLIST"
test -r "$EXTERNAL_ALLOWLIST"
test -s "$EXTERNAL_ALLOWLIST"
install -m 0644 "$EXTERNAL_ALLOWLIST" "$LEGACY_ALLOWLIST"
test "$(stat -c %s "$EXTERNAL_ALLOWLIST")" = "$(stat -c %s "$LEGACY_ALLOWLIST")"
cmp -s "$EXTERNAL_ALLOWLIST" "$LEGACY_ALLOWLIST"
git status --porcelain -- "$LEGACY_ALLOWLIST" | grep -Fqx " M $LEGACY_ALLOWLIST"
UNEXPECTED_CHANGES=$(git status --porcelain --untracked-files=all \
  | grep -Fvx " M $LEGACY_ALLOWLIST" || true)
test -z "$UNEXPECTED_CHANGES"

docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

wait_for_legacy_health() {
  local service="$1"
  local url="$2"
  for attempt in $(seq 1 30); do
    if docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T "$service" \
      curl -sf "$url" > /dev/null 2>&1; then
      return 0
    fi
    test "$attempt" -lt 30 \
      || { echo "ERROR: legacy $service health failed"; return 1; }
    sleep 5
  done
}
wait_for_legacy_health api http://localhost:8000/healthz
wait_for_legacy_health frontend http://localhost:8001/healthz
wait_for_legacy_health explorer http://localhost:8002/healthz
for attempt in $(seq 1 30); do
  if docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T caddy \
    wget -q -O /dev/null http://oauth2-proxy:4180/ping; then
    break
  fi
  test "$attempt" -lt 30 || { echo "ERROR: legacy oauth2-proxy health failed"; exit 1; }
  sleep 5
done

test "$(git rev-parse HEAD)" = "$EXPECTED_LEGACY_SHA"
git status --porcelain -- "$LEGACY_ALLOWLIST" | grep -Fqx " M $LEGACY_ALLOWLIST"
UNEXPECTED_CHANGES=$(git status --porcelain --untracked-files=all \
  | grep -Fvx " M $LEGACY_ALLOWLIST" || true)
test -z "$UNEXPECTED_CHANGES"
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
echo "LEGACY_ROLLBACK_REVISION=$EXPECTED_LEGACY_SHA"
echo "LEGACY_ROLLBACK_HEALTH_RESULT=healthy"
echo "LEGACY_ROLLBACK_POSTURE=legacy tracked allowlist restored from current external authorization state"
```

The resulting tracked-file modification is expected only for the legacy
configuration and is verified as the only dirty path before and after restart.
Preserve the exact revision, terminal API and oauth2-proxy health results,
database compatibility decision, and rollback-posture line as the monitored
operation's evidence. Do not run the new exact-SHA workflow against that dirty
checkout, and do not restart the legacy configuration without separate
rollback authorization.

### Prerequisites

- The change has been merged to `main` and any required repository review and
  checks have completed.
- The operator has separate authorization to change production.
- `gh` is authenticated for this repository, or the operator can use the
  repository's **Actions** tab.
- The exact candidate SHA is known; do not use a branch name, tag, abbreviated
  SHA, or the current checkout.
- A new deployment UUID will be generated after authorization. Never reuse an
  earlier deployment UUID, including for a retry or rollback.
- `/opt/spotify-mcp-config/authenticated-emails.txt` exists, is readable and
  non-empty, has a `deploy:deploy` mode-`0644` file behind a `deploy:deploy`
  mode-`0750` parent, and the production Git checkout is clean.
- The GitHub `production` environment contains
  `DROPLET_SSH_HOST_FINGERPRINT` with the same trusted Ed25519 `SHA256:` value
  obtained from the authenticated DigitalOcean console. Configure this
  protected environment secret out of band; never add its value to a pull
  request, repository file, issue, log, or deployment command.

Confirm the candidate before dispatching:

```bash
DEPLOY_SHA="0123456789abcdef0123456789abcdef01234567"  # replace with the full SHA
git fetch origin main:refs/remotes/origin/main
git rev-parse "$DEPLOY_SHA^{commit}"
git merge-base --is-ancestor "$DEPLOY_SHA" origin/main
ALLOWLIST_MOUNT="/opt/spotify-mcp-config/authenticated-emails.txt:/etc/oauth2-proxy/authenticated-emails.txt:ro"
git show "${DEPLOY_SHA}:docker-compose.prod.yml" | grep -Fqx "      - $ALLOWLIST_MOUNT"
```

All commands must succeed. Stop if the SHA is not 40 hexadecimal characters,
does not name a commit, is not reachable from `origin/main`, or does not use
the external OAuth allowlist mount. Use the separately authorized legacy
rollback procedure for a revision that fails the mount check.

### Dispatch and monitor

Use one of these paths after authorization:

```bash
set -euo pipefail
DEPLOYMENT_ID=$(python -c 'import uuid; print(uuid.uuid4())')
EXPECTED_RUN_TITLE="Deploy $DEPLOY_SHA to production [$DEPLOYMENT_ID]"
DISPATCHED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if ! DISPATCH_OUTPUT=$(gh workflow run deploy.yml \
  --ref main \
  -f commit_sha="$DEPLOY_SHA" \
  -f deployment_id="$DEPLOYMENT_ID" 2>&1); then
  printf '%s\n' "$DISPATCH_OUTPUT" >&2
  exit 1
fi
printf '%s\n' "$DISPATCH_OUTPUT"

# Prefer an exact run URL or numeric run ID returned by the dispatch command.
RUN_URL=$(printf '%s\n' "$DISPATCH_OUTPUT" \
  | sed -nE 's|.*(https://github.com/[^[:space:]]+/actions/runs/[0-9]+).*|\1|p' \
  | tail -n1)
RUN_ID=""
if [ -n "$RUN_URL" ]; then
  RUN_ID=${RUN_URL##*/}
else
  RETURNED_RUN_IDS=$(printf '%s\n' "$DISPATCH_OUTPUT" \
    | awk '{
        normalized = tolower($0)
        if (normalized ~ /^((run[ _-]?)?id[=: ]+)?[0-9]+$/) {
          sub(/^((run[ _-]?)?id[=: ]+)?/, "", normalized)
          print normalized
        }
      }')
  RETURNED_RUN_COUNT=$(printf '%s\n' "$RETURNED_RUN_IDS" \
    | awk 'NF { count++ } END { print count + 0 }')
  if [ "$RETURNED_RUN_COUNT" -gt 1 ]; then
    echo "ERROR: dispatch returned more than one run ID"
    exit 1
  fi
  if [ "$RETURNED_RUN_COUNT" -eq 1 ]; then
    RUN_ID=$(printf '%s\n' "$RETURNED_RUN_IDS" | awk 'NF { print; exit }')
  fi
fi

# Older gh versions may return neither value. Query only by the unique full
# SHA + deployment UUID title after the recorded dispatch time. Never fall back
# to the newest run or to a SHA-only match.
if [ -z "$RUN_ID" ]; then
  for attempt in $(seq 1 30); do
    MATCHING_RUNS=$(gh run list \
      --workflow deploy.yml \
      --event workflow_dispatch \
      --branch main \
      --limit 100 \
      --json databaseId,displayTitle,createdAt,url \
      --jq ".[] | select(.displayTitle == \"$EXPECTED_RUN_TITLE\" and .createdAt >= \"$DISPATCHED_AT\") | [.databaseId, .url] | @tsv")
    RUN_COUNT=$(printf '%s\n' "$MATCHING_RUNS" \
      | awk 'NF { count++ } END { print count + 0 }')
    if [ "$RUN_COUNT" -eq 1 ]; then
      RUN_ID=$(printf '%s\n' "$MATCHING_RUNS" | awk -F '\t' 'NF { print $1; exit }')
      RUN_URL=$(printf '%s\n' "$MATCHING_RUNS" | awk -F '\t' 'NF { print $2; exit }')
      break
    fi
    if [ "$RUN_COUNT" -gt 1 ]; then
      echo "ERROR: multiple runs match $EXPECTED_RUN_TITLE; do not guess"
      exit 1
    fi
    sleep 2
  done
fi
test -n "$RUN_ID" || { echo "ERROR: dispatched run was not found"; exit 1; }

ACTUAL_RUN_TITLE=$(gh run view "$RUN_ID" --json displayTitle --jq .displayTitle)
test "$ACTUAL_RUN_TITLE" = "$EXPECTED_RUN_TITLE" \
  || { echo "ERROR: run $RUN_ID does not match $EXPECTED_RUN_TITLE"; exit 1; }
RUN_URL=$(gh run view "$RUN_ID" --json url --jq .url)
printf 'Monitoring run %s at %s\n' "$RUN_ID" "$RUN_URL"
gh run watch "$RUN_ID" --exit-status
gh run view "$RUN_ID" --json databaseId,displayTitle,status,conclusion,url
```

Or in GitHub, open **Actions** → **Deploy to DigitalOcean** → **Run workflow**,
select the `main` workflow definition, enter `commit_sha` as the full SHA, and
enter a freshly generated UUID v4 as `deployment_id`. Select **Run workflow**
only after verifying both values against the authorization. Do not dispatch
from a branch or tag. Open the run whose title is exactly
`Deploy <the full SHA> to production [<the deployment UUID>]`, record its run ID
and URL, and monitor that exact run page. Stop if the title does not contain
both authorized values or if more than one run could match; never substitute
the newest run or a SHA-only match.

The workflow validates the SHA before deployment, runs lint, type checking, and
every service test suite against that exact revision, then captures a clean,
exact production commit in a separate successful job. The deploy job stops if
the production checkout changes after capture, fetches `origin/main`, validates
the requested SHA again, and checks out that exact revision in a clean detached
state. It verifies the allowlist's documented owner and modes and requires an
oauth2-proxy `/ping` response through the production service network before
reporting terminal health. It preserves the existing firewall handling,
Compose build, migration order, and collector restart sequence.

The workflow's health evidence is deliberately internal and bounded. It calls
the API, Frontend, and Explorer `/healthz` handlers from their containers;
those handlers report process availability and version only. It separately
runs the API database-connectivity check, queries oauth2-proxy `/ping` from
Caddy's service network, and records Compose service status. It does not probe
the public Caddy endpoint and therefore does not establish public DNS, TLS
certificate, external routing, Spotify connectivity, or complete dependency
readiness. An operator may run the public `curl` below as separate evidence,
but the deployment workflow does not produce or claim that evidence.

Every production SSH action authenticates the offered host key against the
`production` environment fingerprint. A missing or malformed secret fails
before production SSH begins; a fingerprint mismatch is rejected by the SSH
action. Stop and verify the server identity through the authenticated
DigitalOcean console. Do not weaken host checking, replace the trusted value
with `ssh-keyscan` output, or configure the secret in a pull request.

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
captured full SHA as `commit_sha` and a newly generated `deployment_id`.
Generic workflow redispatch is limited to revisions whose production Compose
file uses the external allowlist mount; validation rejects older revisions
before production contact. Do not dispatch the workflow for a legacy revision.
Follow the separately authorized legacy procedure above so the current
external authorization state is copied into the legacy tracked path before
its services restart.

If a database decision is required, any older-code redispatch must follow its
accepted outcome. In either case, monitor the exact authorized operation to a
terminal result using the same success evidence. Do not use `main`, a branch,
a tag, or a local `git reset` as a rollback mechanism.

### GitHub Secrets

`provision.sh` configures the repository connection secrets below. To update
them manually:

| Secret | Description |
|--------|-------------|
| `DROPLET_IP` | Droplet public IPv4 |
| `SSH_PRIVATE_KEY` | Ed25519 private key for `deploy` user |

```bash
gh secret set DROPLET_IP --repo gmyuval/spotify-mcp-history-collector --body "YOUR_IP"
gh secret set SSH_PRIVATE_KEY --repo gmyuval/spotify-mcp-history-collector < deploy/.deploy-key
```

Separately, configure `DROPLET_SSH_HOST_FINGERPRINT` as a protected secret on
the repository's **Settings → Environments → production** page. Its value must
be the trusted Ed25519 `SHA256:` fingerprint obtained through the authenticated
DigitalOcean console, not output copied from an unauthenticated network scan.
The provisioner and pull requests intentionally do not create or update this
production-environment secret.

## File Reference

| File | Purpose |
|------|---------|
| `docker-compose.prod.yml` | Production service definitions (no local Postgres, Caddy, production uvicorn) |
| `deploy/Caddyfile` | Reverse proxy routes with automatic HTTPS and forward_auth |
| `deploy/authenticated-emails.txt.example` | Non-sensitive format example for the external oauth2-proxy allowlist |
| `deploy/provision.sh` | One-time automated provisioning script |
| `.github/workflows/deploy.yml` | Manual, immutable-revision production deployment workflow |
| `.env.prod.example` | Template for production environment variables |
| `resources/.env.do` | Provisioning parameters (not committed — gitignored) |
| `docs/google-oauth-setup.md` | Google OAuth setup guide for oauth2-proxy |

## Manual Operations

### SSH to the Droplet

```bash
# These commands use the operator's independently verified default known_hosts.
# As deploy user (for app operations)
ssh -o StrictHostKeyChecking=yes deploy@DROPLET_IP

# As root (for system administration)
ssh -o StrictHostKeyChecking=yes root@DROPLET_IP
```

### View logs

```bash
ssh -o StrictHostKeyChecking=yes deploy@DROPLET_IP
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
Except for the separately authorized legacy allowlist rollback procedure above,
do not deploy or roll back directly over SSH; that bypasses immutable-SHA
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

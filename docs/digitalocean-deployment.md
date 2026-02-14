# DigitalOcean Deployment Guide

Deploy the Spotify MCP History Collector to a DigitalOcean Droplet with
Docker Compose, Caddy (automatic HTTPS), and GitHub Actions CI/CD.

## Architecture

```
                Internet
                   │
                   ▼
          ┌────────────────┐
          │   Caddy :443   │  Automatic HTTPS (Let's Encrypt)
          └───────┬────────┘
                  │
       ┌──────────┴──────────┐
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

| Path | Backend |
|------|---------|
| `/auth/*` | API |
| `/admin/*` | API |
| `/mcp/*` | API |
| `/history/*` | API |
| `/healthz` | API |
| `/*` | Frontend |

## Prerequisites

- [doctl](https://docs.digitalocean.com/reference/doctl/how-to/install/)
  authenticated (`doctl auth init`)
- [gh](https://cli.github.com/) CLI authenticated (`gh auth login`)
- Python 3.x available locally (for generating encryption keys)
- An existing DigitalOcean Managed PostgreSQL cluster in Frankfurt (fra1)
- A domain name with DNS managed by DigitalOcean
- A Spotify Developer application
  ([dashboard](https://developer.spotify.com/dashboard))

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

**Only remaining manual step:** Add
`https://yourdomain.com/auth/callback` as a Redirect URI in your
[Spotify Developer Dashboard](https://developer.spotify.com/dashboard).

## Configuration

### `resources/.env.do` (provisioning parameters)

```bash
DOMAIN_NAME=music.example.com
SSH_KEY_NAME=my-ssh-key        # Name from: doctl compute ssh-key list
SPOTIFY_CLIENT_ID=abc123...
SPOTIFY_CLIENT_SECRET=xyz789...
DROPLET_SIZE=s-2vcpu-2gb       # $18/mo — sufficient for all services
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

For the full template with all available options, see `.env.prod.example`.

### SSL / asyncpg Note

DigitalOcean Managed PostgreSQL requires SSL (`sslmode=require`).
The asyncpg driver uses a different parameter name: `ssl=require`.
The `DATABASE_URL` in `.env.prod` is configured with `?ssl=require`
which asyncpg understands natively. No application code changes needed.

## CI/CD (GitHub Actions)

After provisioning, all deploys are automatic:

- **Trigger:** Push to `main` branch, or manual dispatch from the
  Actions tab
- **Workflow:** `.github/workflows/deploy.yml`
- **Process:**
  1. SSH to Droplet as `deploy` user
  2. Pull latest code from `main`
  3. Build Docker images on the Droplet
  4. Restart services with zero-config rolling update
  5. Wait for API health check
  6. Run database migrations (Alembic)
  7. Verify all services

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
| `deploy/Caddyfile` | Reverse proxy routes with automatic HTTPS |
| `deploy/provision.sh` | One-time automated provisioning script |
| `.github/workflows/deploy.yml` | CI/CD pipeline (deploy on push to main) |
| `.env.prod.example` | Template for production environment variables |
| `resources/.env.do` | Provisioning parameters (not committed — gitignored) |

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

### Manual deploy (without CI/CD)

```bash
ssh deploy@DROPLET_IP
cd /opt/spotify-mcp
git fetch origin main && git reset --hard origin/main
docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
docker compose --env-file .env.prod -f docker-compose.prod.yml exec api alembic upgrade head
```

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

#!/usr/bin/env bash
# =============================================================================
# provision.sh — Automated DigitalOcean deployment for Spotify MCP
#
# Provisions a droplet, configures networking, deploys the app, and sets up
# GitHub Actions CI/CD. Run from the project root on your local machine.
#
# Prerequisites:
#   - doctl auth init   (DigitalOcean CLI authenticated)
#   - gh auth login     (GitHub CLI authenticated)
#   - ssh-keygen        (available in PATH)
#
# Usage:
#   bash deploy/provision.sh
#   bash deploy/provision.sh --resume-after-allowlist <full-commit-sha>
#
# Configuration is read from resources/.env.do:
#   DOMAIN_NAME, SSH_KEY_NAME, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
#   DROPLET_SIZE, DB_EXTERNAL_HOST, DB_PRIVATE_HOST, DB_PORT, DB_USER,
#   DB_PASSWORD, DB_NAME, DB_CLUSTER_ID
# =============================================================================
set -euo pipefail

RESUME_AFTER_ALLOWLIST=false
RESUME_DEPLOY_SHA=""
case "${1:-}" in
    "")
        [[ "$#" -eq 0 ]] || exit 2
        ;;
    --resume-after-allowlist)
        if [[ "$#" -ne 2 ]]; then
            echo "Usage: bash deploy/provision.sh --resume-after-allowlist <full-commit-sha>" >&2
            exit 2
        fi
        RESUME_AFTER_ALLOWLIST=true
        RESUME_DEPLOY_SHA="$2"
        if ! [[ "$RESUME_DEPLOY_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
            echo "ERROR: resume revision must be a full 40-character commit SHA" >&2
            exit 2
        fi
        ;;
    *)
        echo "Usage: bash deploy/provision.sh [--resume-after-allowlist <full-commit-sha>]" >&2
        exit 2
        ;;
esac

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/resources/.env.do"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Create it with the required parameters."
    exit 1
fi

# shellcheck source=/dev/null
source "$ENV_FILE"

# Validate required variables
for var in DOMAIN_NAME SSH_KEY_NAME SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET DROPLET_SIZE \
           DB_EXTERNAL_HOST DB_PRIVATE_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME \
           DB_CLUSTER_ID; do
    if [[ -z "${!var:-}" ]]; then
        echo "ERROR: $var is not set in $ENV_FILE"
        exit 1
    fi
done

DROPLET_NAME="spotify-mcp-prod"
REGION="fra1"
IMAGE="ubuntu-24-04-x64"
PROJECT_PATH="/opt/spotify-mcp"
GITHUB_REPO="gmyuval/spotify-mcp-history-collector"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
log() { echo "=== $1 ==="; }
err() { echo "ERROR: $1" >&2; exit 1; }

wait_for_ssh() {
    local ip="$1"
    local max_attempts=30
    log "Waiting for SSH on $ip"
    for i in $(seq 1 $max_attempts); do
        if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "root@$ip" "echo ok" &>/dev/null; then
            echo "SSH is ready"
            return 0
        fi
        echo "  Attempt $i/$max_attempts..."
        sleep 10
    done
    err "SSH not available after $max_attempts attempts"
}

# ---------------------------------------------------------------------------
# Step 1: Look up SSH key ID
# ---------------------------------------------------------------------------
if [[ "$RESUME_AFTER_ALLOWLIST" == "false" ]]; then
log "Step 1: Looking up SSH key '$SSH_KEY_NAME'"
SSH_KEY_ID=$(doctl compute ssh-key list --format ID,Name --no-header | grep "$SSH_KEY_NAME" | awk '{print $1}')
if [[ -z "$SSH_KEY_ID" ]]; then
    echo "Available SSH keys:"
    doctl compute ssh-key list --format ID,Name,FingerPrint
    err "SSH key '$SSH_KEY_NAME' not found"
fi
echo "  SSH Key ID: $SSH_KEY_ID"

# ---------------------------------------------------------------------------
# Step 2: Find VPC in Frankfurt (same as managed DB)
# ---------------------------------------------------------------------------
log "Step 2: Finding VPC in $REGION"
VPC_ID=$(doctl vpcs list --format ID,Region --no-header | grep "$REGION" | head -1 | awk '{print $1}')
if [[ -z "$VPC_ID" ]]; then
    err "No VPC found in $REGION. Create one in the DigitalOcean console first."
fi
echo "  VPC ID: $VPC_ID"

# ---------------------------------------------------------------------------
# Step 3: Create Droplet
# ---------------------------------------------------------------------------
log "Step 3: Creating droplet '$DROPLET_NAME'"

# Check if droplet already exists
EXISTING=$(doctl compute droplet list --format ID,Name --no-header | grep "$DROPLET_NAME" | awk '{print $1}' || true)
if [[ -n "$EXISTING" ]]; then
    echo "  Droplet '$DROPLET_NAME' already exists (ID: $EXISTING). Skipping creation."
    DROPLET_ID="$EXISTING"
else
    DROPLET_ID=$(doctl compute droplet create "$DROPLET_NAME" \
        --region "$REGION" \
        --image "$IMAGE" \
        --size "$DROPLET_SIZE" \
        --ssh-keys "$SSH_KEY_ID" \
        --vpc-uuid "$VPC_ID" \
        --enable-monitoring \
        --tag-names "spotify-mcp,production" \
        --wait \
        --format ID \
        --no-header)
    echo "  Droplet created (ID: $DROPLET_ID)"
fi

# Get public IP
DROPLET_IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)
echo "  Public IP: $DROPLET_IP"

# ---------------------------------------------------------------------------
# Step 4: Configure DO Cloud Firewall
# ---------------------------------------------------------------------------
log "Step 4: Configuring cloud firewall"

FW_NAME="spotify-mcp-fw"
EXISTING_FW=$(doctl compute firewall list --format ID,Name --no-header | grep "$FW_NAME" | awk '{print $1}' || true)

if [[ -n "$EXISTING_FW" ]]; then
    echo "  Firewall '$FW_NAME' already exists. Updating droplet assignment."
    doctl compute firewall add-droplets "$EXISTING_FW" --droplet-ids "$DROPLET_ID"
else
    doctl compute firewall create \
        --name "$FW_NAME" \
        --droplet-ids "$DROPLET_ID" \
        --inbound-rules "protocol:tcp,ports:22,address:0.0.0.0/0,address:::/0 protocol:tcp,ports:80,address:0.0.0.0/0,address:::/0 protocol:tcp,ports:443,address:0.0.0.0/0,address:::/0" \
        --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0,address:::/0 protocol:udp,ports:all,address:0.0.0.0/0,address:::/0 protocol:icmp,address:0.0.0.0/0,address:::/0" \
        --format ID,Name \
        --no-header
    echo "  Firewall created"
fi

# ---------------------------------------------------------------------------
# Step 5: Add droplet to database trusted sources
# ---------------------------------------------------------------------------
log "Step 5: Adding droplet to database trusted sources"

echo "  Database cluster ID: $DB_CLUSTER_ID"
# Add the droplet as a trusted source
doctl databases firewalls append "$DB_CLUSTER_ID" --rule "droplet:$DROPLET_ID" || \
    echo "  Note: Droplet may already be a trusted source"

# ---------------------------------------------------------------------------
# Step 6: Create DNS A record
# ---------------------------------------------------------------------------
log "Step 6: Creating DNS A record for $DOMAIN_NAME"

# Extract the base domain and subdomain
# e.g., music.praxiscode.dev -> base=praxiscode.dev, sub=music
BASE_DOMAIN=$(echo "$DOMAIN_NAME" | rev | cut -d. -f1-2 | rev)
SUBDOMAIN=$(echo "$DOMAIN_NAME" | sed "s/\.$BASE_DOMAIN$//")

if [[ "$SUBDOMAIN" == "$DOMAIN_NAME" ]]; then
    # No subdomain (bare domain)
    SUBDOMAIN="@"
fi

echo "  Base domain: $BASE_DOMAIN, Subdomain: $SUBDOMAIN"

# Check if record already exists
EXISTING_RECORD=$(doctl compute domain records list "$BASE_DOMAIN" --format ID,Type,Name --no-header 2>/dev/null | grep "A.*$SUBDOMAIN" | awk '{print $1}' || true)

if [[ -n "$EXISTING_RECORD" ]]; then
    echo "  DNS record already exists (ID: $EXISTING_RECORD). Updating IP."
    doctl compute domain records update "$BASE_DOMAIN" --record-id "$EXISTING_RECORD" --record-data "$DROPLET_IP"
else
    doctl compute domain records create "$BASE_DOMAIN" \
        --record-type A \
        --record-name "$SUBDOMAIN" \
        --record-data "$DROPLET_IP" \
        --record-ttl 300
    echo "  DNS A record created: $DOMAIN_NAME -> $DROPLET_IP"
fi

# ---------------------------------------------------------------------------
# Step 7: Wait for SSH and set up the droplet
# ---------------------------------------------------------------------------
wait_for_ssh "$DROPLET_IP"

log "Step 7: Setting up droplet via SSH"

ssh -o StrictHostKeyChecking=no "root@$DROPLET_IP" bash -s <<'REMOTE_SETUP'
set -euo pipefail

echo "--- System update ---"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get upgrade -y -qq

echo "--- Install Docker ---"
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
fi
docker compose version

echo "--- Install PostgreSQL client ---"
apt-get install -y -qq postgresql-client

echo "--- Create deploy user ---"
if ! id "deploy" &>/dev/null; then
    useradd -m -s /bin/bash -G docker deploy
    mkdir -p /home/deploy/.ssh
    cp /root/.ssh/authorized_keys /home/deploy/.ssh/
    chown -R deploy:deploy /home/deploy/.ssh
    chmod 700 /home/deploy/.ssh
    chmod 600 /home/deploy/.ssh/authorized_keys
    echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
    echo "  Created deploy user"
else
    echo "  deploy user already exists"
fi

echo "--- Configure external OAuth allowlist path ---"
AUTHENTICATED_EMAILS_FILE="/opt/spotify-mcp-config/authenticated-emails.txt"
install -d -o deploy -g deploy -m 0750 /opt/spotify-mcp-config
if [[ -e "$AUTHENTICATED_EMAILS_FILE" && ! -f "$AUTHENTICATED_EMAILS_FILE" ]]; then
    echo "ERROR: $AUTHENTICATED_EMAILS_FILE exists but is not a regular file"
    exit 1
fi
if [[ ! -e "$AUTHENTICATED_EMAILS_FILE" ]]; then
    install -o deploy -g deploy -m 0644 /dev/null "$AUTHENTICATED_EMAILS_FILE"
    echo "  Created empty $AUTHENTICATED_EMAILS_FILE; populate it before Step 10"
else
    chown deploy:deploy "$AUTHENTICATED_EMAILS_FILE"
    chmod 0644 "$AUTHENTICATED_EMAILS_FILE"
fi

echo "--- Configure UFW ---"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
echo "y" | ufw enable
ufw status

echo "--- Add swap ---"
if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "  1GB swap added"
fi

echo "--- Clone repository ---"
PROJECT_DIR="/opt/spotify-mcp"
if [[ ! -d "$PROJECT_DIR" ]]; then
    git clone https://github.com/gmyuval/spotify-mcp-history-collector.git "$PROJECT_DIR"
    chown -R deploy:deploy "$PROJECT_DIR"
    echo "  Repository cloned"
else
    cd "$PROJECT_DIR"
    git fetch origin main
    git reset --hard origin/main
    chown -R deploy:deploy "$PROJECT_DIR"
    echo "  Repository updated"
fi

echo "--- Docker log rotation ---"
cat > /etc/docker/daemon.json << 'DAEMON_EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
DAEMON_EOF
systemctl restart docker

echo "--- Droplet setup complete ---"
REMOTE_SETUP

# ---------------------------------------------------------------------------
# Step 8: Create the spotify_mcp database
# ---------------------------------------------------------------------------
log "Step 8: Creating database '$DB_NAME'"

ssh -o StrictHostKeyChecking=no "root@$DROPLET_IP" bash -s -- \
  "$DB_USER" "$DB_PASSWORD" "$DB_EXTERNAL_HOST" "$DB_PORT" "$DB_NAME" <<'REMOTE_DB'
set -euo pipefail
DB_USER="$1"
DB_PASSWORD="$2"
DB_EXTERNAL_HOST="$3"
DB_PORT="$4"
DB_NAME="$5"
# Check if database already exists, create if not
if psql "postgresql://$DB_USER:$DB_PASSWORD@$DB_EXTERNAL_HOST:$DB_PORT/defaultdb?sslmode=require" \
    -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "  Database '$DB_NAME' already exists"
else
    psql "postgresql://$DB_USER:$DB_PASSWORD@$DB_EXTERNAL_HOST:$DB_PORT/defaultdb?sslmode=require" \
        -c "CREATE DATABASE $DB_NAME;"
    echo "  Database '$DB_NAME' created"
fi
REMOTE_DB

# ---------------------------------------------------------------------------
# Step 9: Generate and upload .env.prod
# ---------------------------------------------------------------------------
log "Step 9: Generating .env.prod"

# Verify Python cryptography is available
if ! python -c "from cryptography.fernet import Fernet" 2>/dev/null; then
    err "Python 'cryptography' package required. Install with: pip install cryptography"
fi

# Generate secrets locally
TOKEN_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
ADMIN_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
OAUTH2_PROXY_COOKIE_SECRET=$(python -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_PRIVATE_HOST}:${DB_PORT}/${DB_NAME}?ssl=require"

ENV_PROD_CONTENT="# Production environment — generated by provision.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)

DOMAIN=${DOMAIN_NAME}

DATABASE_URL=${DATABASE_URL}

SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID}
SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET}
SPOTIFY_REDIRECT_URI=https://${DOMAIN_NAME}/auth/callback

TOKEN_ENCRYPTION_KEY=${TOKEN_ENCRYPTION_KEY}

ADMIN_AUTH_MODE=token
ADMIN_TOKEN=${ADMIN_TOKEN}

CORS_ALLOWED_ORIGINS=https://${DOMAIN_NAME}

FRONTEND_AUTH_MODE=token

COLLECTOR_INTERVAL_SECONDS=600
INITIAL_SYNC_ENABLED=true
INITIAL_SYNC_MAX_DAYS=30
INITIAL_SYNC_MAX_REQUESTS=200
INITIAL_SYNC_CONCURRENCY=2

IMPORT_MAX_ZIP_SIZE_MB=500
IMPORT_MAX_RECORDS=5000000

RATE_LIMIT_AUTH_PER_MINUTE=10
RATE_LIMIT_MCP_PER_MINUTE=60

LOG_RETENTION_DAYS=90

# Google OAuth (for oauth2-proxy)
# IMPORTANT: Fill these in after creating Google OAuth credentials
# See docs/google-oauth-setup.md for instructions
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
OAUTH2_PROXY_COOKIE_SECRET=${OAUTH2_PROXY_COOKIE_SECRET}
"

echo "$ENV_PROD_CONTENT" | ssh -o StrictHostKeyChecking=no "root@$DROPLET_IP" \
    "cat > $PROJECT_PATH/.env.prod && chown deploy:deploy $PROJECT_PATH/.env.prod && chmod 600 $PROJECT_PATH/.env.prod"

echo "  .env.prod uploaded to droplet"
echo ""
echo "  ADMIN_TOKEN: $ADMIN_TOKEN"
echo "  OAUTH2_PROXY_COOKIE_SECRET: (auto-generated, already in .env.prod)"
echo "  (Save the admin token — you'll need it for MCP/ChatGPT access)"
echo "  WARNING: Clear your terminal history after saving the token."
echo ""
echo "  NOTE: Google OAuth credentials (GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET)"
echo "  are left blank. You must fill them in on the droplet before oauth2-proxy will work."
echo "  See docs/google-oauth-setup.md for setup instructions."
echo ""

else
    log "Resume: locating existing droplet and skipping Steps 1-9"
    mapfile -t MATCHING_DROPLETS < <(
        doctl compute droplet list --format ID,Name --no-header \
            | awk -v name="$DROPLET_NAME" '$2 == name {print $1}'
    )
    if [[ "${#MATCHING_DROPLETS[@]}" -ne 1 ]]; then
        err "resume requires exactly one existing '$DROPLET_NAME' droplet"
    fi
    DROPLET_ID="${MATCHING_DROPLETS[0]}"
    DROPLET_IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)
    [[ -n "$DROPLET_IP" ]] || err "existing droplet has no public IPv4 address"
    ADMIN_TOKEN="unchanged (resume mode does not read it)"
    wait_for_ssh "$DROPLET_IP"

    RESUME_CAPTURE=$(ssh -o StrictHostKeyChecking=no "deploy@$DROPLET_IP" bash -s -- \
        "$RESUME_DEPLOY_SHA" <<'REMOTE_RESUME'
set -euo pipefail
RESUME_DEPLOY_SHA="$1"
cd /opt/spotify-mcp
[[ -z "$(git status --porcelain --untracked-files=all)" ]] \
    || { echo "ERROR: resume checkout has tracked or untracked changes" >&2; exit 1; }
git fetch origin main:refs/remotes/origin/main
git cat-file -e "$RESUME_DEPLOY_SHA^{commit}" \
    || { echo "ERROR: resume revision does not exist" >&2; exit 1; }
git merge-base --is-ancestor "$RESUME_DEPLOY_SHA" origin/main \
    || { echo "ERROR: resume revision is not reachable from origin/main" >&2; exit 1; }
ALLOWLIST_MOUNT="/opt/spotify-mcp-config/authenticated-emails.txt:/etc/oauth2-proxy/authenticated-emails.txt:ro"
git show "${RESUME_DEPLOY_SHA}:docker-compose.prod.yml" \
    | grep -Fqx "      - $ALLOWLIST_MOUNT" \
    || { echo "ERROR: resume revision lacks the external OAuth allowlist contract" >&2; exit 1; }
EXPECTED_RESUME_SHA=$(git rev-parse "$RESUME_DEPLOY_SHA^{commit}")
git checkout --detach "$EXPECTED_RESUME_SHA"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_RESUME_SHA" ]] \
    || { echo "ERROR: resume checkout did not land on the requested revision" >&2; exit 1; }
[[ -z "$(git status --porcelain --untracked-files=all)" ]] \
    || { echo "ERROR: exact resume checkout is not clean" >&2; exit 1; }
echo "RESUME_DEPLOY_SHA=$EXPECTED_RESUME_SHA"
REMOTE_RESUME
    )
    INITIAL_DEPLOY_SHA=$(printf '%s\n' "$RESUME_CAPTURE" | sed -n 's/^RESUME_DEPLOY_SHA=//p')
    [[ "$INITIAL_DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] \
        || err "resume did not return exactly one immutable revision"
fi

if [[ "$RESUME_AFTER_ALLOWLIST" == "false" ]]; then
    INITIAL_DEPLOY_SHA=$(ssh -o StrictHostKeyChecking=no "deploy@$DROPLET_IP" \
        "cd '$PROJECT_PATH' && git rev-parse --verify HEAD^{commit}")
    [[ "$INITIAL_DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] \
        || err "initial checkout is not an immutable revision"
fi

# ---------------------------------------------------------------------------
# Pre-Step-10 operator checkpoint
# ---------------------------------------------------------------------------
log "Pre-Step-10: Verifying external OAuth allowlist"
AUTHENTICATED_EMAILS_FILE="/opt/spotify-mcp-config/authenticated-emails.txt"

allowlist_ready() {
    ssh -o StrictHostKeyChecking=no "deploy@$DROPLET_IP" \
        "test -f '$AUTHENTICATED_EMAILS_FILE' && test -r '$AUTHENTICATED_EMAILS_FILE' && test -s '$AUTHENTICATED_EMAILS_FILE' && test \"\$(stat -c '%a:%U:%G' '${AUTHENTICATED_EMAILS_FILE%/*}')\" = '750:deploy:deploy' && test \"\$(stat -c '%a:%U:%G' '$AUTHENTICATED_EMAILS_FILE')\" = '644:deploy:deploy'"
}

if allowlist_ready; then
    echo "  External OAuth allowlist is ready"
else
    echo "  External OAuth allowlist is missing, unreadable, or empty."
    echo "  Populate $AUTHENTICATED_EMAILS_FILE in a separate SSH session without printing it."
    if [[ -t 0 ]]; then
        read -r -p "Press Enter after the allowlist is populated: "
    else
        err "populate the allowlist, then rerun with --resume-after-allowlist and the authorized full SHA"
    fi
fi

allowlist_ready || err "external OAuth allowlist is still missing, unreadable, or empty"

# ---------------------------------------------------------------------------
# Step 10: Initial deployment
# ---------------------------------------------------------------------------
log "Step 10: Running initial deployment"

ssh -o StrictHostKeyChecking=no "deploy@$DROPLET_IP" bash -s -- "$INITIAL_DEPLOY_SHA" <<REMOTE_DEPLOY
set -euo pipefail
EXPECTED_INITIAL_SHA="\$1"
AUTHENTICATED_EMAILS_FILE="/opt/spotify-mcp-config/authenticated-emails.txt"
if [[ ! -f "\$AUTHENTICATED_EMAILS_FILE" || ! -r "\$AUTHENTICATED_EMAILS_FILE" ]]; then
    echo "ERROR: external OAuth allowlist is missing or unreadable"
    exit 1
fi
if [[ ! -s "\$AUTHENTICATED_EMAILS_FILE" ]]; then
    echo "ERROR: external OAuth allowlist is empty; configure it before starting services"
    exit 1
fi
AUTHENTICATED_EMAILS_DIR="\${AUTHENTICATED_EMAILS_FILE%/*}"
if [[ "\$(stat -c '%a:%U:%G' "\$AUTHENTICATED_EMAILS_DIR")" != "750:deploy:deploy" ]]; then
    echo "ERROR: external OAuth allowlist directory must be deploy:deploy mode 0750"
    exit 1
fi
if [[ "\$(stat -c '%a:%U:%G' "\$AUTHENTICATED_EMAILS_FILE")" != "644:deploy:deploy" ]]; then
    echo "ERROR: external OAuth allowlist must be deploy:deploy mode 0644 for the non-root consumer"
    exit 1
fi
cd $PROJECT_PATH
[[ "\$(git rev-parse HEAD)" == "\$EXPECTED_INITIAL_SHA" ]] \
    || { echo "ERROR: initial deployment revision changed before service mutation"; exit 1; }
[[ -z "\$(git status --porcelain --untracked-files=all)" ]] \
    || { echo "ERROR: initial deployment checkout is not clean"; exit 1; }

echo "--- Building images ---"
docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull

echo "--- Starting services ---"
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

echo "--- Waiting for API health ---"
for i in \$(seq 1 30); do
    if docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T api curl -sf http://localhost:8000/healthz > /dev/null 2>&1; then
        echo "API is healthy"
        break
    fi
    if [ "\$i" -eq 30 ]; then
        echo "ERROR: API health check failed"
        docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=50 api
        exit 1
    fi
    echo "  Waiting... (\$i/30)"
    sleep 5
done

echo "--- Running migrations ---"
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T api alembic upgrade head

echo "--- Verifying post-migration API health ---"
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T api curl -sf http://localhost:8000/healthz > /dev/null

echo "--- Service status ---"
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
FINAL_INITIAL_SHA=\$(git rev-parse --verify HEAD^{commit})
[[ "\$FINAL_INITIAL_SHA" == "\$EXPECTED_INITIAL_SHA" ]] \
    || { echo "ERROR: initial deployment revision changed during service mutation"; exit 1; }
echo "INITIAL_DEPLOY_REVISION=\$FINAL_INITIAL_SHA"
echo "INITIAL_DEPLOY_API_HEALTH_RESULT=healthy"
REMOTE_DEPLOY

# ---------------------------------------------------------------------------
# Step 11: Generate SSH deploy key for CI/CD
# ---------------------------------------------------------------------------
log "Step 11: Setting up CI/CD deploy key"

DEPLOY_KEY_PATH="$PROJECT_ROOT/deploy/.deploy-key"

if [[ -f "$DEPLOY_KEY_PATH" ]]; then
    echo "  Deploy key already exists at $DEPLOY_KEY_PATH"
else
    ssh-keygen -t ed25519 -f "$DEPLOY_KEY_PATH" -N "" -C "github-actions-deploy"
    echo "  Deploy key generated"
fi

# Add public key to deploy user's authorized_keys on the droplet
DEPLOY_PUB_KEY=$(cat "${DEPLOY_KEY_PATH}.pub")
ssh -o StrictHostKeyChecking=no "root@$DROPLET_IP" bash -s <<REMOTE_KEY
if ! grep -q "github-actions-deploy" /home/deploy/.ssh/authorized_keys 2>/dev/null; then
    echo "$DEPLOY_PUB_KEY" >> /home/deploy/.ssh/authorized_keys
    echo "  Deploy key added to droplet"
else
    echo "  Deploy key already present on droplet"
fi
REMOTE_KEY

# ---------------------------------------------------------------------------
# Step 12: Set GitHub Secrets
# ---------------------------------------------------------------------------
log "Step 12: Setting GitHub Secrets"

DEPLOY_PRIVATE_KEY=$(cat "$DEPLOY_KEY_PATH")

gh secret set DROPLET_IP --repo "$GITHUB_REPO" --body "$DROPLET_IP"
gh secret set SSH_PRIVATE_KEY --repo "$GITHUB_REPO" --body "$DEPLOY_PRIVATE_KEY"

echo "  GitHub Secrets configured"

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
echo ""
log "Provisioning Complete!"
echo ""
echo "  Droplet IP:    $DROPLET_IP"
echo "  Domain:        https://$DOMAIN_NAME"
echo "  Admin Token:   $ADMIN_TOKEN"
echo "  Frontend:      https://$DOMAIN_NAME"
echo "  API Health:    https://$DOMAIN_NAME/healthz"
echo ""
echo "  REMAINING MANUAL STEPS:"
echo ""
echo "  1. Spotify — Go to https://developer.spotify.com/dashboard"
echo "     Add this Redirect URI to your Spotify app:"
echo "       https://$DOMAIN_NAME/auth/callback"
echo ""
echo "  2. Google OAuth — See docs/google-oauth-setup.md"
echo "     a. Create OAuth credentials at https://console.cloud.google.com/apis/credentials"
echo "     b. Set redirect URI: https://$DOMAIN_NAME/oauth2/callback"
echo "     c. SSH to the droplet and edit $PROJECT_PATH/.env.prod:"
echo "        - Set GOOGLE_OAUTH_CLIENT_ID"
echo "        - Set GOOGLE_OAUTH_CLIENT_SECRET"
echo "     d. Add your email to /opt/spotify-mcp-config/authenticated-emails.txt"
echo "     e. Restart: cd $PROJECT_PATH && docker compose --env-file .env.prod -f docker-compose.prod.yml up -d"
echo ""
echo "  Future deploys use the separately authorized manual GitHub Actions workflow."
echo ""

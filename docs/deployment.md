# Deployment Guide

This guide covers deploying the Spotify MCP History Collector system, which consists of four containerized services:

| Service    | Port | Description                                      |
|------------|------|--------------------------------------------------|
| API        | 8000 | FastAPI — Spotify OAuth, MCP tool endpoints, admin APIs |
| Collector  | —    | Python worker — polls Spotify, processes ZIP imports    |
| Frontend   | 8001 | FastAPI — admin management UI                          |
| PostgreSQL | 5432 | Data storage (exposed as 5434 on host by default)      |

---

## Prerequisites

- **Docker** and **Docker Compose v2+** installed and running
- A **domain name** (for production HTTPS deployments)
- A **Spotify Developer account** with an app created at https://developer.spotify.com/dashboard
- **Git** to clone the repository

---

## 1. Spotify Developer Setup

1. Go to https://developer.spotify.com/dashboard and log in.
2. Click **Create App**.
3. Fill in the app name and description. For Redirect URI, enter `http://localhost:8000/auth/callback` (you will update this for production later).
4. Note the **Client ID** and **Client Secret** from the app settings page.
5. Under **Users and Access**, add every Spotify account that will use the system. This is required while the app is in Development Mode. Spotify limits development apps to explicitly added users only.
6. If you need more than 25 users, you must submit your app for Spotify's Extended Quota Mode review.

---

## 2. Clone and Configure

```bash
git clone <repo-url>
cd spotify-mcp-history-collector
cp .env.example .env
```

Open `.env` in your editor and configure each variable:

### Database

| Variable            | Description                                | Default    |
|---------------------|--------------------------------------------|------------|
| `POSTGRES_PASSWORD` | PostgreSQL password. Change in production. | `postgres` |

### Spotify OAuth

| Variable                 | Description                                                        | Default                                   |
|--------------------------|--------------------------------------------------------------------|-------------------------------------------|
| `SPOTIFY_CLIENT_ID`     | Client ID from your Spotify app                                    | _(required)_                              |
| `SPOTIFY_CLIENT_SECRET`  | Client Secret from your Spotify app                                | _(required)_                              |
| `SPOTIFY_REDIRECT_URI`   | OAuth callback URL                                                 | `http://localhost:8000/auth/callback`     |

For production, set `SPOTIFY_REDIRECT_URI` to `https://yourdomain.com/auth/callback`.

### Security

| Variable               | Description                                                  | Default        |
|------------------------|--------------------------------------------------------------|----------------|
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting Spotify refresh tokens at rest     | _(required)_   |
| `ADMIN_AUTH_MODE`      | Authentication mode for admin endpoints: `token` or `basic`  | `token`        |
| `ADMIN_TOKEN`          | Bearer token for admin API and frontend (when mode is `token`) | _(required)_ |

Generate a Fernet encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Generate a secure admin token (any method works):

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

If using `ADMIN_AUTH_MODE=basic`, set `ADMIN_USERNAME` and `ADMIN_PASSWORD` instead of `ADMIN_TOKEN`.

### Collector

| Variable                       | Description                                          | Default     |
|--------------------------------|------------------------------------------------------|-------------|
| `COLLECTOR_INTERVAL_SECONDS`   | Seconds between polling cycles                       | `600` (10 min) |
| `INITIAL_SYNC_ENABLED`         | Whether to backfill history on first authorization   | `true`      |
| `INITIAL_SYNC_MAX_DAYS`        | Maximum days to look back during initial sync        | `30`        |
| `INITIAL_SYNC_MAX_REQUESTS`    | Maximum API requests per initial sync                | `200`       |
| `INITIAL_SYNC_CONCURRENCY`     | Concurrent initial sync users                        | `2`         |
| `IMPORT_MAX_ZIP_SIZE_MB`       | Maximum ZIP file size for imports                    | `500`       |
| `IMPORT_MAX_RECORDS`           | Maximum records per ZIP import                       | `5000000`   |

### Frontend

| Variable              | Description                                          | Default           |
|-----------------------|------------------------------------------------------|-------------------|
| `API_BASE_URL`        | Internal URL for frontend to reach the API service   | `http://api:8000` |
| `FRONTEND_AUTH_MODE`  | Should mirror `ADMIN_AUTH_MODE`                      | `token`           |

### Logging

| Variable              | Description                                  | Default |
|-----------------------|----------------------------------------------|---------|
| `LOG_RETENTION_DAYS`  | Days to retain structured logs in the database | `90`  |

---

## 3. Deploy with Docker Compose

Build and start all services:

```bash
docker-compose up --build -d
```

Wait for all health checks to pass. You can monitor startup with:

```bash
docker-compose ps
docker-compose logs -f
```

Once the API container is healthy, run database migrations:

```bash
docker-compose exec api alembic upgrade head
```

Verify that services are running:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8001/healthz
```

Both should return a successful response.

---

## 4. First User Setup

1. Open `http://localhost:8000/auth/login` in your browser.
2. You will be redirected to Spotify. Authorize the application.
3. After successful authorization, you will be redirected back to the callback URL.
4. Open the admin frontend at `http://localhost:8001` -- the new user should appear on the dashboard.
5. The collector will automatically begin polling the user's recently played tracks on the next cycle (within `COLLECTOR_INTERVAL_SECONDS`).
6. If `INITIAL_SYNC_ENABLED=true`, the collector will also attempt to backfill up to `INITIAL_SYNC_MAX_DAYS` days of history.

---

## 5. Import Historical Data (Optional)

Spotify's API only provides limited recent playback history. For a complete listening history spanning months or years, you can import a data export.

### Request Your Data from Spotify

1. Go to your Spotify account page at https://www.spotify.com/account/privacy/
2. Scroll to **Download your data**.
3. Request **Extended streaming history** (not the basic "Account data" option -- extended history contains full play records with timestamps).
4. Wait for Spotify to send you an email with a download link. This can take several days to a few weeks.
5. Download the ZIP file when it arrives.

### Upload via Admin Frontend

1. Open `http://localhost:8001/imports`.
2. Use the upload form to submit the ZIP file.
3. The collector will process the import automatically on its next cycle.

### Upload via API

```bash
curl -X POST http://localhost:8000/admin/users/{user_id}/import \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@my_spotify_data.zip"
```

Replace `{user_id}` with the user's Spotify user ID (visible in the admin frontend).

### Import Notes

- The ZIP file can contain `endsong_*.json` (extended format) or `StreamingHistory*.json` (account data format).
- Plays are deduplicated by the unique constraint `(user_id, played_at, track_id)`, so re-importing the same data is safe.
- Sensitive fields (IP address, user agent) are stripped during import by default.
- Large imports are processed in batches (5k-20k records per transaction) to avoid memory issues.

---

## 6. Production: HTTPS Setup

For production deployments, you must serve the application over HTTPS. Update these environment variables before proceeding:

```
SPOTIFY_REDIRECT_URI=https://yourdomain.com/auth/callback
```

Also ensure your Spotify Developer app has the production redirect URI added.

### Option A: Caddy (simplest -- automatic TLS)

Caddy automatically obtains and renews TLS certificates from Let's Encrypt.

Create a `Caddyfile`:

```
yourdomain.com {
    handle /auth/* {
        reverse_proxy localhost:8000
    }

    handle /admin/* {
        reverse_proxy localhost:8000
    }

    handle /mcp/* {
        reverse_proxy localhost:8000
    }

    handle /healthz {
        reverse_proxy localhost:8000
    }

    handle /* {
        reverse_proxy localhost:8001
    }
}
```

Run Caddy:

```bash
caddy run --config Caddyfile
```

Caddy will automatically provision a TLS certificate for your domain.

### Option B: nginx + Let's Encrypt

Install nginx and certbot, then create a configuration:

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location /auth/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /mcp/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /healthz {
        proxy_pass http://127.0.0.1:8000;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Obtain the certificate:

```bash
sudo certbot certonly --nginx -d yourdomain.com
```

Certbot will automatically set up a cron job for renewal.

### Option C: Cloud Load Balancer

If running on a cloud provider, use the platform's managed load balancer:

- **AWS**: Application Load Balancer (ALB) with ACM certificate. Create target groups pointing to ports 8000 and 8001, with path-based routing rules.
- **GCP**: Google Cloud Load Balancer with managed SSL certificate.
- **Azure**: Application Gateway with TLS termination.

These options handle TLS termination and certificate management automatically.

---

## 7. Maintenance

### Log Management

Purge old log entries (older than `LOG_RETENTION_DAYS`):

```bash
curl -X POST "http://localhost:8000/admin/maintenance/purge-logs?days=90" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

You can also purge logs from the admin frontend at `http://localhost:8001/logs`.

### Database Backups

Create a database backup:

```bash
docker-compose exec postgres pg_dump -U postgres spotify_mcp > backup_$(date +%Y%m%d).sql
```

Restore from backup:

```bash
docker-compose exec -T postgres psql -U postgres spotify_mcp < backup_20260214.sql
```

### Updating the Application

Pull the latest code, rebuild containers, and run any new migrations:

```bash
git pull
docker-compose up --build -d
docker-compose exec api alembic upgrade head
```

### Monitoring

- Check service health: `curl http://localhost:8000/healthz` and `curl http://localhost:8001/healthz`
- Review application logs: `docker-compose logs -f api collector frontend`
- Review structured logs in the admin UI: `http://localhost:8001/logs`
- Check sync status and job history in the admin UI: `http://localhost:8001/jobs`

### Troubleshooting

| Symptom                        | Check                                                                 |
|-------------------------------|-----------------------------------------------------------------------|
| API returns 500               | `docker-compose logs api` -- look for stack traces                    |
| Collector not polling          | `docker-compose logs collector` -- check for auth or DB errors       |
| OAuth callback fails           | Verify `SPOTIFY_REDIRECT_URI` matches the Spotify app's redirect URI |
| User not appearing after auth  | Ensure the Spotify account is added under "Users and Access" in the Spotify Developer dashboard |
| ZIP import stuck               | Check `docker-compose logs collector` for import errors; verify file size is under `IMPORT_MAX_ZIP_SIZE_MB` |

---

## 8. Resource Recommendations

Minimum resource allocations for a stable deployment:

| Service    | RAM        | CPU   | Storage Notes                                    |
|------------|------------|-------|--------------------------------------------------|
| API        | 512 MB     | 0.5   | Minimal disk usage                               |
| Collector  | 256 MB     | 0.25  | Temporary disk during ZIP processing             |
| Frontend   | 256 MB     | 0.25  | Minimal disk usage                               |
| PostgreSQL | 1 GB min   | 0.5   | SSD storage recommended for large datasets       |

### Storage Estimates

- Each play record uses approximately 200-300 bytes in the database.
- A heavy listener with 10 years of history (~100,000 plays) will use roughly 30-50 MB of database storage including indexes.
- ZIP upload files are stored temporarily in a shared Docker volume (`upload_data`) and can be cleaned up after successful import.

### Scaling Notes

- The system is designed for single-digit to low double-digit users. Each user adds one polling cycle per interval.
- For more users, increase `COLLECTOR_INTERVAL_SECONDS` to reduce API rate limit pressure, or run multiple collector instances (requires coordination -- not natively supported).
- PostgreSQL connection pooling is handled by SQLAlchemy's async pool. The default pool size is sufficient for typical deployments.

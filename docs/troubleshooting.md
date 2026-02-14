# Troubleshooting Guide

This guide covers common issues with the Spotify MCP History Collector system and how to resolve them. The system consists of four Docker services: API (port 8000), collector (worker), frontend (port 8001), and PostgreSQL.

---

## OAuth and Authentication Issues

### OAuth callback fails

**Symptom**: Redirect after Spotify login shows error or 400.

**Causes**:

- **Redirect URI mismatch**: `SPOTIFY_REDIRECT_URI` in `.env` must exactly match what is configured in the Spotify Developer Dashboard, including `http` vs `https` and trailing slashes. Even a single character difference will cause the callback to fail.
- **Invalid client ID/secret**: Double-check `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in your `.env` file against the values in the Spotify Developer Dashboard.
- **App not in development mode with user added**: In the Spotify Developer Dashboard, go to Settings and then User Management. Add the Spotify account you are trying to authorize. Apps in development mode only allow explicitly added users.

### Admin API returns 401/403

- Check that `ADMIN_AUTH_MODE` is set in your `.env` file (e.g., `token` or `basic`).
- If using token auth, verify `ADMIN_TOKEN` in `.env` matches the value sent in the `Authorization` header.
- If using basic auth, verify `ADMIN_USERNAME` and `ADMIN_PASSWORD` are set correctly.

---

## Collector Issues

### Collector not polling

- Check the collector container is running:
  ```bash
  docker-compose ps
  ```
- Check logs for errors:
  ```bash
  docker-compose logs collector
  ```
- Verify the user has valid tokens by checking the Users page in the admin frontend.
- The collector runs on an interval defined by `COLLECTOR_INTERVAL_SECONDS` (default 600 seconds = 10 minutes). It may simply be waiting for the next cycle.

### Initial sync not running

- Verify `INITIAL_SYNC_ENABLED=true` in the collector environment.
- Check the `sync_checkpoints` table in the database. If `initial_sync_completed_at` is already set for a user, the initial sync will not run again for that user.
- The collector prioritizes work in this order: ZIP imports, then initial sync, then polling. Pending ZIP imports will delay the initial sync.

### Collector errors with 429 (rate limited)

- Spotify API enforces rate limits. The collector has built-in exponential backoff to handle 429 responses automatically.
- If rate limiting is excessive, increase `COLLECTOR_INTERVAL_SECONDS` to reduce request frequency.
- Check whether other applications are using the same Spotify API credentials, which would share the same rate limit budget.

---

## ZIP Import Issues

### Import fails: "Format not detected"

- Supported formats are Spotify "Extended Streaming History" (`endsong_*.json`) and "Account Data" (`StreamingHistory*.json`).
- The ZIP must contain JSON files at the root level or one directory level deep.
- Verify the file is a valid ZIP archive and not corrupted.

### Import fails: file too large

- The default upload limit is controlled by `IMPORT_MAX_ZIP_SIZE_MB`, which defaults to 500 MB.
- Increase this value in your `.env` file if you need to import larger files.

### Import shows 0 records processed

- Check that the JSON format matches the expected schema for either Extended Streaming History or Account Data exports.
- Look at the collector logs for parsing errors:
  ```bash
  docker-compose logs collector
  ```
- The files must contain valid JSON arrays of play records.

---

## Frontend Issues

### Frontend shows "API Error" on every page

- Check the API is running and healthy:
  ```bash
  curl http://localhost:8000/healthz
  ```
- Verify `API_BASE_URL` in the frontend configuration. The default for Docker is `http://api:8000`. If running outside Docker, use `http://localhost:8000`.
- Check that the frontend and API containers are on the same Docker network.
- Verify that `FRONTEND_AUTH_MODE` and `ADMIN_TOKEN` are consistent between the frontend and API configurations.

### Dashboard shows no data

- At least one user must have completed the OAuth authorization flow.
- The collector needs time to start polling. The first run will occur after `COLLECTOR_INTERVAL_SECONDS` elapses.
- Check the Jobs page in the admin frontend for completed runs. If no jobs have run, the collector may not have started yet.

---

## MCP Tool Issues

### Empty results from history tools

- No plays have been collected yet. Wait for the collector to complete a polling cycle, or upload a ZIP export.
- Check that the `user_id` parameter matches an actual user in the system.
- Check the `days` parameter. If set too low, there may be no play data in that time window.

### "Unknown tool" error

- Verify the exact tool name by calling `GET /mcp/tools` to list all available tools.
- Tool names are prefixed with their category. For example, use `history.taste_summary`, not just `taste_summary`.

---

## Docker Issues

### Health checks failing

- **API**: Check the health endpoint and container logs:
  ```bash
  curl http://localhost:8000/healthz
  docker-compose logs api
  ```
- **Frontend**: Check the health endpoint and container logs:
  ```bash
  curl http://localhost:8001/healthz
  docker-compose logs frontend
  ```
- **PostgreSQL**: Verify the database is accepting connections:
  ```bash
  docker-compose exec postgres pg_isready -U postgres
  ```

### Database connection errors

- Check that `DATABASE_URL` is correct in your `.env` file.
- Ensure the postgres container is healthy:
  ```bash
  docker-compose ps
  ```
- Check if migrations have been run:
  ```bash
  docker-compose exec api alembic current
  ```
- Run pending migrations:
  ```bash
  docker-compose exec api alembic upgrade head
  ```

### Container won't start

- Check the container logs for error messages:
  ```bash
  docker-compose logs <service-name>
  ```
- Ensure the `.env` file exists and has all required variables.
- Try rebuilding the containers:
  ```bash
  docker-compose up --build -d
  ```

### Out of disk space

- Purge old logs using the admin frontend: navigate to the Logs page and use the Purge button.
- Clean up unused Docker resources:
  ```bash
  docker system prune
  ```
- Check the postgres volume size for excessive data growth.

---

## Database Issues

### Migration errors

- Check the current Alembic state:
  ```bash
  docker-compose exec api alembic current
  ```
- Try running the upgrade:
  ```bash
  docker-compose exec api alembic upgrade head
  ```
- If stuck, check for lock files or concurrent connections to the database that may be blocking the migration.

### Duplicate play errors

- Plays are deduplicated by a unique constraint on `(user_id, played_at, track_id)`.
- Duplicate inserts are silently ignored. This is expected behavior and not an error condition.

---

## Viewing Logs

### API and collector logs

- View live Docker logs:
  ```bash
  docker-compose logs -f api
  docker-compose logs -f collector
  ```
- Use the admin UI by navigating to `http://localhost:8001/logs`.
- Filter logs by level, service, or date range using the controls on the Logs page.

### Structured JSON logs

- The API outputs structured JSON to stdout.
- Each log entry includes: timestamp, level, service, logger, and message.
- The `X-Request-ID` header can be used to correlate all log entries belonging to a single request.

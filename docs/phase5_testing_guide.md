# Phase 5: ZIP Import — Manual Testing Guide

## Prerequisites

```bash
# Build and start all services
docker-compose up --build -d

# Run database migrations
docker-compose exec api alembic upgrade head

# Verify all services are healthy
docker-compose ps
```

All four services should show as running: `postgres` (healthy), `api` (healthy), `frontend` (healthy), `collector` (running).

---

## 1. Create a Test User

The admin endpoints require a valid user ID. Create one directly in Postgres:

```bash
docker-compose exec postgres psql -U postgres -d spotify_mcp -c \
  "INSERT INTO users (spotify_user_id, display_name, created_at, updated_at)
   VALUES ('manual_test_user', 'Manual Tester', NOW(), NOW())
   RETURNING id;"
```

Note the returned `id` — use it as `USER_ID` in all commands below.

---

## 2. Generate Test ZIP Files

### Extended Streaming History format (`endsong_*.json`)

This is the format Spotify provides in "Download your data" (extended) exports:

```bash
python -c "
import io, zipfile, json

buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as zf:
    records = [
        {
            'ts': '2024-01-15T10:30:00Z',
            'master_metadata_track_name': 'Bohemian Rhapsody',
            'master_metadata_album_artist_name': 'Queen',
            'master_metadata_album_album_name': 'A Night at the Opera',
            'ms_played': 354000,
            'spotify_track_uri': 'spotify:track:4u7EnebtmKWzUH433cf5Qv'
        },
        {
            'ts': '2024-01-15T11:00:00Z',
            'master_metadata_track_name': 'Stairway to Heaven',
            'master_metadata_album_artist_name': 'Led Zeppelin',
            'master_metadata_album_album_name': 'Led Zeppelin IV',
            'ms_played': 482000
        },
        {
            'ts': '2024-01-16T09:15:00Z',
            'master_metadata_track_name': 'Hotel California',
            'master_metadata_album_artist_name': 'Eagles',
            'master_metadata_album_album_name': 'Hotel California',
            'ms_played': 391000,
            'spotify_track_uri': 'spotify:track:40riOy7x9W7GXjyGp4pjAv'
        }
    ]
    zf.writestr('endsong_0.json', json.dumps(records))

with open('test_extended.zip', 'wb') as f:
    f.write(buf.getvalue())
print('Created test_extended.zip')
"
```

### Account Data format (`StreamingHistory*.json`)

This is the shorter format from Spotify's "Account data" export:

```bash
python -c "
import io, zipfile, json

buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as zf:
    records = [
        {
            'endTime': '2024-02-10 14:30',
            'artistName': 'Radiohead',
            'trackName': 'Karma Police',
            'msPlayed': 263000
        },
        {
            'endTime': '2024-02-10 15:00',
            'artistName': 'Pink Floyd',
            'trackName': 'Comfortably Numb',
            'msPlayed': 382000
        }
    ]
    zf.writestr('StreamingHistory0.json', json.dumps(records))

with open('test_account_data.zip', 'wb') as f:
    f.write(buf.getvalue())
print('Created test_account_data.zip')
"
```

---

## 3. Test Admin Upload Endpoint

### 3a. Upload a valid ZIP (expected: 200, status=pending)

```bash
curl -s -X POST "http://localhost:8000/admin/users/USER_ID/import" \
  -F "file=@test_extended.zip" | python -m json.tool
```

Expected response:
```json
{
    "id": 1,
    "user_id": USER_ID,
    "status": "pending",
    "file_path": "/app/uploads/USER_ID_<uuid>_test_extended.zip",
    "file_size_bytes": 576,
    "created_at": "2026-..."
}
```

Note the returned `id` — use it as `JOB_ID` below.

### 3b. Upload to non-existent user (expected: 404)

```bash
curl -s -X POST "http://localhost:8000/admin/users/99999/import" \
  -F "file=@test_extended.zip" | python -m json.tool
```

Expected: `{"detail": "User 99999 not found"}`

### 3c. Upload a non-ZIP file (expected: 400)

```bash
echo "not a zip" > fake.csv
curl -s -X POST "http://localhost:8000/admin/users/USER_ID/import" \
  -F "file=@fake.csv" | python -m json.tool
```

Expected: `{"detail": "File must be a .zip archive"}`

---

## 4. Test Import Job Status Endpoint

### 4a. Get status of existing job (expected: 200)

```bash
curl -s "http://localhost:8000/admin/import-jobs/JOB_ID" | python -m json.tool
```

Expected: full status object with `"status": "pending"`, `"records_ingested": 0`.

### 4b. Get non-existent job (expected: 404)

```bash
curl -s "http://localhost:8000/admin/import-jobs/99999" | python -m json.tool
```

Expected: `{"detail": "Import job 99999 not found"}`

---

## 5. Verify Collector Processes the Import

The collector checks for pending imports every `COLLECTOR_INTERVAL_SECONDS` (default 600s). To trigger processing immediately, restart the collector:

```bash
docker-compose restart collector
```

Then watch the logs:

```bash
docker-compose logs -f collector
```

Expected log sequence for a successful import:
```
Found 1 pending import job(s)
Processing import job 1 for user USER_ID: /app/uploads/...
Detected format: extended
Parsing ZIP entry: endsong_0.json
Import job 1: batch done (3 inserted, 0 skipped, 3 total so far)
Import job 1 completed: 3 inserted, 0 skipped, range=2024-01-15 ... to 2024-01-16 ...
```

After processing, check the status endpoint again:

```bash
curl -s "http://localhost:8000/admin/import-jobs/JOB_ID" | python -m json.tool
```

Expected: `"status": "success"`, `"format_detected": "extended"`, `"records_ingested": 3`, with `earliest_played_at`/`latest_played_at` populated.

---

## 6. Verify Database State

### Check import_jobs

```bash
docker-compose exec postgres psql -U postgres -d spotify_mcp -c \
  "SELECT id, status, format_detected, records_ingested, error_message FROM import_jobs;"
```

### Check tracks were created

```bash
docker-compose exec postgres psql -U postgres -d spotify_mcp -c \
  "SELECT id, name, spotify_track_id, local_track_id, source FROM tracks;"
```

Tracks with a Spotify URI should have `spotify_track_id` populated. Tracks without a URI (e.g., Stairway to Heaven above) should have a `local_track_id` of the form `local:<sha1>`.

### Check artists were created

```bash
docker-compose exec postgres psql -U postgres -d spotify_mcp -c \
  "SELECT id, name, spotify_artist_id, local_artist_id, source FROM artists;"
```

All artists from import should have `source = 'import_zip'` and a `local_artist_id`.

### Check plays were recorded

```bash
docker-compose exec postgres psql -U postgres -d spotify_mcp -c \
  "SELECT p.id, p.played_at, p.ms_played, p.source, t.name AS track_name
   FROM plays p
   JOIN tracks t ON p.track_id = t.id
   ORDER BY p.played_at;"
```

### Check job_runs was recorded

```bash
docker-compose exec postgres psql -U postgres -d spotify_mcp -c \
  "SELECT id, user_id, job_type, status, records_fetched, records_inserted, records_skipped
   FROM job_runs;"
```

Should show a row with `job_type = 'import_zip'`, `status = 'success'`.

---

## 7. Test Deduplication

Upload the same ZIP file again:

```bash
curl -s -X POST "http://localhost:8000/admin/users/USER_ID/import" \
  -F "file=@test_extended.zip" | python -m json.tool
```

Restart the collector and wait for processing:

```bash
docker-compose restart collector
docker-compose logs -f collector
```

Expected: the logs should show records as **skipped** (not inserted) since they already exist. Verify:

```bash
docker-compose exec postgres psql -U postgres -d spotify_mcp -c \
  "SELECT COUNT(*) FROM plays;"
```

The count should remain the same as before (no duplicates).

---

## 8. Test Account Data Format

Upload the account data format ZIP:

```bash
curl -s -X POST "http://localhost:8000/admin/users/USER_ID/import" \
  -F "file=@test_account_data.zip" | python -m json.tool
```

After collector processes it, the import job should show `"format_detected": "account_data"`.

---

## 9. Test Error Handling

### Bad ZIP (no recognizable files)

```bash
python -c "
import io, zipfile
buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as zf:
    zf.writestr('random_file.txt', 'nothing useful')
with open('test_bad_format.zip', 'wb') as f:
    f.write(buf.getvalue())
print('Created test_bad_format.zip')
"

curl -s -X POST "http://localhost:8000/admin/users/USER_ID/import" \
  -F "file=@test_bad_format.zip" | python -m json.tool
```

After collector processes it, the import job should show `"status": "error"` with an error message about no recognizable Spotify export files.

---

## 10. Cleanup

```bash
# Stop all services
docker-compose down

# Remove test files
rm -f test_extended.zip test_account_data.zip test_bad_format.zip fake.csv
```

---

## Automated Test Suite

The full automated test suite (118 tests) can be run locally without Docker:

```bash
# API tests (90 tests — auth, DB ops, Spotify client, ZIP import, admin)
pytest services/api/tests/ -v

# Collector tests (28 tests — sync, polling, job tracking, ZIP import service)
cd services/collector && pytest tests/ -v
```

Note: API and collector tests must be run separately (not from the repo root) due to SQLite BigInteger compilation conflicts between their conftest files.

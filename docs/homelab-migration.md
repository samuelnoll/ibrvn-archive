# IBRVN Archive Homelab Migration

This repository can move to the mini PC in two safer phases.

## Phase 1: Move the current app as-is

Goal:

- keep the current SQLite-based architecture
- stop depending on `/opt/sermon-platform`, `venv`, `nohup`, and PID files
- run the FastAPI app in Docker on the shared `homelab` network

Deliverables already in this repo:

- `Dockerfile`
- `compose.yaml`
- `.env.example`
- `scripts/up-api.sh`

Recommended host directories:

```text
/srv/homelab/volumes/ibrvn-archive/
  data/
    bronze/
    silver/
    gold/
  logs/
```

Bring-up flow on Ubuntu:

```bash
cd ~/src/ibrvn-archive
cp .env.example .env
mkdir -p /srv/homelab/volumes/ibrvn-archive/data
mkdir -p /srv/homelab/volumes/ibrvn-archive/logs
chmod +x scripts/up-api.sh
./scripts/up-api.sh
```

The app will expose the current archive on port `8000` and will keep using
the SQLite file mounted at `/srv/homelab/volumes/ibrvn-archive/data/gold/archive.db`.

## Phase 2: Switch gold storage to PostgreSQL

Do this only after the API is already stable on the mini PC.

Recommended sequence:

1. Keep bronze and silver files on disk.
2. Create a new `sermons` table in PostgreSQL with the same business fields.
3. Replace direct `sqlite3` access with a database abstraction compatible with PostgreSQL.
4. Migrate gold loaders (`pipelines/gold/*`) to write to PostgreSQL.
5. Migrate API queries from SQLite syntax to PostgreSQL-compatible SQL.
6. Add a one-time backfill from the existing `archive.db`.
7. Validate counts, date range, missing links, and sample search results before switching the API over.

## Data to copy from the Raspberry or old host

This repo does not include your runtime data. Before starting the container on
the mini PC, copy at least:

- the `data/` directory, especially `data/gold/archive.db`
- the latest WordPress XML under `data/bronze/`
- any logs you want to preserve
- the secret used for `YOUTUBE_API_KEY`

## What changes already happened for this phase

- gold database path is now configurable through `ARCHIVE_GOLD_DB_PATH`
- export path is configurable through `ARCHIVE_EXPORT_DIR`
- `make api` now respects `ARCHIVE_API_HOST` and `ARCHIVE_API_PORT`
- missing runtime dependencies needed by a clean container were added to `requirements.txt`

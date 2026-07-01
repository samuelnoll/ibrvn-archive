# IBRVN Archive Homelab Migration

This repository moved through two phases:

1. run the existing app in Docker with the legacy SQLite gold file
2. switch the gold layer to PostgreSQL while keeping bronze and silver files on disk

## Current state

The repository is now ready for PostgreSQL-backed gold storage.

The stack also supports a dedicated pipeline runtime separate from the API
runtime. This keeps ingestion credentials and heavier dependencies out of the
web container.

Implemented in code:

- API reads from a configurable database backend
- gold loaders write through PostgreSQL-compatible upserts
- schema and indexes are created automatically on startup
- a one-time backfill script copies rows from the legacy `archive.db`
- the old SQLite file can stay mounted for rollback safety

## Required environment

Review `.env` on the mini PC and make sure these values are set:

```dotenv
ARCHIVE_DATABASE_BACKEND=postgres
ARCHIVE_DATABASE_HOST=postgres
ARCHIVE_DATABASE_PORT=5432
ARCHIVE_DATABASE_NAME=app
ARCHIVE_DATABASE_USER=app
ARCHIVE_DATABASE_PASSWORD=<same password used in homelab-infra>

ARCHIVE_GOLD_DB_PATH=/app/data/gold/archive.db
ARCHIVE_LEGACY_SQLITE_PATH=/app/data/gold/archive.db
```

The `postgres` hostname works because both stacks join the shared Docker network
`homelab`.

## Phase 2 rollout on the mini PC

Inside `~/src/ibrvn-archive`:

```bash
git pull
docker compose down
docker compose up -d --build
docker exec ibrvn-archive-pipelines python scripts/migrate_sqlite_to_postgres.py
docker exec ibrvn-archive-pipelines python scripts/sermon_data_quality.py
```

The API container now starts with PostgreSQL as the active gold database. The
pipeline container owns operational scripts and ingestion jobs. The legacy
SQLite file is only used by the migration script.

## Optional reprocessing after the switch

If you want to rebuild gold from silver after the migration:

```bash
docker exec ibrvn-archive-pipelines python -m jobs.wordpress_job
docker exec ibrvn-archive-pipelines python -m jobs.youtube_job --mode historic
docker exec ibrvn-archive-pipelines python -m jobs.youtube_job --mode weekly
```

Those jobs now write to PostgreSQL instead of SQLite.

## Validation checklist

After the rollout, verify:

1. `docker logs ibrvn-archive-api --tail 100` has no startup errors.
2. `http://<mini-pc-ip>:8000` loads normally.
3. search, preachers, series and years pages return expected data.
4. `docker exec ibrvn-archive-pipelines python scripts/sermon_data_quality.py` reports the expected row counts and date range.

## Rollback

If you need to go back temporarily:

1. set `ARCHIVE_DATABASE_BACKEND=sqlite` in `.env`
2. rebuild the API container
3. keep using `/app/data/gold/archive.db` as before

Because the old file stays mounted, rollback is fast and does not require a new
copy from the Raspberry or previous host.

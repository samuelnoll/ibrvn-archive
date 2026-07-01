import os
import sqlite3
import sys

from sqlalchemy import text

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.db import (
    ensure_schema,
    fetch_one,
    utc_now_iso,
    get_engine,
    initialize_database,
    is_postgres_backend,
)
from shared.settings import LEGACY_SQLITE_PATH

UPSERT_SQL = """
INSERT INTO gold_sermons (
    canonical_sermon_id,
    preaching_date,
    preacher_name,
    title,
    text_reference,
    serie,
    youtube_link,
    wordpress_link,
    media_link,
    download_link,
    last_aggregated_at
)
VALUES (
    :canonical_sermon_id,
    :preaching_date,
    :preacher_name,
    :title,
    :text_reference,
    :serie,
    :youtube_link,
    :wordpress_link,
    :media_link,
    :download_link,
    :last_aggregated_at
)
ON CONFLICT(canonical_sermon_id) DO UPDATE SET
    preaching_date = EXCLUDED.preaching_date,
    preacher_name = COALESCE(
        NULLIF(EXCLUDED.preacher_name, ''),
        gold_sermons.preacher_name
    ),
    title = COALESCE(
        NULLIF(EXCLUDED.title, ''),
        gold_sermons.title
    ),
    text_reference = COALESCE(
        NULLIF(EXCLUDED.text_reference, ''),
        gold_sermons.text_reference
    ),
    serie = COALESCE(
        NULLIF(EXCLUDED.serie, ''),
        gold_sermons.serie
    ),
    youtube_link = COALESCE(
        NULLIF(EXCLUDED.youtube_link, ''),
        gold_sermons.youtube_link
    ),
    wordpress_link = COALESCE(
        NULLIF(EXCLUDED.wordpress_link, ''),
        gold_sermons.wordpress_link
    ),
    media_link = COALESCE(
        NULLIF(EXCLUDED.media_link, ''),
        gold_sermons.media_link
    ),
    download_link = COALESCE(
        NULLIF(EXCLUDED.download_link, ''),
        gold_sermons.download_link
    ),
    last_aggregated_at = EXCLUDED.last_aggregated_at
"""


def read_sqlite_records():

    sqlite_path = LEGACY_SQLITE_PATH.resolve()

    if not sqlite_path.exists():
        raise FileNotFoundError(
            f"Legacy SQLite database not found: {sqlite_path}"
        )

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute("""
            SELECT
                preaching_date,
                preacher_name,
                title,
                text_reference,
                serie,
                youtube_link,
                wordpress_link,
                media_link
            FROM sermons
            ORDER BY preaching_date
        """).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def run():

    if not is_postgres_backend():
        raise RuntimeError(
            "Set ARCHIVE_DATABASE_BACKEND=postgres before running this migration."
        )

    initialize_database()

    records = read_sqlite_records()
    now = utc_now_iso()

    for record in records:
        record["canonical_sermon_id"] = record["preaching_date"]
        record["download_link"] = ""
        record["last_aggregated_at"] = now

    with get_engine().begin() as conn:
        ensure_schema(conn)

        if records:
            conn.execute(text(UPSERT_SQL), records)

    row = fetch_one("""
        SELECT COUNT(*) AS total
        FROM gold_sermons
    """)

    print(f"Migrated {len(records)} sermons from SQLite to PostgreSQL")
    print(f"Target row count: {row['total']}")


if __name__ == "__main__":
    run()

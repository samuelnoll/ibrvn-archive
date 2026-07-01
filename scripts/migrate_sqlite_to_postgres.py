import os
import sqlite3
import sys

from sqlalchemy import text

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from archive_database import (
    ensure_schema,
    fetch_one,
    get_engine,
    initialize_database,
    is_postgres_backend,
)
from archive_settings import LEGACY_SQLITE_PATH

UPSERT_SQL = """
INSERT INTO sermons (
    preaching_date,
    preacher_name,
    title,
    text_reference,
    serie,
    youtube_link,
    wordpress_link,
    media_link
)
VALUES (
    :preaching_date,
    :preacher_name,
    :title,
    :text_reference,
    :serie,
    :youtube_link,
    :wordpress_link,
    :media_link
)
ON CONFLICT(preaching_date) DO UPDATE SET
    preacher_name = COALESCE(
        NULLIF(EXCLUDED.preacher_name, ''),
        sermons.preacher_name
    ),
    title = COALESCE(
        NULLIF(EXCLUDED.title, ''),
        sermons.title
    ),
    text_reference = COALESCE(
        NULLIF(EXCLUDED.text_reference, ''),
        sermons.text_reference
    ),
    serie = COALESCE(
        NULLIF(EXCLUDED.serie, ''),
        sermons.serie
    ),
    youtube_link = COALESCE(
        NULLIF(EXCLUDED.youtube_link, ''),
        sermons.youtube_link
    ),
    wordpress_link = COALESCE(
        NULLIF(EXCLUDED.wordpress_link, ''),
        sermons.wordpress_link
    ),
    media_link = COALESCE(
        NULLIF(EXCLUDED.media_link, ''),
        sermons.media_link
    )
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

    with get_engine().begin() as conn:
        ensure_schema(conn)

        if records:
            conn.execute(text(UPSERT_SQL), records)

    row = fetch_one("""
        SELECT COUNT(*) AS total
        FROM sermons
    """)

    print(f"Migrated {len(records)} sermons from SQLite to PostgreSQL")
    print(f"Target row count: {row['total']}")


if __name__ == "__main__":
    run()

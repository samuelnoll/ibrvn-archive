from __future__ import annotations

from sqlalchemy import inspect, text


CREATE_SILVER_STUDY_PROCESSING_RUNS_SQL = """
CREATE TABLE IF NOT EXISTS silver_study_processing_runs (
    run_id TEXT PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    input_ref TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
)
"""

CREATE_SILVER_STUDY_WORDPRESS_SQL = """
CREATE TABLE IF NOT EXISTS silver_study_wordpress (
    study_key TEXT PRIMARY KEY,
    source_item_id TEXT NOT NULL UNIQUE,
    wordpress_post_id TEXT NOT NULL,
    study_type TEXT NOT NULL,
    title TEXT NOT NULL,
    study_date TEXT,
    source_url TEXT,
    collection_slug TEXT,
    payload_version TEXT NOT NULL,
    processed_at TEXT NOT NULL
)
"""

CREATE_SILVER_STUDY_WORDPRESS_RESOURCES_SQL = """
CREATE TABLE IF NOT EXISTS silver_study_wordpress_resources (
    resource_key TEXT PRIMARY KEY,
    study_key TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    label TEXT,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    mime_type TEXT,
    position INTEGER NOT NULL,
    processed_at TEXT NOT NULL,
    UNIQUE (study_key, canonical_url)
)
"""

CREATE_SILVER_STUDY_YOUTUBE_SQL = """
CREATE TABLE IF NOT EXISTS silver_study_youtube (
    study_key TEXT PRIMARY KEY,
    youtube_playlist_id TEXT NOT NULL UNIQUE,
    study_type TEXT NOT NULL,
    title TEXT NOT NULL,
    study_date TEXT,
    source_url TEXT NOT NULL,
    payload_version TEXT NOT NULL,
    processed_at TEXT NOT NULL
)
"""

CREATE_SILVER_STUDY_YOUTUBE_RESOURCES_SQL = """
CREATE TABLE IF NOT EXISTS silver_study_youtube_resources (
    resource_key TEXT PRIMARY KEY,
    study_key TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    label TEXT,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    mime_type TEXT,
    position INTEGER NOT NULL,
    processed_at TEXT NOT NULL,
    UNIQUE (study_key, canonical_url)
)
"""

CREATE_GOLD_STUDIES_SQL = """
CREATE TABLE IF NOT EXISTS gold_studies (
    study_id TEXT PRIMARY KEY,
    study_type TEXT NOT NULL,
    title TEXT NOT NULL,
    study_date TEXT,
    study_year TEXT,
    collection_title TEXT,
    source_system TEXT NOT NULL,
    source_url TEXT,
    resource_count INTEGER NOT NULL DEFAULT 0,
    last_aggregated_at TEXT NOT NULL
)
"""

CREATE_GOLD_STUDY_RESOURCES_SQL = """
CREATE TABLE IF NOT EXISTS gold_study_resources (
    resource_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    label TEXT,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    mime_type TEXT,
    source_system TEXT NOT NULL,
    position INTEGER NOT NULL,
    UNIQUE (study_id, canonical_url)
)
"""


def ensure_study_schema(conn) -> None:
    conn.execute(text(CREATE_SILVER_STUDY_PROCESSING_RUNS_SQL))
    conn.execute(text(CREATE_SILVER_STUDY_WORDPRESS_SQL))
    conn.execute(text(CREATE_SILVER_STUDY_WORDPRESS_RESOURCES_SQL))
    migrate_youtube_playlist_schema(conn)
    conn.execute(text(CREATE_SILVER_STUDY_YOUTUBE_SQL))
    conn.execute(text(CREATE_SILVER_STUDY_YOUTUBE_RESOURCES_SQL))
    conn.execute(text(CREATE_GOLD_STUDIES_SQL))
    conn.execute(text(CREATE_GOLD_STUDY_RESOURCES_SQL))


def migrate_youtube_playlist_schema(conn) -> None:
    database = inspect(conn)

    if not database.has_table("silver_study_youtube"):
        return

    columns = {
        column["name"]
        for column in database.get_columns("silver_study_youtube")
    }

    if "youtube_playlist_id" in columns:
        return

    # The first study schema modeled videos as studies. Rebuild only the
    # source-specific YouTube silver so it can be repopulated from bronze v2.
    conn.execute(text("DROP TABLE IF EXISTS silver_study_youtube_resources"))
    conn.execute(text("DROP TABLE IF EXISTS silver_study_youtube"))


def create_study_indexes(conn) -> None:
    statements = [
        """
        CREATE INDEX IF NOT EXISTS idx_silver_study_wordpress_type_date
        ON silver_study_wordpress(study_type, study_date)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_silver_study_wordpress_resource_study
        ON silver_study_wordpress_resources(study_key, resource_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_silver_study_youtube_type_date
        ON silver_study_youtube(study_type, study_date)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_silver_study_youtube_resource_study
        ON silver_study_youtube_resources(study_key, resource_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_gold_studies_type_year_date
        ON gold_studies(study_type, study_year, study_date)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_gold_study_resources_study_type
        ON gold_study_resources(study_id, resource_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_silver_study_runs_status
        ON silver_study_processing_runs(status, started_at)
        """,
    ]

    for statement in statements:
        conn.execute(text(statement))


def begin_study_processing_run(pipeline_name: str, input_ref: str = "") -> str:
    from shared.db import get_engine, new_run_id, utc_now_iso

    run_id = new_run_id()

    with get_engine().begin() as conn:
        ensure_study_schema(conn)
        conn.execute(text("""
            INSERT INTO silver_study_processing_runs (
                run_id,
                pipeline_name,
                input_ref,
                status,
                started_at,
                finished_at
            )
            VALUES (
                :run_id,
                :pipeline_name,
                :input_ref,
                'running',
                :started_at,
                NULL
            )
        """), {
            "run_id": run_id,
            "pipeline_name": pipeline_name,
            "input_ref": input_ref,
            "started_at": utc_now_iso(),
        })

    return run_id


def finish_study_processing_run(run_id: str, status: str) -> None:
    from shared.db import get_engine, utc_now_iso

    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE silver_study_processing_runs
            SET status = :status,
                finished_at = :finished_at
            WHERE run_id = :run_id
        """), {
            "run_id": run_id,
            "status": status,
            "finished_at": utc_now_iso(),
        })

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

from .settings import (
    DATABASE_BACKEND,
    DATABASE_HOST,
    DATABASE_NAME,
    DATABASE_PASSWORD,
    DATABASE_PORT,
    DATABASE_URL,
    DATABASE_USER,
    GOLD_DB_PATH,
)


CREATE_SILVER_SOURCE_ITEMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS silver_source_items (
    source_system TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    ingestion_run_id TEXT NOT NULL,
    payload_version TEXT NOT NULL,
    raw_path TEXT,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (source_system, source_item_id, payload_version)
)
"""

CREATE_SILVER_SERMON_METADATA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS silver_sermon_metadata (
    canonical_sermon_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    preaching_date TEXT NOT NULL,
    title TEXT,
    preacher_name TEXT,
    text_reference TEXT,
    serie TEXT,
    confidence REAL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (source_system, source_item_id)
)
"""

CREATE_SILVER_MEDIA_ASSETS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS silver_media_assets (
    canonical_sermon_id TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    source_url TEXT,
    local_path TEXT,
    duration_seconds REAL,
    mime_type TEXT,
    PRIMARY KEY (canonical_sermon_id, asset_type)
)
"""

CREATE_SILVER_TRANSCRIPTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS silver_transcripts (
    canonical_sermon_id TEXT NOT NULL,
    transcript_version INTEGER NOT NULL,
    language TEXT,
    transcript_text TEXT,
    model_name TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (canonical_sermon_id, transcript_version)
)
"""

CREATE_SILVER_CRITIQUE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS silver_critique (
    canonical_sermon_id TEXT NOT NULL,
    critique_version INTEGER NOT NULL,
    transcript_version INTEGER,
    critique_text TEXT,
    model_name TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (canonical_sermon_id, critique_version)
)
"""

CREATE_SILVER_PROCESSING_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS silver_processing_runs (
    run_id TEXT PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    input_ref TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
)
"""

CREATE_GOLD_SERMONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS gold_sermons (
    canonical_sermon_id TEXT PRIMARY KEY,
    preaching_date TEXT NOT NULL UNIQUE,
    title TEXT,
    preacher_name TEXT,
    text_reference TEXT,
    serie TEXT,
    youtube_link TEXT,
    wordpress_link TEXT,
    media_link TEXT,
    download_link TEXT,
    duration_seconds REAL,
    transcript_available INTEGER DEFAULT 0,
    last_aggregated_at TEXT NOT NULL
)
"""


def utc_now_iso() -> str:

    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:

    return uuid4().hex


def is_postgres_backend():

    return DATABASE_BACKEND == "postgres"


def get_backend_name():

    return DATABASE_BACKEND


def get_database_url():

    if DATABASE_URL:
        return DATABASE_URL

    if is_postgres_backend():
        return URL.create(
            "postgresql+psycopg",
            username=DATABASE_USER,
            password=DATABASE_PASSWORD,
            host=DATABASE_HOST,
            port=DATABASE_PORT,
            database=DATABASE_NAME,
        )

    return f"sqlite:///{GOLD_DB_PATH.resolve().as_posix()}"


@lru_cache(maxsize=1)
def get_engine():

    kwargs = {
        "future": True,
        "pool_pre_ping": True,
    }

    if not is_postgres_backend():
        kwargs["connect_args"] = {
            "check_same_thread": False,
        }

    return create_engine(get_database_url(), **kwargs)


def ensure_schema(conn):

    conn.execute(text(CREATE_SILVER_SOURCE_ITEMS_TABLE_SQL))
    conn.execute(text(CREATE_SILVER_SERMON_METADATA_TABLE_SQL))
    conn.execute(text(CREATE_SILVER_MEDIA_ASSETS_TABLE_SQL))
    conn.execute(text(CREATE_SILVER_TRANSCRIPTS_TABLE_SQL))
    conn.execute(text(CREATE_SILVER_CRITIQUE_TABLE_SQL))
    conn.execute(text(CREATE_SILVER_PROCESSING_RUNS_TABLE_SQL))
    conn.execute(text(CREATE_GOLD_SERMONS_TABLE_SQL))

    gold_columns = {
        column["name"]
        for column in inspect(conn).get_columns("gold_sermons")
    }

    if "download_link" not in gold_columns:
        conn.execute(text("""
            ALTER TABLE gold_sermons
            ADD COLUMN download_link TEXT
        """))


def create_indexes(conn):

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_silver_source_items_system
        ON silver_source_items(source_system, captured_at)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_silver_sermon_metadata_date
        ON silver_sermon_metadata(preaching_date)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_silver_sermon_metadata_canonical
        ON silver_sermon_metadata(canonical_sermon_id)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_silver_media_assets_type
        ON silver_media_assets(asset_type)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_silver_processing_runs_status
        ON silver_processing_runs(status, started_at)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_silver_critique_canonical
        ON silver_critique(canonical_sermon_id, critique_version)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_gold_sermons_date
        ON gold_sermons(preaching_date)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_gold_sermons_preacher
        ON gold_sermons(preacher_name)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_gold_sermons_serie
        ON gold_sermons(serie)
    """))

    if is_postgres_backend():

        conn.execute(text("""
            CREATE EXTENSION IF NOT EXISTS pg_trgm
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_gold_sermons_title_trgm
            ON gold_sermons
            USING gin (lower(title) gin_trgm_ops)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_gold_sermons_preacher_trgm
            ON gold_sermons
            USING gin (lower(preacher_name) gin_trgm_ops)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_gold_sermons_serie_trgm
            ON gold_sermons
            USING gin (lower(serie) gin_trgm_ops)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_gold_sermons_text_reference_trgm
            ON gold_sermons
            USING gin (lower(text_reference) gin_trgm_ops)
        """))


def initialize_database():

    from .study_db import create_study_indexes, ensure_study_schema

    with get_engine().begin() as conn:
        ensure_schema(conn)
        create_indexes(conn)
        ensure_study_schema(conn)
        create_study_indexes(conn)


def fetch_all(query, params=None):

    with get_engine().connect() as conn:
        rows = conn.execute(text(query), params or {}).mappings().all()

    return [dict(row) for row in rows]


def fetch_one(query, params=None):

    with get_engine().connect() as conn:
        row = conn.execute(text(query), params or {}).mappings().first()

    return dict(row) if row else None


def execute(query, params=None):

    with get_engine().begin() as conn:
        conn.execute(text(query), params or {})


def execute_many(query, rows):

    with get_engine().begin() as conn:
        conn.execute(text(query), rows)


def begin_processing_run(pipeline_name: str, input_ref: str = "") -> str:

    run_id = new_run_id()

    execute("""
        INSERT INTO silver_processing_runs (
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
            :status,
            :started_at,
            :finished_at
        )
    """, {
        "run_id": run_id,
        "pipeline_name": pipeline_name,
        "input_ref": input_ref,
        "status": "running",
        "started_at": utc_now_iso(),
        "finished_at": None,
    })

    return run_id


def finish_processing_run(run_id: str, status: str):

    execute("""
        UPDATE silver_processing_runs
        SET
            status = :status,
            finished_at = :finished_at
        WHERE run_id = :run_id
    """, {
        "run_id": run_id,
        "status": status,
        "finished_at": utc_now_iso(),
    })


def list_tables():

    return inspect(get_engine()).get_table_names()

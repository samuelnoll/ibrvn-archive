from functools import lru_cache

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


CREATE_SERMONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sermons (
    preaching_date TEXT PRIMARY KEY,
    preacher_name TEXT,
    title TEXT,
    text_reference TEXT,
    serie TEXT,
    youtube_link TEXT,
    wordpress_link TEXT,
    media_link TEXT
)
"""


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

    conn.execute(text(CREATE_SERMONS_TABLE_SQL))


def create_indexes(conn):

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_sermons_date
        ON sermons(preaching_date)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_sermons_preacher
        ON sermons(preacher_name)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_sermons_serie
        ON sermons(serie)
    """))

    if is_postgres_backend():

        conn.execute(text("""
            CREATE EXTENSION IF NOT EXISTS pg_trgm
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sermons_title_trgm
            ON sermons
            USING gin (lower(title) gin_trgm_ops)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sermons_preacher_trgm
            ON sermons
            USING gin (lower(preacher_name) gin_trgm_ops)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sermons_serie_trgm
            ON sermons
            USING gin (lower(serie) gin_trgm_ops)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sermons_text_reference_trgm
            ON sermons
            USING gin (lower(text_reference) gin_trgm_ops)
        """))


def initialize_database():

    with get_engine().begin() as conn:
        ensure_schema(conn)
        create_indexes(conn)


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


def list_tables():

    return inspect(get_engine()).get_table_names()

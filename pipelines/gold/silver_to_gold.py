import sqlite3
import pandas as pd

CSV_PATH = "data/silver/sermons_clean.csv"
DB_PATH = "data/gold/sermons.db"


def create_table(conn):

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sermons (

        body_date TEXT PRIMARY KEY,
        post_date TEXT,
        file_preaching_date TEXT,

        preacher_name TEXT,
        poster_name TEXT,
        file_preacher_name TEXT,

        text TEXT,
        text_book TEXT,
        text_chapter TEXT,
        text_verses TEXT,

        file_path TEXT,
        youtube_link TEXT,

        tags TEXT,
        categories TEXT
    )
    """)


def create_indexes(conn):

    conn.execute("CREATE INDEX IF NOT EXISTS idx_preacher ON sermons(preacher_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_book ON sermons(text_book)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON sermons(body_date)")


def create_search_table(conn):

    conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS sermons_search
    USING fts5(
        body_date,
        preacher_name,
        text,
        text_book,
        tags,
        categories
    )
    """)


def refresh_search_table(conn):

    conn.execute("DELETE FROM sermons_search")

    conn.execute("""
    INSERT INTO sermons_search
    SELECT
        body_date,
        preacher_name,
        text,
        text_book,
        tags,
        categories
    FROM sermons
    """)


def upsert_rows(conn, df):

    for _, row in df.iterrows():

        conn.execute("""
        INSERT INTO sermons VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(body_date) DO UPDATE SET

            post_date=excluded.post_date,
            file_preaching_date=excluded.file_preaching_date,
            preacher_name=excluded.preacher_name,
            poster_name=excluded.poster_name,
            file_preacher_name=excluded.file_preacher_name,
            text=excluded.text,
            text_book=excluded.text_book,
            text_chapter=excluded.text_chapter,
            text_verses=excluded.text_verses,
            file_path=excluded.file_path,
            youtube_link=excluded.youtube_link,
            tags=excluded.tags,
            categories=excluded.categories
        """, tuple(row))


def run():

    df = pd.read_csv(CSV_PATH)

    conn = sqlite3.connect(DB_PATH)

    create_table(conn)
    create_indexes(conn)

    upsert_rows(conn, df)

    create_search_table(conn)
    refresh_search_table(conn)

    conn.commit()
    conn.close()

    print("Gold table merged and indexed")

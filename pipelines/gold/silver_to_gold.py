import sqlite3
import pandas as pd

CSV_PATH = "data/silver/wordpress_sermons_clean.csv"
DB_PATH = "data/gold/sermons.db"


def create_table(conn):

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sermons (
        body_date TEXT PRIMARY KEY,
        file_date TEXT,
        pregador TEXT,
        texto_lido TEXT,
        mp3 TEXT,
        youtube TEXT,
        mp3_path TEXT,
        tags TEXT,
        categorias TEXT
    )
    """)


def upsert_rows(conn, df):

    for _, row in df.iterrows():

        conn.execute("""
        INSERT INTO sermons (
            post_date,
            body_date,
            file_preaching_date,
            preacher_name,
            poster_name,
            file_preacher_name,
            text_reference,
            text_book,
            text_chapter,
            text_verses,
            file_path,
            youtube_link,
            tags,
            categories
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(body_date) DO UPDATE SET
            post_date=excluded.post_date,
            body_date=excluded.body_date,
            file_preaching_date=excluded.file_preaching_date,
            preacher_name=excluded.preacher_name,
            poster_name=excluded.poster_name,
            file_preacher_name=excluded.file_preacher_name,
            text_reference=excluded.text_reference,
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

    upsert_rows(conn, df)

    conn.commit()
    conn.close()

    print("Gold table merged")


if __name__ == "__main__":
    run()


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
            body_date,
            file_date,
            pregador,
            texto_lido,
            mp3,
            youtube,
            mp3_path,
            tags,
            categorias
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(body_date) DO UPDATE SET
            file_date=excluded.file_date,
            pregador=excluded.pregador,
            texto_lido=excluded.texto_lido,
            mp3=excluded.mp3,
            youtube=excluded.youtube,
            mp3_path=excluded.mp3_path,
            tags=excluded.tags,
            categorias=excluded.categorias
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


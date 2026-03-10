from fastapi import FastAPI
import sqlite3

app = FastAPI()

DB_PATH = "data/gold/sermons.db"


def get_conn():
    return sqlite3.connect(DB_PATH)


@app.get("/sermons")

def list_sermons(limit: int = 50):

    conn = get_conn()

    rows = conn.execute("""
        SELECT body_date, preacher_name, text, file_path, youtube_link
        FROM sermons
        ORDER BY body_date DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()

    return rows


@app.get("/search")

def search(q: str):

    conn = get_conn()

    rows = conn.execute("""
        SELECT
            s.body_date,
            s.preacher_name,
            s.text,
            s.file_path,
            s.youtube_link

        FROM sermons_search f
        JOIN sermons s
        ON f.body_date = s.body_date

        WHERE sermons_search MATCH ?

        ORDER BY s.body_date DESC
        LIMIT 50
    """, (q,)).fetchall()

    conn.close()

    return rows

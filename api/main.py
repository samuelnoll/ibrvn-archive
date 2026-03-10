from fastapi import FastAPI
import sqlite3
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

DB_PATH = "data/gold/sermons.db"


def get_conn():
    return sqlite3.connect(DB_PATH)


@app.get("/sermons")

def list_sermons(limit: int = 50):

    conn = get_conn()

    rows = conn.execute("""
        SELECT body_date, preacher_name, text_reference, file_path, youtube_link
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
            s.text_reference,
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

@app.get("/search_html", response_class=HTMLResponse)
def search_html(q: str = ""):

    conn = get_conn()

    rows = conn.execute("""
        SELECT
            s.body_date,
            s.preacher_name,
            s.text_reference,
            s.file_path,
            s.youtube_link

        FROM sermons_search f
        JOIN sermons s
        ON f.body_date = s.body_date

        WHERE sermons_search MATCH ?

        ORDER BY bm25(sermons_search)

    """, (q,)).fetchall()

    conn.close()

    html = ""

    for r in rows:

        date, preacher, text, mp3, youtube = r

        link = mp3 if mp3 else youtube

        html += f"""
        <div class="sermon">
            <div class="date">{date}</div>
            <b>{preacher}</b><br>
            {text}<br>
            <a href="{link}" target="_blank">▶ ouvir</a>
        </div>
        """

    return html

app.mount("/", StaticFiles(directory="web", html=True), name="web")

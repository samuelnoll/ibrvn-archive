from fastapi import FastAPI
import sqlite3

app = FastAPI()

DB = "data/gold/sermons.db"


@app.get("/sermons")
def sermons():

    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")

    return {"tables": cursor.fetchall()}


import sqlite3
from archive_settings import GOLD_DB_PATH

DB_PATH = str(GOLD_DB_PATH)


def get_db():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn

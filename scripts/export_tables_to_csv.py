import sqlite3
import csv
import os

DB_PATH = "data/gold/sermons.db"
OUTPUT_DIR = "data/exports"


def export_table(conn, table):

    cursor = conn.execute(f"SELECT * FROM {table}")

    columns = [description[0] for description in cursor.description]

    rows = cursor.fetchall()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    file_path = f"{OUTPUT_DIR}/{table}.csv"

    with open(file_path, "w", newline="", encoding="utf-8") as f:

        writer = csv.writer(f)

        writer.writerow(columns)

        writer.writerows(rows)

    print(f"Exported {table} → {file_path}")


def list_tables(conn):

    cursor = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name NOT LIKE 'sqlite_%'
    """)

    return [row[0] for row in cursor.fetchall()]


def run():

    conn = sqlite3.connect(DB_PATH)

    tables = list_tables(conn)

    for table in tables:

        export_table(conn, table)

    conn.close()


if __name__ == "__main__":
    run()
import csv
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from archive_database import fetch_all, list_tables
from archive_settings import EXPORT_DIR

OUTPUT_DIR = str(EXPORT_DIR)


def export_table(table):

    rows = fetch_all(f"""
        SELECT *
        FROM {table}
    """)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    file_path = f"{OUTPUT_DIR}/{table}.csv"

    with open(file_path, "w", newline="", encoding="utf-8") as f:

        if rows:
            columns = list(rows[0].keys())
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        else:
            writer = csv.writer(f)
            writer.writerow([])

    print(f"Exported {table} -> {file_path}")


def run():

    for table in list_tables():
        export_table(table)


if __name__ == "__main__":
    run()

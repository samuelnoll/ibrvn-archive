import os
import sys
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from archive_database import fetch_all, fetch_one, initialize_database


def total_rows():

    row = fetch_one("""
        SELECT COUNT(*) AS total
        FROM sermons
    """)

    return row["total"]


def count_missing(column):

    row = fetch_one(f"""
        SELECT COUNT(*) AS total
        FROM sermons
        WHERE {column} IS NULL
        OR {column} = ''
    """)

    return row["total"]


def count_missing_links():

    row = fetch_one("""
        SELECT COUNT(*) AS total
        FROM sermons
        WHERE (youtube_link IS NULL OR youtube_link = '')
        AND (wordpress_link IS NULL OR wordpress_link = '')
    """)

    return row["total"]


def count_duplicates():

    row = fetch_one("""
        SELECT COUNT(*) AS total
        FROM (
            SELECT preaching_date
            FROM sermons
            GROUP BY preaching_date
            HAVING COUNT(*) > 1
        ) duplicates
    """)

    return row["total"]


def get_dates():

    rows = fetch_all("""
        SELECT preaching_date
        FROM sermons
        WHERE preaching_date IS NOT NULL
        AND preaching_date != ''
    """)

    dates = [str(row["preaching_date"]) for row in rows]

    return sorted(dates)


def find_missing_sundays(dates):

    if not dates:
        return []

    start = datetime.fromisoformat(dates[0])
    end = datetime.fromisoformat(dates[-1])

    while start.weekday() != 6:
        start += timedelta(days=1)

    sundays = []
    current = start

    while current <= end:
        sundays.append(current.date().isoformat())
        current += timedelta(days=7)

    existing = set(dates)

    return [
        sunday for sunday in sundays
        if sunday not in existing
    ]


def find_non_sundays(dates):

    non_sundays = []

    for sermon_date in dates:
        try:
            dt = datetime.fromisoformat(sermon_date)

            if dt.weekday() != 6:
                non_sundays.append(sermon_date)
        except ValueError:
            pass

    return non_sundays


def run():

    initialize_database()

    total = total_rows()
    missing_preacher = count_missing("preacher_name")
    missing_reference = count_missing("text_reference")
    missing_date = count_missing("preaching_date")
    missing_series = count_missing("serie")
    missing_media = count_missing("media_link")
    missing_links = count_missing_links()
    duplicates = count_duplicates()
    dates = get_dates()
    missing_sundays = find_missing_sundays(dates)
    non_sundays = find_non_sundays(dates)

    print("\n==============================")
    print(" SERMON DATA QUALITY REPORT")
    print("==============================\n")

    print(f"Total sermons: {total}\n")

    print("Missing values")
    print("----------------")
    print(f"preacher_name: {missing_preacher}")
    print(f"text_reference: {missing_reference}")
    print(f"preaching_date: {missing_date}")
    print(f"serie: {missing_series}")
    print(f"media_link (audio): {missing_media}")
    print(
        "missing source (no youtube_link and no wordpress_link): "
        f"{missing_links}\n"
    )

    print("Integrity checks")
    print("----------------")
    print(f"Duplicate preaching_date values: {duplicates}\n")

    if dates:
        print("Date range")
        print("----------------")
        print(f"First sermon: {dates[0]}")
        print(f"Last sermon: {dates[-1]}\n")

    print("Missing Sundays")
    print("----------------")
    print(f"Total missing Sundays: {len(missing_sundays)}\n")

    for sermon_date in missing_sundays:
        print(sermon_date)

    print("\nNon-Sunday Sermons")
    print("----------------")
    print(f"Total non-Sundays: {len(non_sundays)}\n")

    for sermon_date in non_sundays:
        print(sermon_date)

    print("\nQuality check finished.\n")


if __name__ == "__main__":
    run()

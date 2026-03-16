import sqlite3
from datetime import datetime, timedelta

DB_PATH = "data/gold/archive.db"


def total_rows(conn):

    cursor = conn.execute("SELECT COUNT(*) FROM sermons")
    return cursor.fetchone()[0]


def count_missing(conn, column):

    cursor = conn.execute(f"""
        SELECT COUNT(*)
        FROM sermons
        WHERE {column} IS NULL
        OR {column} = ''
    """)

    return cursor.fetchone()[0]


def count_missing_links(conn):

    cursor = conn.execute("""
        SELECT COUNT(*)
        FROM sermons
        WHERE (youtube_link IS NULL OR youtube_link = '')
        AND (wordpress_link IS NULL OR wordpress_link = '')
    """)

    return cursor.fetchone()[0]


def count_duplicates(conn):

    cursor = conn.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT preaching_date, COUNT(*)
            FROM sermons
            GROUP BY preaching_date
            HAVING COUNT(*) > 1
        )
    """)

    return cursor.fetchone()[0]


def get_dates(conn):

    cursor = conn.execute("""
        SELECT preaching_date
        FROM sermons
        WHERE preaching_date != ''
    """)

    dates = [row[0] for row in cursor.fetchall()]

    return sorted(dates)


def find_missing_sundays(dates):

    if not dates:
        return []

    start = datetime.fromisoformat(dates[0])
    end = datetime.fromisoformat(dates[-1])

    # encontrar primeiro domingo
    while start.weekday() != 6:
        start += timedelta(days=1)

    sundays = []

    current = start

    while current <= end:

        sundays.append(current.date().isoformat())
        current += timedelta(days=7)

    existing = set(dates)

    missing = []

    for sunday in sundays:
        if sunday not in existing:
            missing.append(sunday)

    return missing


def find_non_sundays(dates):

    non_sundays = []

    for d in dates:

        try:
            dt = datetime.fromisoformat(d)

            if dt.weekday() != 6:   # 6 = domingo
                non_sundays.append(d)

        except:
            pass

    return non_sundays


def run():

    conn = sqlite3.connect(DB_PATH)

    total = total_rows(conn)

    missing_preacher = count_missing(conn, "preacher_name")
    missing_reference = count_missing(conn, "text_reference")
    missing_date = count_missing(conn, "preaching_date")
    missing_series = count_missing(conn, "serie")
    missing_media = count_missing(conn, "media_link")

    missing_links = count_missing_links(conn)

    duplicates = count_duplicates(conn)

    dates = get_dates(conn)

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
    print(f"missing source (no youtube_link and no wordpress_link): {missing_links}\n")

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

    for d in missing_sundays:
        print(d)

    print("\nNon-Sunday Sermons")
    print("----------------")
    print(f"Total non-Sundays: {len(non_sundays)}\n")

    for d in non_sundays:
        print(d)

    conn.close()

    print("\nQuality check finished.\n")


if __name__ == "__main__":
    run()

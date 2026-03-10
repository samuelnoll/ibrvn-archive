import sqlite3

DB_PATH = "data/gold/sermons.db"


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


def count_invalid_dates(conn):

    cursor = conn.execute("""
        SELECT COUNT(*)
        FROM sermons
        WHERE preaching_date NOT LIKE '____-__-__'
    """)

    return cursor.fetchone()[0]


def count_old_dates(conn):

    cursor = conn.execute("""
        SELECT COUNT(*)
        FROM sermons
        WHERE preaching_date < '1980-01-01'
    """)

    return cursor.fetchone()[0]


def list_missing_preachers(conn):

    cursor = conn.execute("""
        SELECT preaching_date, text_reference
        FROM sermons
        WHERE preacher_name = ''
    """)

    return cursor.fetchall()


def list_missing_reference(conn):

    cursor = conn.execute("""
        SELECT preaching_date, preacher_name
        FROM sermons
        WHERE text_reference = ''
    """)

    return cursor.fetchall()


def list_missing_series(conn):

    cursor = conn.execute("""
        SELECT preaching_date, preacher_name, text_reference
        FROM sermons
        WHERE serie = ''
    """)

    return cursor.fetchall()


def detect_multiple_preachers_same_series(conn):

    cursor = conn.execute("""
        SELECT serie, preaching_date, COUNT(DISTINCT preacher_name)
        FROM sermons
        WHERE serie != ''
        GROUP BY serie, preaching_date
        HAVING COUNT(DISTINCT preacher_name) > 1
    """)

    return cursor.fetchall()


def run():

    conn = sqlite3.connect(DB_PATH)

    total = total_rows(conn)

    missing_preacher = count_missing(conn, "preacher_name")
    missing_reference = count_missing(conn, "text_reference")
    missing_date = count_missing(conn, "preaching_date")
    missing_link = count_missing(conn, "source_link")
    missing_series = count_missing(conn, "serie")

    duplicates = count_duplicates(conn)
    invalid_dates = count_invalid_dates(conn)
    old_dates = count_old_dates(conn)

    multi_preachers_series = detect_multiple_preachers_same_series(conn)

    print("\n==============================")
    print(" SERMON DATA QUALITY REPORT")
    print("==============================\n")

    print(f"Total sermons: {total}\n")

    print("Missing values")
    print("----------------")
    print(f"preacher_name: {missing_preacher}")
    print(f"text_reference: {missing_reference}")
    print(f"preaching_date: {missing_date}")
    print(f"source_link: {missing_link}")
    print(f"serie: {missing_series}\n")

    print("Integrity checks")
    print("----------------")
    print(f"Duplicate preaching_date values: {duplicates}")
    print(f"Invalid preaching_date format: {invalid_dates}")
    print(f"Dates earlier than 1980: {old_dates}\n")

    print("Series checks")
    print("----------------")
    print(f"multiple preachers in same series/day: {len(multi_preachers_series)}\n")

    print("Problematic rows")
    print("----------------")

    missing_preachers = list_missing_preachers(conn)

    if missing_preachers:
        print("\nRows missing preacher_name:")
        for row in missing_preachers:
            print(row)

    missing_refs = list_missing_reference(conn)

    if missing_refs:
        print("\nRows missing text_reference:")
        for row in missing_refs:
            print(row)

    missing_series_rows = list_missing_series(conn)

    if missing_series_rows:
        print("\nRows missing serie:")
        for row in missing_series_rows:
            print(row)

    if multi_preachers_series:
        print("\nMultiple preachers in same series/day:")
        for row in multi_preachers_series:
            print(row)

    conn.close()

    print("\nQuality check finished.\n")


if __name__ == "__main__":
    run()
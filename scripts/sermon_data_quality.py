import sqlite3

DB_PATH = "data/gold/sermons.db"


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
            SELECT id, COUNT(*)
            FROM sermons
            GROUP BY id
            HAVING COUNT(*) > 1
        )
    """)

    return cursor.fetchone()[0]


def total_rows(conn):

    cursor = conn.execute("SELECT COUNT(*) FROM sermons")

    return cursor.fetchone()[0]


def run():

    conn = sqlite3.connect(DB_PATH)

    total = total_rows(conn)

    missing_preacher = count_missing(conn, "preacher_name")
    missing_reference = count_missing(conn, "text_reference")
    missing_date = count_missing(conn, "preaching_date")
    missing_link = count_missing(conn, "source_link")

    duplicates = count_duplicates(conn)

    print("\nData Quality Report\n")

    print(f"Total sermons: {total}\n")

    print(f"Missing preacher_name: {missing_preacher}")
    print(f"Missing text_reference: {missing_reference}")
    print(f"Missing preaching_date: {missing_date}")
    print(f"Missing source_link: {missing_link}")

    print(f"\nDuplicate sermon IDs: {duplicates}")

    conn.close()


if __name__ == "__main__":
    run()

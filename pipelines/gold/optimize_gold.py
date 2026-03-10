import sqlite3

DB_PATH = "data/gold/sermons.db"


def create_indexes(conn):

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sermons_date ON sermons(preaching_date)"
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sermons_preacher ON sermons(preacher_name)"
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sermons_serie ON sermons(serie)"
    )


def create_search_table(conn):

    conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS sermons_search
    USING fts5(
        preaching_date,
        preacher_name,
        text_reference,
        serie
    )
    """)


def refresh_search_table(conn):

    conn.execute("DELETE FROM sermons_search")

    conn.execute("""
    INSERT INTO sermons_search
    SELECT
        preaching_date,
        preacher_name,
        text_reference,
        serie
    FROM sermons
    """)


def run():

    conn = sqlite3.connect(DB_PATH)

    create_indexes(conn)

    create_search_table(conn)

    refresh_search_table(conn)

    conn.commit()
    conn.close()

    print("Gold database optimized")


if __name__ == "__main__":
    run()

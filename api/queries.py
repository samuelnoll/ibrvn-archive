from .db import get_db


def get_last_update():

    conn = get_db()

    row = conn.execute(
        "SELECT MAX(preaching_date) as d FROM sermons"
    ).fetchone()

    conn.close()

    return row["d"]


def get_recent_sermons(limit=20):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM sermons
        ORDER BY preaching_date DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()

    return rows


def search_sermons(q):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM sermons
        WHERE
        title LIKE ?
        OR preacher_name LIKE ?
        OR serie LIKE ?
        OR text_reference LIKE ?
        ORDER BY preaching_date DESC
    """, [f"%{q}%"]*4).fetchall()

    conn.close()

    return rows


def get_books():

    conn = get_db()

    rows = conn.execute("""
        SELECT
        TRIM(
            CASE
                WHEN SUBSTR(text_reference,1,INSTR(text_reference,' ')-1) IN ('1','2','3')
                THEN
                    SUBSTR(
                        text_reference,
                        1,
                        INSTR(text_reference,' ') +
                        INSTR(SUBSTR(text_reference, INSTR(text_reference,' ')+1),' ')
                    )
                ELSE
                    SUBSTR(text_reference,1,INSTR(text_reference,' ')-1)
            END
        ) AS book,
        COUNT(*) as n
        FROM sermons
        WHERE text_reference != ''
        AND book NOT IN ('','1','2','3')
        GROUP BY book
        ORDER BY book
    """).fetchall()

    conn.close()

    return rows


def sermons_by_book(book):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM sermons
        WHERE text_reference LIKE ?
        ORDER BY preaching_date DESC
    """, (f"{book}%",)).fetchall()

    conn.close()

    return rows


def get_series():

    conn = get_db()

    rows = conn.execute("""
        SELECT serie, COUNT(*) as n
        FROM sermons
        WHERE serie != ''
        GROUP BY serie
        ORDER BY serie
    """).fetchall()

    conn.close()

    return rows


def sermons_by_series(serie):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM sermons
        WHERE serie = ?
        ORDER BY preaching_date DESC
    """, (serie,)).fetchall()

    conn.close()

    return rows


def get_preachers():

    conn = get_db()

    rows = conn.execute("""
        SELECT preacher_name, COUNT(*) as n
        FROM sermons
        GROUP BY preacher_name
        ORDER BY preacher_name
    """).fetchall()

    conn.close()

    return rows


def sermons_by_preacher(preacher):

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM sermons
        WHERE preacher_name = ?
        ORDER BY preaching_date DESC
    """, (preacher,)).fetchall()

    conn.close()

    return rows


def get_stats():

    conn = get_db()

    total = conn.execute(
        "SELECT COUNT(*) FROM sermons"
    ).fetchone()[0]

    preachers = conn.execute(
        "SELECT COUNT(DISTINCT preacher_name) FROM sermons"
    ).fetchone()[0]

    series = conn.execute(
        "SELECT COUNT(DISTINCT serie) FROM sermons WHERE serie != ''"
    ).fetchone()[0]

    conn.close()

    return {
        "total": total,
        "preachers": preachers,
        "series": series
    }


def timeline():

    conn = get_db()

    rows = conn.execute("""
        SELECT
        strftime('%Y', preaching_date) as year,
        COUNT(*) as n
        FROM sermons
        GROUP BY year
        ORDER BY year
    """).fetchall()

    conn.close()

    return rows

def get_home_stats():

    conn = get_db()

    row = conn.execute("""

    SELECT
        COUNT(*) as sermons,
        COUNT(DISTINCT preacher_name) as preachers,
        COUNT(DISTINCT serie) as series

    FROM sermons

    """).fetchone()

    conn.close()

    return row
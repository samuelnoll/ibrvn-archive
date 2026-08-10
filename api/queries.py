from collections import Counter
from datetime import date, datetime

from .db import fetch_all, fetch_one

GOLD_TABLE = "gold_sermons"


def format_brazilian_date(value):

    if not value:
        return ""

    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")

    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    date_str = str(value)
    parts = date_str.split("-")

    if len(parts) != 3:
        return date_str

    year, month, day = parts

    if len(year) != 4 or len(month) != 2 or len(day) != 2:
        return date_str

    return f"{day}/{month}/{year}"


def format_duration_minutes(value):

    if value is None:
        return ""

    try:
        total_seconds = float(value)
    except (TypeError, ValueError):
        return ""

    if total_seconds <= 0:
        return ""

    minutes = int(total_seconds // 60)

    if minutes <= 0:
        return ""

    return f"{minutes}min"


def extract_book_name(text_reference):

    if not text_reference:
        return ""

    parts = str(text_reference).strip().split()

    if not parts:
        return ""

    if parts[0] in {"1", "2", "3"} and len(parts) >= 2:
        return f"{parts[0]} {parts[1]}".strip()

    if parts[0] in {"1", "2", "3"}:
        return ""

    return parts[0].strip()


def serialize_sermon(row):

    sermon = dict(row)
    sermon["preaching_date"] = format_brazilian_date(
        sermon.get("preaching_date")
    )
    sermon["duration_minutes"] = format_duration_minutes(
        sermon.get("duration_seconds")
    )
    return sermon


def serialize_sermons(rows):

    return [
        serialize_sermon(row)
        for row in rows
    ]


def get_last_update():

    row = fetch_one("""
        SELECT MAX(preaching_date) AS d
        FROM {table}
    """.format(table=GOLD_TABLE))

    return format_brazilian_date(row["d"]) if row else ""


def get_recent_sermons(limit=20):

    rows = fetch_all("""
        SELECT *
        FROM {table}
        ORDER BY preaching_date DESC
        LIMIT :limit
    """.format(table=GOLD_TABLE), {"limit": limit})

    return serialize_sermons(rows)


def search_sermons(q):

    pattern = f"%{q.lower()}%"

    rows = fetch_all("""
        SELECT *
        FROM {table}
        WHERE
            LOWER(COALESCE(title, '')) LIKE :pattern
            OR LOWER(COALESCE(preacher_name, '')) LIKE :pattern
            OR LOWER(COALESCE(serie, '')) LIKE :pattern
            OR LOWER(COALESCE(text_reference, '')) LIKE :pattern
        ORDER BY preaching_date DESC
    """.format(table=GOLD_TABLE), {"pattern": pattern})

    return serialize_sermons(rows)


def get_books():

    rows = fetch_all("""
        SELECT text_reference
        FROM {table}
        WHERE text_reference IS NOT NULL
        AND text_reference != ''
    """.format(table=GOLD_TABLE))

    counts = Counter()

    for row in rows:
        book = extract_book_name(row["text_reference"])

        if book and book not in {"1", "2", "3"}:
            counts[book] += 1

    return [
        {
            "book": book,
            "n": counts[book],
        }
        for book in sorted(counts)
    ]


def sermons_by_book(book):

    rows = fetch_all("""
        SELECT *
        FROM {table}
        WHERE LOWER(COALESCE(text_reference, '')) LIKE :prefix
        ORDER BY preaching_date DESC
    """.format(table=GOLD_TABLE), {"prefix": f"{book.lower()}%"})

    return serialize_sermons(rows)


def get_series():

    return fetch_all("""
        SELECT serie, preacher_name, COUNT(*) AS n
        FROM {table}
        WHERE serie IS NOT NULL
        AND serie != ''
        GROUP BY serie, preacher_name
        ORDER BY serie, preacher_name
    """.format(table=GOLD_TABLE))


def sermons_by_series(serie):

    rows = fetch_all("""
        SELECT *
        FROM {table}
        WHERE serie = :serie
        ORDER BY preaching_date DESC
    """.format(table=GOLD_TABLE), {"serie": serie})

    return serialize_sermons(rows)


def sermons_by_series_and_preacher(serie, preacher):

    rows = fetch_all("""
        SELECT *
        FROM {table}
        WHERE serie = :serie
        AND preacher_name = :preacher
        ORDER BY preaching_date DESC
    """.format(table=GOLD_TABLE), {
        "serie": serie,
        "preacher": preacher,
    })

    return serialize_sermons(rows)


def get_preachers():

    return fetch_all("""
        SELECT preacher_name, COUNT(*) AS n
        FROM {table}
        WHERE preacher_name IS NOT NULL
        AND preacher_name != ''
        GROUP BY preacher_name
        ORDER BY preacher_name
    """.format(table=GOLD_TABLE))


def get_years():

    rows = fetch_all("""
        SELECT preaching_date
        FROM {table}
        WHERE preaching_date IS NOT NULL
        AND preaching_date != ''
    """.format(table=GOLD_TABLE))

    counts = Counter()

    for row in rows:
        year = str(row["preaching_date"])[:4]

        if len(year) == 4 and year.isdigit():
            counts[year] += 1

    return [
        {
            "year": year,
            "n": counts[year],
        }
        for year in sorted(counts, reverse=True)
    ]


def sermons_by_preacher(preacher):

    rows = fetch_all("""
        SELECT *
        FROM {table}
        WHERE preacher_name = :preacher
        ORDER BY preaching_date DESC
    """.format(table=GOLD_TABLE), {"preacher": preacher})

    return serialize_sermons(rows)


def sermons_by_year(year):

    rows = fetch_all("""
        SELECT *
        FROM {table}
        WHERE preaching_date LIKE :year_prefix
        ORDER BY preaching_date DESC
    """.format(table=GOLD_TABLE), {"year_prefix": f"{year}%"})

    return serialize_sermons(rows)


def get_home_stats():

    row = fetch_one("""
        SELECT
            COUNT(*) AS sermons,
            COUNT(DISTINCT NULLIF(preacher_name, '')) AS preachers,
            COUNT(DISTINCT NULLIF(serie, '')) AS series
        FROM {table}
    """.format(table=GOLD_TABLE))

    return row or {
        "sermons": 0,
        "preachers": 0,
        "series": 0,
    }


def get_transcript(canonical_sermon_id):

    row = fetch_one("""
        SELECT
            gs.canonical_sermon_id,
            gs.preaching_date,
            gs.title,
            gs.preacher_name,
            gs.text_reference,
            st.transcript_version,
            st.transcript_text,
            st.model_name,
            st.created_at
        FROM silver_transcripts st
        JOIN {table} gs
          ON gs.canonical_sermon_id = st.canonical_sermon_id
        WHERE st.canonical_sermon_id = :canonical_sermon_id
        ORDER BY st.transcript_version DESC
        LIMIT 1
    """.format(table=GOLD_TABLE), {"canonical_sermon_id": canonical_sermon_id})

    if not row:
        return None

    transcript = dict(row)
    transcript["preaching_date"] = format_brazilian_date(
        transcript.get("preaching_date")
    )
    return transcript

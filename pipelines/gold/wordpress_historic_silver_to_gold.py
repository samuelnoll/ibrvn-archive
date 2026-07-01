import os
import re
import sys
import unicodedata

import pandas as pd
import yaml
from sqlalchemy import text

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from archive_database import ensure_schema, get_engine

CSV_PATH = "data/silver/wordpress_sermons.csv"

UPSERT_SQL = """
INSERT INTO sermons (
    preaching_date,
    preacher_name,
    title,
    text_reference,
    serie,
    youtube_link,
    wordpress_link,
    media_link
)
VALUES (
    :preaching_date,
    :preacher_name,
    :title,
    :text_reference,
    :serie,
    :youtube_link,
    :wordpress_link,
    :media_link
)
ON CONFLICT(preaching_date) DO UPDATE SET
    preacher_name = COALESCE(
        NULLIF(EXCLUDED.preacher_name, ''),
        sermons.preacher_name
    ),
    title = COALESCE(
        NULLIF(sermons.title, ''),
        NULLIF(EXCLUDED.title, ''),
        sermons.title
    ),
    text_reference = COALESCE(
        NULLIF(EXCLUDED.text_reference, ''),
        sermons.text_reference
    ),
    serie = COALESCE(
        NULLIF(EXCLUDED.serie, ''),
        sermons.serie
    ),
    youtube_link = COALESCE(
        NULLIF(sermons.youtube_link, ''),
        NULLIF(EXCLUDED.youtube_link, ''),
        sermons.youtube_link
    ),
    wordpress_link = COALESCE(
        NULLIF(EXCLUDED.wordpress_link, ''),
        sermons.wordpress_link
    ),
    media_link = COALESCE(
        NULLIF(EXCLUDED.media_link, ''),
        sermons.media_link
    )
"""


def load_preacher_map():

    with open("config/preachers.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return {k.lower(): v for k, v in data.items()}


PREACHER_MAP = load_preacher_map()


def normalize_text(text_value):

    if pd.isna(text_value):
        return ""

    normalized = str(text_value)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )

    return normalized.lower().strip()


def choose_preaching_date(row):

    if row["file_preaching_date"]:
        return row["file_preaching_date"]

    if row["body_date"]:
        return row["body_date"]

    return row["post_date"]


def choose_preacher(row):

    preacher = row["file_preacher_name"] or row["preacher_name"]

    if not preacher:
        return ""

    key = normalize_text(preacher)

    if key in PREACHER_MAP:
        return PREACHER_MAP[key]

    return preacher.title()


def extract_serie(row):

    tags = row["tags"] or ""
    categories = row["categories"] or ""
    combined = tags + ";" + categories

    match = re.search(r"S[Ã©e]rie:\s*([^;]+)", combined)

    if match:
        return match.group(1).strip()

    return ""


def transform_dataframe(df):

    df["preaching_date"] = df.apply(choose_preaching_date, axis=1)
    df["preacher_name"] = df.apply(choose_preacher, axis=1)
    df["serie"] = df.apply(extract_serie, axis=1)
    df["youtube_link"] = ""
    df["wordpress_link"] = df["source_link"]

    return df[[
        "preaching_date",
        "preacher_name",
        "title",
        "text_reference",
        "serie",
        "youtube_link",
        "wordpress_link",
        "media_link",
    ]]


def to_records(df):

    return df.fillna("").to_dict(orient="records")


def run():

    df = pd.read_csv(CSV_PATH).fillna("")
    records = to_records(transform_dataframe(df))

    with get_engine().begin() as conn:
        ensure_schema(conn)

        if records:
            conn.execute(text(UPSERT_SQL), records)

    print("WordPress sermons loaded into gold")


if __name__ == "__main__":
    run()

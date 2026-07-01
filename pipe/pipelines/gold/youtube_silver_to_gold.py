import argparse
import os
import sys
import unicodedata

import pandas as pd
import yaml
from sqlalchemy import text

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.db import ensure_schema, get_engine

HISTORIC_CSV = "data/silver/youtube_sermons.csv"
WEEKLY_CSV = "data/silver/youtube_weekly_sermons.csv"

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
        NULLIF(EXCLUDED.title, ''),
        sermons.title
    ),
    text_reference = COALESCE(
        NULLIF(sermons.text_reference, ''),
        NULLIF(EXCLUDED.text_reference, ''),
        sermons.text_reference
    ),
    serie = COALESCE(
        NULLIF(sermons.serie, ''),
        NULLIF(EXCLUDED.serie, ''),
        sermons.serie
    ),
    youtube_link = COALESCE(
        NULLIF(EXCLUDED.youtube_link, ''),
        sermons.youtube_link
    ),
    wordpress_link = COALESCE(
        NULLIF(sermons.wordpress_link, ''),
        NULLIF(EXCLUDED.wordpress_link, ''),
        sermons.wordpress_link
    ),
    media_link = COALESCE(
        NULLIF(sermons.media_link, ''),
        NULLIF(EXCLUDED.media_link, ''),
        sermons.media_link
    )
"""


def load_preacher_map():

    with open("pipe/config/preachers.yaml", "r", encoding="utf-8") as f:
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


def choose_preacher(row):

    preacher = (
        row["preacher_playlist"]
        or row["preacher_title"]
        or row["preacher_description"]
    )

    if not preacher:
        return ""

    key = normalize_text(preacher)

    if key in PREACHER_MAP:
        return PREACHER_MAP[key]

    return preacher.title()


def transform_dataframe(df):

    df["preacher_name"] = df.apply(
        choose_preacher,
        axis=1
    )

    df["youtube_link"] = df["youtube_link"]
    df["wordpress_link"] = ""
    df["media_link"] = ""

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


def run(mode):

    csv_path = HISTORIC_CSV if mode == "historic" else WEEKLY_CSV
    df = pd.read_csv(csv_path).fillna("")
    records = to_records(transform_dataframe(df))

    with get_engine().begin() as conn:
        ensure_schema(conn)

        if records:
            conn.execute(text(UPSERT_SQL), records)

    print("YouTube sermons loaded into gold")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["historic", "weekly"],
        default="historic"
    )

    args = parser.parse_args()

    run(args.mode)

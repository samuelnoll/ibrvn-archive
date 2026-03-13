import sqlite3
import pandas as pd
import unicodedata
import yaml
import argparse

HISTORIC_CSV = "data/silver/youtube_sermons.csv"
WEEKLY_CSV = "data/silver/youtube_weekly_sermons.csv"

DB_PATH = "data/gold/sermons.db"


def load_preacher_map():

    with open("config/preachers.yaml", "r") as f:
        data = yaml.safe_load(f)

    return {k.lower(): v for k, v in data.items()}


PREACHER_MAP = load_preacher_map()


def normalize_text(text):

    if pd.isna(text):
        return ""

    text = str(text)

    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        c for c in text
        if not unicodedata.combining(c)
    )

    return text.lower().strip()


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

    df["wordpress_link"] = None

    df["media_link"] = None

    df_gold = df[[
        "preaching_date",
        "preacher_name",
        "title",
        "text_reference",
        "serie",
        "youtube_link",
        "wordpress_link",
        "media_link"
    ]]

    return df_gold


def create_table(conn):

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sermons (

        preaching_date TEXT PRIMARY KEY,
        preacher_name TEXT,
        title TEXT,
        text_reference TEXT,
        serie TEXT,
        youtube_link TEXT,
        wordpress_link TEXT,
        media_link TEXT
    )
    """)


def upsert_rows(conn, df):

    for _, row in df.iterrows():

        conn.execute("""
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(preaching_date) DO UPDATE SET
            preacher_name = excluded.preacher_name,

            title = COALESCE(
                excluded.title,
                sermons.title
            ),

            text_reference = COALESCE(
                sermons.text_reference,
                excluded.text_reference
            ),

            serie = COALESCE(
                sermons.serie,
                excluded.serie
            ),

            youtube_link = COALESCE(
                excluded.youtube_link,
                sermons.youtube_link
            ),

            wordpress_link = COALESCE(
                sermons.wordpress_link,
                excluded.wordpress_link
            ),

            media_link = COALESCE(
                sermons.media_link,
                excluded.media_link
            );
        """, tuple(row))


def run(mode):

    csv_path = HISTORIC_CSV if mode == "historic" else WEEKLY_CSV

    df = pd.read_csv(csv_path).fillna("")

    df_gold = transform_dataframe(df)

    conn = sqlite3.connect(DB_PATH)

    create_table(conn)

    upsert_rows(conn, df_gold)

    conn.commit()

    conn.close()

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

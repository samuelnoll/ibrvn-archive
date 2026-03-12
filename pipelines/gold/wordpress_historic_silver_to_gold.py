import sqlite3
import pandas as pd
import re
import unicodedata
import yaml

CSV_PATH = "data/silver/wordpress_sermons.csv"
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

    text = "".join(c for c in text if not unicodedata.combining(c))

    return text.lower().strip()


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

    m = re.search(r"S[ée]rie:\s*([^;]+)", combined)

    if m:
        return m.group(1).strip()

    return ""


def transform_dataframe(df):

    df["preaching_date"] = df.apply(choose_preaching_date, axis=1)

    df["preacher_name"] = df.apply(choose_preacher, axis=1)

    df["serie"] = df.apply(extract_serie, axis=1)

    df["youtube_link"] = None

    df["wordpress_link"] = df["source_link"]

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
                sermons.title,
                excluded.title
            ),
            
            text_reference = COALESCE(
                excluded.text_reference,
                sermons.text_reference
            ),

            serie = COALESCE(
                excluded.serie,
                sermons.serie
            ),

            youtube_link = COALESCE(
                sermons.youtube_link,
                excluded.youtube_link
            ),

            wordpress_link = COALESCE(
                excluded.wordpress_link,
                sermons.wordpress_link
            ),

            media_link = COALESCE(
                excluded.media_link,
                sermons.media_link
            );
        """, tuple(row))


def run():

    df = pd.read_csv(CSV_PATH).fillna("")

    df_gold = transform_dataframe(df)

    conn = sqlite3.connect(DB_PATH)

    create_table(conn)

    upsert_rows(conn, df_gold)

    conn.commit()
    conn.close()

    print("WordPress sermons loaded into gold")

import sqlite3
import pandas as pd
import re
import unicodedata
import yaml

CSV_PATH = "data/silver/wordpress_sermons_clean.csv"
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

    # fallback: capitalizar
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

    df["source"] = "wordpress"

    df["source_link"] = df["file_path"]

    df_gold = df[[
        "preaching_date",
        "preacher_name",
        "text_reference",
        "serie",
        "source",
        "source_link"
    ]]

    return df_gold


def create_table(conn):

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sermons (

        preaching_date TEXT,
        preacher_name TEXT,
        text_reference TEXT,
        serie TEXT,
        source TEXT,
        source_link TEXT
    )
    """)


def insert_rows(conn, df):

    for _, row in df.iterrows():

        conn.execute("""
        INSERT INTO sermons
        VALUES (?, ?, ?, ?, ?, ?)
        """, tuple(row))


def run():

    df = pd.read_csv(CSV_PATH)

    df_gold = transform_dataframe(df)

    conn = sqlite3.connect(DB_PATH)

    create_table(conn)

    insert_rows(conn, df_gold)

    conn.commit()
    conn.close()

    print("WordPress sermons loaded into gold")

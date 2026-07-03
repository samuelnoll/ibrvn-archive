import glob
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher

import yaml
from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    finish_processing_run,
    get_engine,
    utc_now_iso,
)


FILES_GLOB = "data/bronze/ibrvn.WordPress.*.xml"
MAX_DATE = "2021-12-31"

UPSERT_SOURCE_ITEM_SQL = """
INSERT INTO silver_source_items (
    source_system,
    source_item_id,
    ingestion_run_id,
    payload_version,
    raw_path,
    captured_at
)
VALUES (
    :source_system,
    :source_item_id,
    :ingestion_run_id,
    :payload_version,
    :raw_path,
    :captured_at
)
ON CONFLICT(source_system, source_item_id, payload_version) DO UPDATE SET
    ingestion_run_id = EXCLUDED.ingestion_run_id,
    raw_path = EXCLUDED.raw_path,
    captured_at = EXCLUDED.captured_at
"""

UPSERT_SERMON_METADATA_SQL = """
INSERT INTO silver_sermon_metadata (
    canonical_sermon_id,
    source_system,
    source_item_id,
    preaching_date,
    title,
    preacher_name,
    text_reference,
    serie,
    confidence,
    processed_at
)
VALUES (
    :canonical_sermon_id,
    :source_system,
    :source_item_id,
    :preaching_date,
    :title,
    :preacher_name,
    :text_reference,
    :serie,
    :confidence,
    :processed_at
)
ON CONFLICT(source_system, source_item_id) DO UPDATE SET
    canonical_sermon_id = EXCLUDED.canonical_sermon_id,
    preaching_date = EXCLUDED.preaching_date,
    title = EXCLUDED.title,
    preacher_name = EXCLUDED.preacher_name,
    text_reference = EXCLUDED.text_reference,
    serie = COALESCE(
        NULLIF(TRIM(EXCLUDED.serie), ''),
        NULLIF(TRIM(serie), '')
    ),
    confidence = EXCLUDED.confidence,
    processed_at = EXCLUDED.processed_at
"""

NORMALIZE_EMPTY_SERIE_SQL = """
UPDATE silver_sermon_metadata
SET serie = NULL
WHERE serie IS NOT NULL
  AND TRIM(serie) = ''
"""

UPSERT_MEDIA_ASSET_SQL = """
INSERT INTO silver_media_assets (
    canonical_sermon_id,
    asset_type,
    source_url,
    local_path,
    duration_seconds,
    mime_type
)
VALUES (
    :canonical_sermon_id,
    :asset_type,
    :source_url,
    :local_path,
    :duration_seconds,
    :mime_type
)
ON CONFLICT(canonical_sermon_id, asset_type) DO UPDATE SET
    source_url = EXCLUDED.source_url,
    local_path = EXCLUDED.local_path,
    duration_seconds = EXCLUDED.duration_seconds,
    mime_type = EXCLUDED.mime_type
"""

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "wp": "http://wordpress.org/export/1.2/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

BIBLE_BOOKS = [
    ("Genesis", "Gênesis"),
    ("Exodo", "Êxodo"),
    ("Levitico", "Levítico"),
    ("Numeros", "Números"),
    ("Deuteronomio", "Deuteronômio"),
    ("Josue", "Josué"),
    ("Juizes", "Juízes"),
    ("Rute", "Rute"),
    ("1 Samuel", "1 Samuel"),
    ("2 Samuel", "2 Samuel"),
    ("1 Reis", "1 Reis"),
    ("2 Reis", "2 Reis"),
    ("1 Cronicas", "1 Crônicas"),
    ("2 Cronicas", "2 Crônicas"),
    ("Esdras", "Esdras"),
    ("Neemias", "Neemias"),
    ("Ester", "Ester"),
    ("Jo", "Jó"),
    ("Salmos", "Salmos"),
    ("Proverbios", "Provérbios"),
    ("Eclesiastes", "Eclesiastes"),
    ("Canticos", "Cânticos"),
    ("Isaias", "Isaías"),
    ("Jeremias", "Jeremias"),
    ("Lamentacoes", "Lamentações"),
    ("Ezequiel", "Ezequiel"),
    ("Daniel", "Daniel"),
    ("Oseias", "Oséias"),
    ("Joel", "Joel"),
    ("Amos", "Amós"),
    ("Obadias", "Obadias"),
    ("Jonas", "Jonas"),
    ("Miqueias", "Miquéias"),
    ("Naum", "Naum"),
    ("Habacuque", "Habacuque"),
    ("Sofonias", "Sofonias"),
    ("Ageu", "Ageu"),
    ("Zacarias", "Zacarias"),
    ("Malaquias", "Malaquias"),
    ("Mateus", "Mateus"),
    ("Marcos", "Marcos"),
    ("Lucas", "Lucas"),
    ("Joao", "João"),
    ("Atos", "Atos"),
    ("Romanos", "Romanos"),
    ("1 Corintios", "1 Coríntios"),
    ("2 Corintios", "2 Coríntios"),
    ("Galatas", "Gálatas"),
    ("Efesios", "Efésios"),
    ("Filipenses", "Filipenses"),
    ("Colossenses", "Colossenses"),
    ("1 Tessalonicenses", "1 Tessalonicenses"),
    ("2 Tessalonicenses", "2 Tessalonicenses"),
    ("1 Timoteo", "1 Timóteo"),
    ("2 Timoteo", "2 Timóteo"),
    ("Tito", "Tito"),
    ("Filemon", "Filemom"),
    ("Hebreus", "Hebreus"),
    ("Tiago", "Tiago"),
    ("1 Pedro", "1 Pedro"),
    ("2 Pedro", "2 Pedro"),
    ("1 Joao", "1 João"),
    ("2 Joao", "2 João"),
    ("3 Joao", "3 João"),
    ("Judas", "Judas"),
    ("Apocalipse", "Apocalipse"),
]


def load_preacher_map():

    with open("pipe/config/preachers.yaml", "r", encoding="utf-8") as file_handle:
        data = yaml.safe_load(file_handle)

    return {
        normalize_text(key): value
        for key, value in data.items()
    }


def normalize_text(text_value):

    if not text_value:
        return ""

    normalized = unicodedata.normalize("NFKD", str(text_value))
    normalized = "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
    )

    return normalized.lower().strip()


def normalize_nullable_text(text_value):

    normalized = str(text_value or "").strip()

    return normalized or None


def clean_title_text(text_value):

    if not text_value:
        return ""

    return (
        str(text_value)
        .replace("\u00A0", " ")
        .replace("â€“", "-")
        .replace("Ã¢â‚¬â€œ", "-")
        .strip()
    )


PREACHER_MAP = load_preacher_map()


def is_similar_book(left, right):

    if any(char.isdigit() for char in left + right):
        return False

    return SequenceMatcher(None, left, right).ratio() >= 0.9


def normalize_date(date_str):

    if not date_str:
        return ""

    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.date().isoformat()
    except Exception:
        return ""


def extract_text(title, content):

    del content

    if not title:
        return ""

    title = clean_title_text(title)
    title = re.sub(r"\bI\s+", "1 ", title)
    title = re.sub(r"\bII\s+", "2 ", title)
    title = re.sub(r"\bIII\s+", "3 ", title)
    title = re.sub(r"(\d+)\s*a\s*(\d+)", r"\1-\2", title)
    title = re.sub(r"(\d+)\s*e\s*(\d+)", r"\1-\2", title)

    title_norm = normalize_text(title)
    words = title_norm.split()

    for book_ascii, book_display in BIBLE_BOOKS:
        book_norm = normalize_text(book_ascii)
        pattern = r"\b" + re.escape(book_norm) + r"\b"
        match_book = re.search(pattern, title_norm)

        if not match_book:
            for word in words:
                if is_similar_book(word, book_norm):
                    match_book = True
                    break

        if not match_book:
            continue

        start = title_norm.find(book_norm)

        if start == -1:
            continue

        fragment = title_norm[start + len(book_norm):].strip()
        match_ref = re.search(r"(\d+)(?::\s*(\d+(?:-\d+)?))?", fragment)

        if not match_ref:
            return book_display

        chapter = match_ref.group(1)
        verse = match_ref.group(2)

        if verse:
            return f"{book_display} {chapter}:{verse}"

        return f"{book_display} {chapter}"

    return ""


def extract_mp3(content):

    if not content:
        return ""

    urls = re.findall(r'https?://[^"\'>]+', content)
    audio_ext = (".mp3", ".m4a", ".wav", ".ogg")

    for url in urls:
        if url.lower().strip().endswith(audio_ext):
            return url.strip()

    return ""


def extract_preacher(content):

    if not content:
        return ""

    match = re.search(r"por\s+([^<\n\r]+)", content, flags=re.IGNORECASE)

    if not match:
        return ""

    preacher = match.group(1).strip()
    preacher = re.split(r"[|,.:-]\s*", preacher)[0].strip()
    return preacher


def extract_file_info(mp3_url):

    if not mp3_url:
        return "", ""

    filename = os.path.basename(mp3_url)
    patterns = [
        r"(20\d{2})[_\-](\d{2})[_\-](\d{2})[_\-]([^\W\d_]+)",
        r"([^\W\d_]+)[_\-](\d{2})[_\-](\d{2})[_\-](\d{2})",
        r"([^\W\d_]+)[\s\-](\d{2})\.(\d{2})\.(\d{4})",
        r"([^\W\d_]+)[\s\-](\d{2})\-(\d{2})\-(\d{4})",
    ]

    for index, pattern in enumerate(patterns):
        match = re.search(pattern, filename)

        if not match:
            continue

        if index == 0:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}", match.group(4)

        if index == 1:
            return f"20{match.group(4)}-{match.group(3)}-{match.group(2)}", match.group(1)

        return f"{match.group(4)}-{match.group(3)}-{match.group(2)}", match.group(1)

    return "", ""


def extract_body_date(title):

    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", title or "")

    if not match:
        return ""

    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"


def extract_title(title):

    if not title:
        return ""

    title = clean_title_text(title)

    if " - " not in title:
        return ""

    first = title.rsplit(" - ", 1)[0].strip()

    if normalize_text(first).startswith("pregacao"):
        return ""

    return first


def choose_preaching_date(post_date, body_date, file_preaching_date):

    if file_preaching_date:
        return file_preaching_date

    if body_date:
        return body_date

    return post_date


def choose_preacher(file_preacher_name, preacher_name):

    preacher = file_preacher_name or preacher_name

    if not preacher:
        return ""

    key = normalize_text(preacher)

    if key in PREACHER_MAP:
        return PREACHER_MAP[key]

    return preacher.title()


def extract_serie(tags, categories):

    for value in list(tags or []) + list(categories or []):
        if normalize_text(value).startswith("serie:"):
            return normalize_nullable_text(value.split(":", 1)[1])

    return None


def infer_mime_type(media_link):

    link = (media_link or "").lower()

    if link.endswith(".mp3"):
        return "audio/mpeg"

    if link.endswith(".m4a"):
        return "audio/mp4"

    if link.endswith(".wav"):
        return "audio/wav"

    if link.endswith(".ogg"):
        return "audio/ogg"

    return ""


def run():

    files = glob.glob(FILES_GLOB)

    if not files:
        raise FileNotFoundError("Nenhum XML encontrado em data/bronze")

    input_xml = sorted(files)[-1]
    run_id = begin_processing_run(
        "wordpress_historic_bronze_to_silver",
        input_xml,
    )

    try:
        tree = ET.parse(input_xml)
        root = tree.getroot()
        payload_version = os.path.basename(input_xml)
        captured_at = utc_now_iso()
        processed_at = utc_now_iso()
        source_records = []
        metadata_records = []
        media_records = []

        for item in root.findall("./channel/item"):
            title = item.findtext("title", "")
            content = item.findtext("content:encoded", "", NS)
            post_date = normalize_date(
                item.findtext("wp:post_date", "", NS)
            )

            if post_date and post_date > MAX_DATE:
                continue

            source_link = item.findtext("link", "") or ""
            source_item_id = source_link or title or post_date
            preacher_name = extract_preacher(content)
            text_reference = extract_text(title, content)
            clean_title = extract_title(title)
            media_link = extract_mp3(content)
            file_date, file_preacher = extract_file_info(media_link)
            body_date = extract_body_date(title)

            tags = []
            categories = []

            for category in item.findall("category"):
                domain = category.attrib.get("domain")
                name = (category.text or "").strip()

                if domain == "post_tag":
                    tags.append(name)

                if domain == "category":
                    categories.append(name)

            normalized_categories = [
                normalize_text(category)
                for category in categories
            ]

            if "pregacoes" not in normalized_categories:
                continue

            source_records.append({
                "source_system": "wordpress",
                "source_item_id": source_item_id,
                "ingestion_run_id": run_id,
                "payload_version": payload_version,
                "raw_path": input_xml,
                "captured_at": captured_at,
            })

            preaching_date = choose_preaching_date(
                post_date,
                body_date,
                file_date,
            )

            if not preaching_date:
                continue

            metadata_records.append({
                "canonical_sermon_id": preaching_date,
                "source_system": "wordpress",
                "source_item_id": source_item_id,
                "preaching_date": preaching_date,
                "title": clean_title,
                "preacher_name": choose_preacher(file_preacher, preacher_name),
                "text_reference": text_reference,
                "serie": extract_serie(tags, categories),
                "confidence": 1.0,
                "processed_at": processed_at,
            })

            if media_link:
                media_records.append({
                    "canonical_sermon_id": preaching_date,
                    "asset_type": "audio",
                    "source_url": media_link,
                    "local_path": "",
                    "duration_seconds": None,
                    "mime_type": infer_mime_type(media_link),
                })

        with get_engine().begin() as conn:
            ensure_schema(conn)
            conn.execute(text(NORMALIZE_EMPTY_SERIE_SQL))

            if source_records:
                conn.execute(text(UPSERT_SOURCE_ITEM_SQL), source_records)

            if metadata_records:
                conn.execute(text(UPSERT_SERMON_METADATA_SQL), metadata_records)

            if media_records:
                conn.execute(text(UPSERT_MEDIA_ASSET_SQL), media_records)

        finish_processing_run(run_id, "success")
        print("WordPress metadata saved into silver tables")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

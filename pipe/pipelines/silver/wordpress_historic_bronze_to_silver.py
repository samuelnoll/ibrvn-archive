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
    serie = EXCLUDED.serie,
    confidence = EXCLUDED.confidence,
    processed_at = EXCLUDED.processed_at
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

ns = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "wp": "http://wordpress.org/export/1.2/",
    "dc": "http://purl.org/dc/elements/1.1/"
}

BIBLE_BOOKS = [
    "GÃªnesis", "ÃŠxodo", "LevÃ­tico", "NÃºmeros", "DeuteronÃ´mio",
    "JosuÃ©", "JuÃ­zes", "Rute", "1 Samuel", "2 Samuel", "1 Reis", "2 Reis",
    "1 CrÃ´nicas", "2 CrÃ´nicas", "Esdras", "Neemias", "Ester",
    "JÃ³", "Salmos", "ProvÃ©rbios", "Eclesiastes", "CÃ¢nticos",
    "IsaÃ­as", "Jeremias", "LamentaÃ§Ãµes", "Ezequiel", "Daniel",
    "OsÃ©ias", "Joel", "AmÃ³s", "Obadias", "Jonas", "Miqueias",
    "Naum", "Habacuque", "Sofonias", "Ageu", "Zacarias", "Malaquias",
    "Mateus", "Marcos", "Lucas", "JoÃ£o", "Atos",
    "Romanos", "1 CorÃ­ntios", "2 CorÃ­ntios", "GÃ¡latas", "EfÃ©sios",
    "Filipenses", "Colossenses", "1 Tessalonicenses", "2 Tessalonicenses",
    "1 TimÃ³teo", "2 TimÃ³teo", "Tito", "Filemon", "Hebreus",
    "Tiago", "1 Pedro", "2 Pedro", "1 JoÃ£o", "2 JoÃ£o", "3 JoÃ£o",
    "Judas", "Apocalipse"
]


def load_preacher_map():

    with open("pipe/config/preachers.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return {k.lower(): v for k, v in data.items()}


PREACHER_MAP = load_preacher_map()


def is_similar_book(a, b):

    if any(c.isdigit() for c in a + b):
        return False

    ratio = SequenceMatcher(None, a, b).ratio()

    return ratio >= 0.9


def normalize_date(date_str):

    if not date_str:
        return ""

    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.date().isoformat()
    except Exception:
        return ""


def normalize_compare(text):

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    return text.lower()


def normalize_text(text_value):

    if not text_value:
        return ""

    normalized = unicodedata.normalize("NFKD", str(text_value))
    normalized = "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )

    return normalized.lower().strip()


def extract_text(title, content):

    if not title:
        return ""

    title = (
        title.replace("\u00A0", " ")
        .replace("â€“", "-")
        .strip()
    )

    title = re.sub(r"\bI\s+", "1 ", title)
    title = re.sub(r"\bII\s+", "2 ", title)
    title = re.sub(r"\bIII\s+", "3 ", title)
    title = re.sub(r"(\d+)\s*a\s*(\d+)", r"\1-\2", title)
    title = re.sub(r"(\d+)\s*e\s*(\d+)", r"\1-\2", title)

    title_norm = normalize_compare(title)
    words = title_norm.split()

    for book in BIBLE_BOOKS:
        book_norm = normalize_compare(book)
        pattern = r"\b" + re.escape(book_norm) + r"\b"
        match_book = re.search(pattern, title_norm)

        if not match_book:

            for word in words:
                if is_similar_book(word, book_norm):
                    match_book = True
                    break

        if match_book:
            start = title_norm.find(book_norm)

            if start == -1:
                start = title_norm.find(word)

            fragment = title[start + len(book):].strip()
            match_ref = re.search(r"(\d+)(?::\s*(\d+(?:-\d+)?))?", fragment)

            if match_ref:
                chapter = match_ref.group(1)
                verse = match_ref.group(2)

                if verse:
                    return f"{book} {chapter}:{verse}"

                return f"{book} {chapter}"

            return book

    return ""


def extract_mp3(content):

    if not content:
        return ""

    urls = re.findall(r'https?://[^"\'>]+', content)
    audio_ext = (".mp3", ".m4a", ".wav", ".ogg")

    for url in urls:
        clean_url = url.lower().strip()

        if clean_url.endswith(audio_ext):
            return url.strip()

    return ""


def extract_preacher(content):

    m = re.search(r"por ([A-Za-zÃ€-Ã¿\s]+)", content or "")
    return m.group(1).strip() if m else ""


def extract_file_info(mp3_url):

    if not mp3_url:
        return "", ""

    filename = os.path.basename(mp3_url)
    patterns = [
        r"(20\d{2})[_\-](\d{2})[_\-](\d{2})[_\-]([A-Za-zÃ€-Ã¿]+)",
        r"([A-Za-zÃ€-Ã¿]+)[_\-](\d{2})[_\-](\d{2})[_\-](\d{2})",
        r"([A-Za-zÃ€-Ã¿]+)[\s\-](\d{2})\.(\d{2})\.(\d{4})",
        r"([A-Za-zÃ€-Ã¿]+)[\s\-](\d{2})\-(\d{2})\-(\d{4})",
    ]

    for index, pattern in enumerate(patterns):
        m = re.search(pattern, filename)

        if not m:
            continue

        if index == 0:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4)

        if index == 1:
            return f"20{m.group(4)}-{m.group(3)}-{m.group(2)}", m.group(1)

        return f"{m.group(4)}-{m.group(3)}-{m.group(2)}", m.group(1)

    return "", ""


def extract_body_date(title):

    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", title or "")

    if not m:
        return ""

    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def extract_title(title):

    if not title:
        return ""

    title = title.replace("\u00A0", " ").replace("â€“", "-").strip()

    if " - " not in title:
        return ""

    first = title.rsplit(" - ", 1)[0].strip()

    if first.lower().startswith("pregaÃ§Ã£o"):
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

    combined = (tags or "") + ";" + (categories or "")
    match = re.search(r"S[ÃƒÂ©e]rie:\s*([^;]+)", combined)

    if match:
        return match.group(1).strip()

    return ""


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
            content = item.findtext("content:encoded", "", ns)
            post_date = normalize_date(
                item.findtext("wp:post_date", "", ns)
            )

            if post_date and post_date > MAX_DATE:
                continue

            source_link = item.findtext("link", "") or ""
            source_item_id = source_link or title or post_date
            poster_name = item.findtext("dc:creator", "")
            preacher_name = extract_preacher(content)
            text_reference = extract_text(title, content)
            clean_title = extract_title(title)
            media_link = extract_mp3(content)
            file_date, file_preacher = extract_file_info(media_link)
            body_date = extract_body_date(title)

            tags = []
            categories = []

            for cat in item.findall("category"):
                domain = cat.attrib.get("domain")
                name = (cat.text or "").strip()

                if domain == "post_tag":
                    tags.append(name)

                if domain == "category":
                    categories.append(name)

            categories_lower = [category.lower() for category in categories]

            if "pregaÃ§Ãµes" not in categories_lower:
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
                "serie": extract_serie(";".join(tags), ";".join(categories)),
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

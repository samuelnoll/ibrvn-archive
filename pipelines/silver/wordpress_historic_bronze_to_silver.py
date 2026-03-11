import xml.etree.ElementTree as ET
import csv
import re
import os
from datetime import datetime

INPUT_XML = "data/bronze/ibrvn.WordPress.2026-03-09.xml"
OUTPUT_CSV = "data/silver/wordpress_sermons.csv"

ns = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "wp": "http://wordpress.org/export/1.2/",
    "dc": "http://purl.org/dc/elements/1.1/"
}


def normalize_date(date_str):

    if not date_str:
        return ""

    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.date().isoformat()
    except:
        return ""

def extract_preacher(content):

    m = re.search(r"por ([A-Za-zÀ-ÿ\s]+)", content or "")
    return m.group(1).strip() if m else ""


def extract_text(title, content):

    if not title:
        return "", "", "", ""

    # normalizar espaços estranhos
    title = title.replace("\u00A0", " ").replace("–", "-")

    # dividir pelo hífen
    parts = title.split("-")

    # pegar a segunda parte se houver
    if len(parts) < 2:
        return parts[0].strip()
    else:
        reference = parts[1].strip()

    # regex apenas para separar livro/capítulo/versos
    m = re.search(r'(.+?)\s+(\d+):([\d\-]+)', reference)

    if not m:
        return reference, "", "", ""

    book = m.group(1).strip()
    chapter = m.group(2)
    verses = m.group(3)

    return reference, book, chapter, verses

def extract_mp3(content):

    if not content:
        return ""

    # pegar todas as URLs
    urls = re.findall(r'https?://[^\s"\']+', content)

    # filtrar apenas arquivos de áudio
    audio_ext = (".mp3", ".m4a", ".wav", ".ogg")

    for url in urls:
        if url.lower().endswith(audio_ext):
            return url

    return ""


def extract_youtube(content):

    if not content:
        return ""

    m = re.search(r'https?://(www\.)?(youtube\.com|youtu\.be)[^\s"]+', content)
    if m:
        return m.group(0)

    return ""


def extract_file_info(mp3_url):

    if not mp3_url:
        return "", ""

    filename = os.path.basename(mp3_url)

    # YYYY_MM_DD_PREGADOR
    m = re.search(r'(20\d{2})[_\-](\d{2})[_\-](\d{2})[_\-]([A-Za-zÀ-ÿ]+)', filename)

    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        preacher = m.group(4)
        return date, preacher


    # PREGADOR_DD_MM_YY
    m = re.search(r'([A-Za-zÀ-ÿ]+)[_\-](\d{2})[_\-](\d{2})[_\-](\d{2})', filename)

    if m:
        preacher = m.group(1)
        date = f"20{m.group(4)}-{m.group(3)}-{m.group(2)}"
        return date, preacher


    # NOME DD.MM.YYYY
    m = re.search(r'([A-Za-zÀ-ÿ]+)[\s\-](\d{2})\.(\d{2})\.(\d{4})', filename)

    if m:
        preacher = m.group(1)
        date = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
        return date, preacher


    # NOME DD-MM-YYYY
    m = re.search(r'([A-Za-zÀ-ÿ]+)[\s\-](\d{2})\-(\d{2})\-(\d{4})', filename)

    if m:
        preacher = m.group(1)
        date = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
        return date, preacher


    return "", ""


def extract_body_date(title):

    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', title or "")

    if not m:
        return ""

    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def run():

    tree = ET.parse(INPUT_XML)
    root = tree.getroot()

    rows = []

    for item in root.findall("./channel/item"):

        title = item.findtext("title", "")
        content = item.findtext("content:encoded", "", ns)

        post_date = normalize_date(
            item.findtext("wp:post_date", "", ns)
        )

        poster_name = item.findtext("dc:creator", "")

        preacher_name = extract_preacher(content)

        text, book, chapter, verses = extract_text(title, content)

        file_path = extract_mp3(content)
        youtube = extract_youtube(content)

        file_date, file_preacher = extract_file_info(file_path)

        body_date = extract_body_date(title)

        tags = []
        categories = []

        for cat in item.findall("category"):

            domain = cat.attrib.get("domain")
            name = cat.text or ""

            if domain == "post_tag":
                tags.append(name)

            if domain == "category":
                categories.append(name)

        rows.append({

            "post_date": post_date,
            "body_date": body_date,
            "file_preaching_date": file_date,
            "preacher_name": preacher_name,
            "poster_name": poster_name,
            "file_preacher_name": file_preacher,
            "text_reference": text,
            "text_book": book,
            "text_chapter": chapter,
            "text_verses": verses,
            "file_path": file_path,
            "youtube_link": youtube,
            "tags": ";".join(tags),
            "categories": ";".join(categories)
        })

    os.makedirs("data/silver", exist_ok=True)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "post_date",
                "body_date",
                "file_preaching_date",
                "preacher_name",
                "poster_name",
                "file_preacher_name",
                "text_reference",
                "text_book",
                "text_chapter",
                "text_verses",
                "file_path",
                "youtube_link",
                "tags",
                "categories"
            ]
        )

        writer.writeheader()
        writer.writerows(rows)

    print("Silver dataset generated")


if __name__ == "__main__":
    run()

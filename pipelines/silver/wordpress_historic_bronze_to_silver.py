import xml.etree.ElementTree as ET
import csv
import re
import os
import unicodedata
from datetime import datetime

INPUT_XML = "data/bronze/ibrvn.WordPress.2026-03-09.xml"
OUTPUT_CSV = "data/silver/wordpress_sermons.csv"

MAX_DATE = "2021-12-31"

ns = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "wp": "http://wordpress.org/export/1.2/",
    "dc": "http://purl.org/dc/elements/1.1/"
}

BIBLE_BOOKS = [
    "Gênesis","Êxodo","Levítico","Números","Deuteronômio",
    "Josué","Juízes","Rute","1 Samuel","2 Samuel","1 Reis","2 Reis",
    "1 Crônicas","2 Crônicas","Esdras","Neemias","Ester",
    "Jó","Salmos","Provérbios","Eclesiastes","Cânticos",
    "Isaías","Jeremias","Lamentações","Ezequiel","Daniel",
    "Oséias","Joel","Amós","Obadias","Jonas","Miqueias",
    "Naum","Habacuque","Sofonias","Ageu","Zacarias","Malaquias",
    "Mateus","Marcos","Lucas","João","Atos",
    "Romanos","1 Coríntios","2 Coríntios","Gálatas","Efésios",
    "Filipenses","Colossenses","1 Tessalonicenses","2 Tessalonicenses",
    "1 Timóteo","2 Timóteo","Tito","Filemon","Hebreus",
    "Tiago","1 Pedro","2 Pedro","1 João","2 João","3 João",
    "Judas","Apocalipse"
]


def normalize_date(date_str):

    if not date_str:
        return ""

    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.date().isoformat()
    except:
        return ""


def normalize_compare(text):

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    return text.lower()


def extract_text(title, content):

    if not title:
        return ""

    title = (
        title.replace("\u00A0", " ")
        .replace("–", "-")
        .strip()
    )

    # normalizar numerais romanos
    title = re.sub(r'\bI\s+', '1 ', title)
    title = re.sub(r'\bII\s+', '2 ', title)
    title = re.sub(r'\bIII\s+', '3 ', title)

    # normalizar intervalos
    title = re.sub(r'(\d+)\s*a\s*(\d+)', r'\1-\2', title)
    title = re.sub(r'(\d+)\s*e\s*(\d+)', r'\1-\2', title)

    title_norm = normalize_compare(title)

    for book in BIBLE_BOOKS:

        book_norm = normalize_compare(book)

        pattern = r'\b' + re.escape(book_norm) + r'\b'

        m_book = re.search(pattern, title_norm)

        if m_book:

            start = m_book.start()

            fragment = title[start:]

            # procurar capítulo e versículos após o livro
            m = re.search(r'(\d+)(?::\s*(\d+(?:-\d+)?))?', fragment)

            if m:

                chapter = m.group(1)
                verse = m.group(2)

                if verse:
                    return f"{book} {chapter}:{verse}"

                return f"{book} {chapter}"

            return book

    return ""


def extract_mp3(content):

    if not content:
        return ""

    urls = re.findall(r'https?://[^\s"\']+', content)

    audio_ext = (".mp3", ".m4a", ".wav", ".ogg")

    for url in urls:
        clean_url = url.lower().strip()
        if clean_url.endswith(audio_ext):
            return url

    return ""
    

def extract_preacher(content):

    m = re.search(r"por ([A-Za-zÀ-ÿ\s]+)", content or "")
    return m.group(1).strip() if m else ""


def extract_file_info(mp3_url):

    if not mp3_url:
        return "", ""

    filename = os.path.basename(mp3_url)

    m = re.search(r'(20\d{2})[_\-](\d{2})[_\-](\d{2})[_\-]([A-Za-zÀ-ÿ]+)', filename)

    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        preacher = m.group(4)
        return date, preacher

    m = re.search(r'([A-Za-zÀ-ÿ]+)[_\-](\d{2})[_\-](\d{2})[_\-](\d{2})', filename)

    if m:
        preacher = m.group(1)
        date = f"20{m.group(4)}-{m.group(3)}-{m.group(2)}"
        return date, preacher

    m = re.search(r'([A-Za-zÀ-ÿ]+)[\s\-](\d{2})\.(\d{2})\.(\d{4})', filename)

    if m:
        preacher = m.group(1)
        date = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
        return date, preacher

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

        if post_date and post_date > MAX_DATE:
            continue

        source_link = item.findtext("link", "")

        poster_name = item.findtext("dc:creator", "")

        preacher_name = extract_preacher(content)

        text = extract_text(title, content)

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

        categories_lower = [c.lower() for c in categories]

        if "pregações" not in categories_lower:
            continue

        rows.append({

            "post_date": post_date,
            "body_date": body_date,
            "file_preaching_date": file_date,
            "preacher_name": preacher_name,
            "poster_name": poster_name,
            "file_preacher_name": file_preacher,
            "text_reference": text,
            "source_link": source_link,
            "media_link": media_link,
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
                "source_link",
                "media_link",
                "tags",
                "categories"
            ]
        )

        writer.writeheader()
        writer.writerows(rows)

    print("Silver dataset generated")


if __name__ == "__main__":
    run()

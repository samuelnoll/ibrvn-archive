import xml.etree.ElementTree as ET
import csv
import re
import os
from datetime import datetime

INPUT_XML = "data/bronze/ibrvn.WordPress.2026-03-09.xml"
OUTPUT_CSV = "data/silver/wordpress_sermons.csv"

MAX_DATE = "2021-12-31"

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


BIBLE_BOOK_ALIASES = {
    "Gênesis": ["gen", "gn"],
    "Êxodo": ["ex", "exo"],
    "Levítico": ["lv"],
    "Números": ["nm"],
    "Deuteronômio": ["dt"],
    "Josué": ["js"],
    "Juízes": ["jz"],
    "Rute": ["rt"],

    "1 Samuel": [
        "1sm", "1 samuel", "i samuel", "primeiro samuel", "primeira samuel"
    ],

    "2 Samuel": [
        "2sm", "2 samuel", "ii samuel", "segundo samuel", "segunda samuel"
    ],

    "1 Reis": [
        "1rs", "1 reis", "i reis", "primeiro reis", "primeira reis"
    ],

    "2 Reis": [
        "2rs", "2 reis", "ii reis", "segundo reis", "segunda reis"
    ],

    "Salmos": ["sl", "salmo"],
    "Provérbios": ["pv"],
    "Eclesiastes": ["ec"],
    "Cânticos": ["ct"],
    "Isaías": ["is"],
    "Jeremias": ["jr"],
    "Ezequiel": ["ez"],
    "Daniel": ["dn"],
    "Oséias": ["os"],
    "Joel": [],
    "Amós": [],
    "Jonas": [],
    "Miqueias": ["mq"],
    "Naum": [],
    "Habacuque": ["hc"],
    "Sofonias": [],
    "Ageu": [],
    "Zacarias": ["zc"],
    "Malaquias": ["ml"],

    "Mateus": ["mt"],
    "Marcos": ["mc"],
    "Lucas": ["lc"],
    "João": ["jo"],

    "Atos": ["at"],

    "Romanos": ["rm"],

    "1 Coríntios": [
        "1co", "1 cor", "1 corintios",
        "i corintios",
        "primeiro corintios", "primeira corintios"
    ],

    "2 Coríntios": [
        "2co", "2 cor", "2 corintios",
        "ii corintios",
        "segundo corintios", "segunda corintios"
    ],

    "Gálatas": ["gl"],
    "Efésios": ["ef"],
    "Filipenses": ["fp"],
    "Colossenses": ["cl"],

    "1 Tessalonicenses": [
        "1ts", "1 tessalonicenses",
        "i tessalonicenses",
        "primeiro tessalonicenses", "primeira tessalonicenses"
    ],

    "2 Tessalonicenses": [
        "2ts", "2 tessalonicenses",
        "ii tessalonicenses",
        "segundo tessalonicenses", "segunda tessalonicenses"
    ],

    "1 Timóteo": [
        "1tm", "1 timoteo",
        "i timoteo",
        "primeiro timoteo", "primeira timoteo"
    ],

    "2 Timóteo": [
        "2tm", "2 timoteo",
        "ii timoteo",
        "segundo timoteo", "segunda timoteo"
    ],

    "Tito": ["tt"],
    "Filemon": ["fm"],

    "Hebreus": ["hb"],
    "Tiago": ["tg"],

    "1 Pedro": [
        "1pe", "1 pedro",
        "i pedro",
        "primeiro pedro", "primeira pedro"
    ],

    "2 Pedro": [
        "2pe", "2 pedro",
        "ii pedro",
        "segundo pedro", "segunda pedro"
    ],

    "1 João": [
        "1jo", "1 joao",
        "i joao",
        "primeiro joao", "primeira joao"
    ],

    "2 João": [
        "2jo", "2 joao",
        "ii joao",
        "segundo joao", "segunda joao"
    ],

    "3 João": [
        "3jo", "3 joao",
        "iii joao",
        "terceiro joao", "terceira joao"
    ],

    "Judas": ["jd"],
    "Apocalipse": ["ap"]
}


def extract_text(title, content):

    if not title:
        return ""

    title = (
        title.replace("\u00A0", " ")
        .replace("–", "-")
        .strip()
    )

    title_lower = title.lower()

    for canonical, aliases in BIBLE_BOOK_ALIASES.items():

        candidates = [canonical.lower()] + aliases

        for candidate in candidates:

            if candidate in title_lower:

                start = title_lower.index(candidate)

                reference = title[start:]

                # normalizar nome do livro
                reference = canonical + reference[len(candidate):]

                # remover coisas irrelevantes
                reference = re.sub(
                    r'parte\s+\w+',
                    '',
                    reference,
                    flags=re.IGNORECASE
                )

                # normalizar intervalos
                reference = reference.replace(" a ", "-")

                reference = reference.strip()

                return reference

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

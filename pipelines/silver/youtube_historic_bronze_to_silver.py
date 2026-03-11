import json
import csv
import os
import re
from datetime import datetime

INPUT_JSON = "data/bronze/youtube_videos.json"
OUTPUT_CSV = "data/silver/youtube_sermons.csv"


def extract_date(description):

    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', description)

    if not m:
        return ""

    d = m.group(1)

    try:
        dt = datetime.strptime(d, "%d/%m/%Y")
        return dt.date().isoformat()
    except:
        return ""


def extract_preacher_description(description):

    m = re.search(
        r'Pregador\s*-\s*([^\n\r]+)',
        description
    )

    if m:
        return m.group(1).strip()

    return ""


def extract_preacher_title(title):

    parts = title.split("|")

    if len(parts) < 2:
        return ""

    last = parts[-1].strip()

    if len(last.split()) <= 3:
        return last

    return ""


def extract_title_clean(title):

    return title.split("|")[0].strip()


def extract_text_reference(title):

    parts = title.split("|")

    if len(parts) >= 2:
        return parts[1].strip()

    return ""


def extract_serie_and_preacher(playlists):

    serie = ""
    preacher_playlist = ""

    for p in playlists:

        if p.lower().startswith("série"):

            # extrair pregador dentro de []
            m = re.search(r'\[(.*?)\]', p)

            if m:
                preacher_playlist = m.group(1).strip()

            # remover "Série" e o conteúdo []
            s = re.sub(r'\[.*?\]', '', p)
            s = s.replace("Série", "").strip()

            serie = s

    return serie, preacher_playlist


def is_cult(description):

    return "culto" in description.lower()


def run():

    with open(INPUT_JSON, encoding="utf-8") as f:
        data = json.load(f)

    rows = []

    for v in data:

        description = v.get("description", "")

        if not is_cult(description):
            continue

        title = v.get("title", "")

        serie, preacher_playlist = extract_serie_and_preacher(
            v.get("playlists", [])
        )

        row = {

            "video_id": v["video_id"],

            "youtube_link": v["url"],

            "preaching_date": extract_date(description),

            "title": extract_title_clean(title),

            "text_reference": extract_text_reference(title),

            "preacher_title": extract_preacher_title(title),

            "preacher_description": extract_preacher_description(description),

            "preacher_playlist": preacher_playlist,

            "serie": serie
        }

        rows.append(row)

    os.makedirs("data/silver", exist_ok=True)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "video_id",
                "youtube_link",
                "preaching_date",
                "title",
                "text_reference",
                "preacher_title",
                "preacher_description",
                "preacher_playlist",
                "serie"
            ]
        )

        writer.writeheader()
        writer.writerows(rows)

    print("Silver dataset generated:", len(rows), "rows")


if __name__ == "__main__":
    run()

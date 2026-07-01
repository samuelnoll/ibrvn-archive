import json
import csv
import os
import re
import argparse
from datetime import datetime, timedelta

HISTORIC_INPUT = "data/bronze/youtube_videos.json"
WEEKLY_INPUT = "data/bronze/youtube_weekly_videos.json"

HISTORIC_OUTPUT = "data/silver/youtube_sermons.csv"
WEEKLY_OUTPUT = "data/silver/youtube_weekly_sermons.csv"


def convert_utc_to_brt(date_str):

    if not date_str:
        return ""

    try:
        dt = datetime.fromisoformat(
            date_str.replace("Z", "+00:00")
        )

        dt = dt - timedelta(hours=3)

        return dt.date().isoformat()

    except:
        return ""


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

            m = re.search(r'\[(.*?)\]', p)

            if m:
                preacher_playlist = m.group(1).strip()

            s = re.sub(r'\[.*?\]', '', p)
            s = s.replace("Série", "").strip()

            serie = s

    return serie, preacher_playlist


def choose_preaching_date(video, description):

    date = extract_date(description)

    if date:
        return date

    live_start = video.get("live_start_time")

    if live_start:
        return convert_utc_to_brt(live_start)

    return convert_utc_to_brt(video.get("published_at"))


def is_sermon(title):

    if not title:
        return False

    return title.count("|") >= 2


def run(mode):

    input_path = HISTORIC_INPUT if mode == "historic" else WEEKLY_INPUT
    output_path = HISTORIC_OUTPUT if mode == "historic" else WEEKLY_OUTPUT

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    rows = []

    for v in data:

        title = v.get("title", "")

        if not is_sermon(title):
            continue

        description = v.get("description", "")

        serie, preacher_playlist = extract_serie_and_preacher(
            v.get("playlists", [])
        )

        row = {

            "video_id": v["video_id"],

            "youtube_link": v["url"],

            "preaching_date": choose_preaching_date(v, description),

            "title": extract_title_clean(title),

            "text_reference": extract_text_reference(title),

            "preacher_title": extract_preacher_title(title),

            "preacher_description": extract_preacher_description(description),

            "preacher_playlist": preacher_playlist,

            "serie": serie
        }

        rows.append(row)

    os.makedirs("data/silver", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:

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

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["historic", "weekly"],
        default="historic"
    )

    args = parser.parse_args()

    run(args.mode)

import argparse
import json
import re
from datetime import datetime, timedelta

import yaml
from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    finish_processing_run,
    get_engine,
    utc_now_iso,
)


HISTORIC_INPUT = "data/bronze/youtube_videos.json"
WEEKLY_INPUT = "data/bronze/youtube_weekly_videos.json"

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


def load_preacher_map():

    with open("pipe/config/preachers.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return {k.lower(): v for k, v in data.items()}


PREACHER_MAP = load_preacher_map()


def normalize_text(text_value):

    if not text_value:
        return ""

    normalized = str(text_value)

    return normalized.lower().strip()


def convert_utc_to_brt(date_str):

    if not date_str:
        return ""

    try:
        dt = datetime.fromisoformat(
            date_str.replace("Z", "+00:00")
        )

        dt = dt - timedelta(hours=3)

        return dt.date().isoformat()

    except Exception:
        return ""


def extract_date(description):

    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", description)

    if not m:
        return ""

    d = m.group(1)

    try:
        dt = datetime.strptime(d, "%d/%m/%Y")
        return dt.date().isoformat()
    except Exception:
        return ""


def extract_preacher_description(description):

    m = re.search(
        r"Pregador\s*-\s*([^\n\r]+)",
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

    for playlist_title in playlists:

        normalized_title = normalize_text(playlist_title)

        if not normalized_title.startswith("serie"):
            continue

        m = re.search(r"\[(.*?)\]", playlist_title)

        if m:
            preacher_playlist = m.group(1).strip()

        cleaned = re.sub(r"\[.*?\]", "", playlist_title).strip()
        cleaned = re.sub(r"^\s*s[ée]rie\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)

        serie = cleaned.strip()

    return serie, preacher_playlist


def choose_preaching_date(video, description):

    extracted = extract_date(description)

    if extracted:
        return extracted

    live_start = video.get("live_start_time")

    if live_start:
        return convert_utc_to_brt(live_start)

    return convert_utc_to_brt(video.get("published_at"))


def choose_preacher(preacher_playlist, preacher_title, preacher_description):

    preacher = (
        preacher_playlist
        or preacher_title
        or preacher_description
    )

    if not preacher:
        return ""

    key = normalize_text(preacher)

    if key in PREACHER_MAP:
        return PREACHER_MAP[key]

    return preacher.title()


def is_sermon(title):

    if not title:
        return False

    return title.count("|") >= 2


def run(mode):

    input_path = HISTORIC_INPUT if mode == "historic" else WEEKLY_INPUT
    pipeline_name = f"youtube_bronze_to_silver:{mode}"
    run_id = begin_processing_run(pipeline_name, input_path)

    try:
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)

        captured_at = utc_now_iso()
        processed_at = utc_now_iso()
        source_records = []
        metadata_records = []
        media_records = []

        for video in data:
            video_id = video.get("video_id", "")

            if not video_id:
                continue

            source_records.append({
                "source_system": "youtube",
                "source_item_id": video_id,
                "ingestion_run_id": run_id,
                "payload_version": mode,
                "raw_path": input_path,
                "captured_at": captured_at,
            })

            title = video.get("title", "")

            if not is_sermon(title):
                continue

            description = video.get("description", "")
            serie, preacher_playlist = extract_serie_and_preacher(
                video.get("playlists", [])
            )

            preaching_date = choose_preaching_date(video, description)

            if not preaching_date:
                continue

            preacher_title = extract_preacher_title(title)
            preacher_description = extract_preacher_description(description)
            preacher_name = choose_preacher(
                preacher_playlist,
                preacher_title,
                preacher_description,
            )

            metadata_records.append({
                "canonical_sermon_id": preaching_date,
                "source_system": "youtube",
                "source_item_id": video_id,
                "preaching_date": preaching_date,
                "title": extract_title_clean(title),
                "preacher_name": preacher_name,
                "text_reference": extract_text_reference(title),
                "serie": serie,
                "confidence": 1.0,
                "processed_at": processed_at,
            })

            media_records.append({
                "canonical_sermon_id": preaching_date,
                "asset_type": "youtube_video",
                "source_url": video.get("url", ""),
                "local_path": "",
                "duration_seconds": None,
                "mime_type": "video/youtube",
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
        print("YouTube metadata saved into silver tables")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["historic", "weekly"],
        default="historic"
    )

    args = parser.parse_args()

    run(args.mode)

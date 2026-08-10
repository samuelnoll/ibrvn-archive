import argparse
import json
import re
import unicodedata
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
    serie = COALESCE(
        NULLIF(TRIM(EXCLUDED.serie), ''),
        NULLIF(TRIM(silver_sermon_metadata.serie), '')
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


def normalize_nullable_text(text_value):

    normalized = str(text_value or "").strip()

    return normalized or None


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

    serie = None
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

        serie = normalize_nullable_text(cleaned)

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


def extract_serie_and_preacher(playlists):

    serie = None
    preacher_playlist = ""

    for playlist_title in playlists:

        normalized_title = normalize_text(playlist_title)

        if not (
            normalized_title.startswith("serie")
            or normalized_title.startswith("minisserie")
        ):
            continue

        m = re.search(r"\[(.*?)\]", playlist_title)

        if m:
            preacher_playlist = m.group(1).strip()

        cleaned = re.sub(r"\[.*?\]", "", playlist_title).strip()
        cleaned = re.sub(
            r"^\s*(?:mini)?s(?:e|é)rie\s*[:\-]?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        serie = normalize_nullable_text(cleaned)

    return serie, preacher_playlist


def is_sermon(title):

    if not title:
        return False

    return title.count("|") >= 2


def parse_published_at(date_str):

    if not date_str:
        return None

    try:
        return datetime.fromisoformat(
            str(date_str).replace("Z", "+00:00")
        )
    except Exception:
        return None


def sermon_candidate_sort_key(candidate):

    video = candidate["video"]
    published_at = parse_published_at(video.get("published_at"))
    duration = str(video.get("duration", "") or "").strip()

    return (
        published_at or datetime.min,
        1 if duration and duration != "P0D" else 0,
        1 if bool(video.get("playlists")) else 0,
        str(video.get("video_id", "") or ""),
    )


def choose_best_sermon_candidate(candidates):

    return max(candidates, key=sermon_candidate_sort_key)


def coalesce_metadata_from_candidates(selected_candidate, candidates):

    metadata = dict(selected_candidate["metadata"])

    for field in ("title", "preacher_name", "text_reference", "serie"):
        if metadata.get(field):
            continue

        for candidate in candidates:
            value = candidate["metadata"].get(field)

            if value:
                metadata[field] = value
                break

    return metadata


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
        sermon_candidates_by_date = {}

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

            metadata_record = {
                "canonical_sermon_id": preaching_date,
                "source_system": "youtube",
                "source_item_id": video_id,
                "preaching_date": preaching_date,
                "title": extract_title_clean(title),
                "preacher_name": preacher_name,
                "text_reference": extract_text_reference(title),
                "serie": normalize_nullable_text(serie),
                "confidence": 1.0,
                "processed_at": processed_at,
            }

            media_record = {
                "canonical_sermon_id": preaching_date,
                "asset_type": "youtube_video",
                "source_url": video.get("url", ""),
                "local_path": "",
                "duration_seconds": None,
                "mime_type": "video/youtube",
            }

            sermon_candidates_by_date.setdefault(preaching_date, []).append({
                "video": video,
                "metadata": metadata_record,
                "media": media_record,
            })

        metadata_records = []
        media_records = []

        for preaching_date, candidates in sermon_candidates_by_date.items():
            selected_candidate = choose_best_sermon_candidate(candidates)
            selected_metadata = coalesce_metadata_from_candidates(
                selected_candidate,
                candidates,
            )

            metadata_records.append(selected_metadata)
            media_records.append(dict(selected_candidate["media"]))

            if len(candidates) > 1:
                selected_video = selected_candidate["video"]
                discarded_video_ids = [
                    candidate["video"].get("video_id", "")
                    for candidate in candidates
                    if candidate["video"].get("video_id", "") != selected_video.get("video_id", "")
                ]
                print(
                    "Resolved duplicate sermon videos for "
                    f"{preaching_date}: kept video_id={selected_video.get('video_id', '')} "
                    f"(published_at={selected_video.get('published_at', '')}, "
                    f"live_start_time={selected_video.get('live_start_time', '')}) "
                    f"and skipped {discarded_video_ids}"
                )

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

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from shared.db import get_engine, utc_now_iso
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)


DEFAULT_INPUT = Path("data/bronze/studies/youtube_studies.json")
LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
VALID_STUDY_TYPES = {
    "ctb",
    "lecture_or_conference",
    "pfd",
    "weekly",
}

UPSERT_STUDY_SQL = """
INSERT INTO silver_study_youtube (
    study_key,
    youtube_video_id,
    study_type,
    title,
    study_date,
    source_url,
    collection_title,
    playlist_ids,
    payload_version,
    processed_at
)
VALUES (
    :study_key,
    :youtube_video_id,
    :study_type,
    :title,
    :study_date,
    :source_url,
    :collection_title,
    :playlist_ids,
    :payload_version,
    :processed_at
)
ON CONFLICT(study_key) DO UPDATE SET
    youtube_video_id = EXCLUDED.youtube_video_id,
    study_type = EXCLUDED.study_type,
    title = EXCLUDED.title,
    study_date = EXCLUDED.study_date,
    source_url = EXCLUDED.source_url,
    collection_title = EXCLUDED.collection_title,
    playlist_ids = EXCLUDED.playlist_ids,
    payload_version = EXCLUDED.payload_version,
    processed_at = EXCLUDED.processed_at
"""

UPSERT_RESOURCE_SQL = """
INSERT INTO silver_study_youtube_resources (
    resource_key,
    study_key,
    resource_type,
    label,
    source_url,
    canonical_url,
    mime_type,
    position,
    processed_at
)
VALUES (
    :resource_key,
    :study_key,
    :resource_type,
    :label,
    :source_url,
    :canonical_url,
    :mime_type,
    :position,
    :processed_at
)
ON CONFLICT(resource_key) DO UPDATE SET
    study_key = EXCLUDED.study_key,
    resource_type = EXCLUDED.resource_type,
    label = EXCLUDED.label,
    source_url = EXCLUDED.source_url,
    canonical_url = EXCLUDED.canonical_url,
    mime_type = EXCLUDED.mime_type,
    position = EXCLUDED.position,
    processed_at = EXCLUDED.processed_at
"""


def stable_key(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def study_date(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return timestamp.astimezone(LOCAL_TIMEZONE).date().isoformat()
    except (TypeError, ValueError):
        return ""


def run(input_path: Path = DEFAULT_INPUT) -> dict[str, int | bool]:
    run_id = begin_study_processing_run(
        "study_youtube_bronze_to_silver",
        str(input_path),
    )

    try:
        with input_path.open(encoding="utf-8") as file_handle:
            payload = json.load(file_handle)

        if payload.get("schema_version") != 1:
            raise ValueError("Unsupported YouTube study bronze schema version")

        processed_at = utc_now_iso()
        payload_version = str(payload.get("captured_at") or processed_at)
        complete_snapshot = bool(payload.get("complete_snapshot"))
        study_rows = []
        resource_rows = []

        for video in payload.get("videos", []):
            video_id = str(video.get("video_id") or "").strip()

            if not video_id:
                continue

            playlists = video.get("playlists") or []
            playlist_titles = list(dict.fromkeys(
                str(item.get("playlist_title") or "").strip()
                for item in playlists
                if str(item.get("playlist_title") or "").strip()
            ))
            playlist_ids = list(dict.fromkeys(
                str(item.get("playlist_id") or "").strip()
                for item in playlists
                if str(item.get("playlist_id") or "").strip()
            ))
            resolved_study_type = str(video.get("study_type") or "weekly")

            if resolved_study_type not in VALID_STUDY_TYPES:
                resolved_study_type = "weekly"

            study_key = f"youtube:{video_id}"
            source_url = f"https://www.youtube.com/watch?v={video_id}"
            canonical_url = f"https://youtube.com/watch?v={video_id}"
            title = str(video.get("title") or "").strip() or f"Estudo {video_id}"
            study_rows.append({
                "study_key": study_key,
                "youtube_video_id": video_id,
                "study_type": resolved_study_type,
                "title": title,
                "study_date": study_date(video.get("published_at", "")) or None,
                "source_url": source_url,
                "collection_title": " | ".join(playlist_titles),
                "playlist_ids": json.dumps(playlist_ids, ensure_ascii=False),
                "payload_version": payload_version,
                "processed_at": processed_at,
            })
            resource_rows.append({
                "resource_key": stable_key(study_key, canonical_url),
                "study_key": study_key,
                "resource_type": "youtube",
                "label": title,
                "source_url": source_url,
                "canonical_url": canonical_url,
                "mime_type": "video/youtube",
                "position": 1,
                "processed_at": processed_at,
            })

        with get_engine().begin() as conn:
            ensure_study_schema(conn)

            if complete_snapshot:
                conn.execute(text("DELETE FROM silver_study_youtube_resources"))
                conn.execute(text("DELETE FROM silver_study_youtube"))
            elif study_rows:
                conn.execute(text("""
                    DELETE FROM silver_study_youtube_resources
                    WHERE study_key = :study_key
                """), [{"study_key": row["study_key"]} for row in study_rows])

            if study_rows:
                conn.execute(text(UPSERT_STUDY_SQL), study_rows)

            if resource_rows:
                conn.execute(text(UPSERT_RESOURCE_SQL), resource_rows)

        finish_study_processing_run(run_id, "success")
        result = {
            "studies": len(study_rows),
            "resources": len(resource_rows),
            "complete_snapshot": complete_snapshot,
        }
        print(f"YouTube studies saved to independent silver tables: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load the independent YouTube study bronze into silver."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.input)

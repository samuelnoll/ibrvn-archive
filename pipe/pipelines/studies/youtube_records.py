from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from pipe.pipelines.studies.title_rules import clean_study_title


LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
VALID_STUDY_TYPES = {
    "ctb",
    "lecture_or_conference",
    "pfd",
    "weekly",
}


def stable_key(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def study_date(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return timestamp.astimezone(LOCAL_TIMEZONE).date().isoformat()
    except (TypeError, ValueError):
        return ""


def playlist_study_date(playlist: dict) -> str:
    oldest_published_at = str(
        playlist.get("oldest_video_published_at") or ""
    ).strip()

    if oldest_published_at:
        resolved = study_date(oldest_published_at)

        if resolved:
            return resolved

    video_dates = sorted(
        resolved
        for video in playlist.get("videos", [])
        if (resolved := study_date(video.get("published_at", "")))
    )

    if video_dates:
        return video_dates[0]

    playlist_year = str(playlist.get("published_at") or "")[:4]
    return playlist_year if playlist_year.isdigit() else ""


def build_silver_records(
    payload: dict,
    processed_at: str,
) -> tuple[list[dict], list[dict]]:
    if payload.get("schema_version") != 2:
        raise ValueError(
            "Unsupported YouTube study bronze schema version; "
            "run ibrvn_study_youtube_bronze to generate schema v2."
        )

    payload_version = str(payload.get("captured_at") or processed_at)
    study_rows = []
    resource_rows = []

    for playlist in payload.get("playlists", []):
        playlist_id = str(playlist.get("playlist_id") or "").strip()

        if not playlist_id:
            continue

        resolved_study_type = str(playlist.get("study_type") or "weekly")

        if resolved_study_type not in VALID_STUDY_TYPES:
            resolved_study_type = "weekly"

        study_key = f"youtube:playlist:{playlist_id}"
        source_url = (
            str(playlist.get("url") or "").strip()
            or f"https://www.youtube.com/playlist?list={playlist_id}"
        )
        title = clean_study_title(
            str(playlist.get("title") or "").strip()
            or f"Estudo {playlist_id}"
        )
        study_rows.append({
            "study_key": study_key,
            "youtube_playlist_id": playlist_id,
            "study_type": resolved_study_type,
            "title": title,
            "study_date": playlist_study_date(playlist) or None,
            "source_url": source_url,
            "payload_version": payload_version,
            "processed_at": processed_at,
        })

        seen_video_ids = set()

        for fallback_position, video in enumerate(
            playlist.get("videos", []),
            start=1,
        ):
            video_id = str(video.get("video_id") or "").strip()

            if not video_id or video_id in seen_video_ids:
                continue

            seen_video_ids.add(video_id)
            canonical_url = f"https://youtube.com/watch?v={video_id}"
            video_url = (
                str(video.get("url") or "").strip()
                or f"https://www.youtube.com/watch?v={video_id}"
            )
            resource_rows.append({
                "resource_key": stable_key(study_key, canonical_url),
                "study_key": study_key,
                "resource_type": "youtube",
                "label": str(video.get("title") or "").strip() or video_id,
                "source_url": video_url,
                "canonical_url": canonical_url,
                "mime_type": "video/youtube",
                "position": int(video.get("position") or fallback_position),
                "processed_at": processed_at,
            })

    return study_rows, resource_rows

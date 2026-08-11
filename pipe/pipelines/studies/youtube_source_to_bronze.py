from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from pipe.pipelines.studies.youtube_rules import (
    infer_study_type,
    is_study_playlist,
    normalize_text,
)


CONFIG_PATH = Path("pipe/config/youtube.yaml")
DEFAULT_OUTPUT = Path("data/bronze/studies/youtube_studies.json")
API_BASE_URL = "https://www.googleapis.com/youtube/v3"
REQUEST_TIMEOUT_SECONDS = 30
MAX_API_ATTEMPTS = 4
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class YoutubeStudyApiError(RuntimeError):
    pass


def parse_api_error(payload: dict) -> tuple[str, str]:
    error = payload.get("error") if isinstance(payload, dict) else None

    if not isinstance(error, dict):
        return "unknown", "Unknown YouTube API error"

    errors = error.get("errors") or []
    first = errors[0] if errors and isinstance(errors[0], dict) else {}
    return (
        str(first.get("reason") or "unknown"),
        str(error.get("message") or first.get("message") or "Unknown error"),
    )


def youtube_get(api_key: str, endpoint: str, params: dict, operation: str) -> dict:
    request_params = {**params, "key": api_key}
    delay_seconds = 2
    last_error = ""

    for attempt in range(1, MAX_API_ATTEMPTS + 1):
        try:
            response = requests.get(
                f"{API_BASE_URL}/{endpoint}",
                params=request_params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = f"YouTube API request failed while {operation}: {exc}"
            should_retry = True
        else:
            if response.ok and "error" not in payload:
                return payload

            reason, message = parse_api_error(payload)
            last_error = (
                f"YouTube API failed while {operation} "
                f"(status={response.status_code}, reason={reason}): {message}"
            )
            should_retry = response.status_code in TRANSIENT_STATUS_CODES

        if attempt >= MAX_API_ATTEMPTS or not should_retry:
            raise YoutubeStudyApiError(last_error)

        print(f"{last_error}. Retrying in {delay_seconds}s...")
        time.sleep(delay_seconds)
        delay_seconds *= 2

    raise YoutubeStudyApiError(last_error)


def load_channel_id(config_path: Path = CONFIG_PATH) -> str:
    with config_path.open(encoding="utf-8") as file_handle:
        config = yaml.safe_load(file_handle) or {}

    channel_id = str(config.get("channel_id") or "").strip()

    if not channel_id:
        raise ValueError(f"Missing channel_id in {config_path}")

    return channel_id


def list_study_playlists(api_key: str, channel_id: str) -> list[dict]:
    playlists = []
    page_token = None

    while True:
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "maxResults": 50,
        }

        if page_token:
            params["pageToken"] = page_token

        payload = youtube_get(
            api_key,
            "playlists",
            params,
            f"listing playlists for channel {channel_id}",
        )

        for item in payload.get("items", []):
            title = item.get("snippet", {}).get("title", "")

            if is_study_playlist(title):
                playlists.append({
                    "playlist_id": item["id"],
                    "title": title,
                    "published_at": item.get("snippet", {}).get(
                        "publishedAt",
                        "",
                    ),
                    "url": (
                        "https://www.youtube.com/playlist?list="
                        f"{item['id']}"
                    ),
                })

        page_token = payload.get("nextPageToken")

        if not page_token:
            break

    return sorted(playlists, key=lambda value: normalize_text(value["title"]))


def list_playlist_memberships(
    api_key: str,
    playlist: dict,
) -> list[dict]:
    memberships = []
    page_token = None

    while True:
        params = {
            "part": "contentDetails",
            "playlistId": playlist["playlist_id"],
            "maxResults": 50,
        }

        if page_token:
            params["pageToken"] = page_token

        payload = youtube_get(
            api_key,
            "playlistItems",
            params,
            f"reading study playlist {playlist['title']!r}",
        )

        for item in payload.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId", "")

            if video_id:
                memberships.append({
                    "video_id": video_id,
                    "playlist_id": playlist["playlist_id"],
                    "playlist_title": playlist["title"],
                    "position": len(memberships) + 1,
                })

        page_token = payload.get("nextPageToken")

        if not page_token:
            break

    return memberships


def fetch_video_details(api_key: str, video_ids: list[str]) -> dict[str, dict]:
    videos = {}

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]
        payload = youtube_get(
            api_key,
            "videos",
            {
                "part": "snippet,contentDetails",
                "id": ",".join(batch),
                "maxResults": 50,
            },
            f"reading details for {len(batch)} study videos",
        )

        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            videos[item["id"]] = {
                "video_id": item["id"],
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "duration": item.get("contentDetails", {}).get("duration", ""),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
            }

    return videos


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def build_bronze_payload(
    api_key: str,
    channel_id: str,
    loopback_days: int | None,
) -> dict:
    playlists = list_study_playlists(api_key, channel_id)

    if not playlists:
        raise ValueError(
            "No supported YouTube study playlists were found; "
            "the existing study bronze was left unchanged."
        )

    memberships_by_playlist = {}
    video_ids = set()

    for playlist in playlists:
        print(f"Reading study playlist: {playlist['title']}")
        memberships = list_playlist_memberships(api_key, playlist)
        memberships_by_playlist[playlist["playlist_id"]] = memberships
        video_ids.update(item["video_id"] for item in memberships)

    details = fetch_video_details(api_key, sorted(video_ids))
    cutoff = None

    if loopback_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=loopback_days)

    study_playlists = []

    for playlist in playlists:
        videos = []
        all_published_dates = []

        for membership in memberships_by_playlist[playlist["playlist_id"]]:
            video = details.get(membership["video_id"])

            if not video:
                continue

            published_at = parse_timestamp(video.get("published_at", ""))

            if published_at:
                all_published_dates.append(published_at)

            if cutoff and (not published_at or published_at < cutoff):
                continue

            videos.append({
                **video,
                "position": membership["position"],
            })

        if cutoff and not videos:
            continue

        study_playlists.append({
            **playlist,
            "study_type": infer_study_type([playlist["title"]]),
            "oldest_video_published_at": (
                min(all_published_dates).isoformat()
                if all_published_dates
                else ""
            ),
            "videos": sorted(videos, key=lambda item: item["position"]),
        })

    return {
        "schema_version": 2,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "channel_id": channel_id,
        "loopback_days": loopback_days,
        "complete_snapshot": loopback_days is None,
        "playlist_prefixes": [
            "Estudo ",
            "CTB ",
            "Confer\u00eancia ",
            "Retiro ",
        ],
        "playlists": study_playlists,
    }


def write_json_atomic(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")

    with temporary_path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)

    os.replace(temporary_path, output_path)


def run(
    loopback_days: int | None = None,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict:
    if loopback_days is not None and loopback_days <= 0:
        raise ValueError("loopback_days must be a positive integer")

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()

    if not api_key:
        raise ValueError("YOUTUBE_API_KEY is required")

    channel_id = load_channel_id()
    payload = build_bronze_payload(api_key, channel_id, loopback_days)
    write_json_atomic(output_path, payload)
    result = {
        "playlists": len(payload["playlists"]),
        "videos": sum(
            len(playlist["videos"])
            for playlist in payload["playlists"]
        ),
        "complete_snapshot": payload["complete_snapshot"],
    }
    print(f"YouTube study bronze saved to {output_path}: {result}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract videos from supported YouTube study playlists into the "
            "independent study bronze."
        )
    )
    parser.add_argument("--loopback-days", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.loopback_days, arguments.output)

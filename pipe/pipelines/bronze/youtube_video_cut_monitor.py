import argparse
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from pipe.pipelines.bronze.youtube_source_to_bronze import (
    DEFAULT_CHANNEL_TIMEZONE,
    enrich_video_details,
    fetch_playlist_items_for_date,
    get_upload_playlist,
    load_channel,
)
from pipe.pipelines.silver.youtube_bronze_to_silver import (
    choose_best_sermon_candidate,
    is_sermon,
)


DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_published_at(value):

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_duration_seconds(duration_iso):

    if not duration_iso:
        return None

    match = DURATION_PATTERN.match(duration_iso)

    if not match:
        return None

    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)

    return seconds + (minutes * 60) + (hours * 3600) + (days * 86400)


def build_same_day_video_candidates(target_date, timezone_name):

    channel_id = load_channel()
    uploads_playlist = get_upload_playlist(channel_id)
    videos = fetch_playlist_items_for_date(
        uploads_playlist,
        target_date=target_date,
        timezone_name=timezone_name,
    )

    if not videos:
        return []

    details_map = enrich_video_details([video["video_id"] for video in videos])
    channel_timezone = ZoneInfo(timezone_name)
    candidates = []

    for video in videos:

        details = details_map.get(video["video_id"], {})
        duration_iso = details.get("duration", "")

        candidates.append({
            "video_id": video["video_id"],
            "title": video["title"],
            "published_at": video["published_at"],
            "published_at_local": parse_published_at(
                video["published_at"]
            ).astimezone(channel_timezone).isoformat(),
            "duration_iso": duration_iso,
            "duration_seconds": parse_duration_seconds(duration_iso),
            "url": video["url"],
        })

    return candidates


def same_day_candidate_sort_key(candidate):

    return (
        parse_published_at(candidate.get("published_at")) or datetime.min,
        str(candidate.get("video_id", "") or ""),
    )


def choose_latest_same_day_candidate(candidates):

    return max(candidates, key=same_day_candidate_sort_key)


def choose_latest_same_day_sermon_candidate(candidates):

    sermon_candidates = [
        {
            "video": candidate,
            "metadata": {},
            "media": {},
        }
        for candidate in candidates
        if is_sermon(candidate.get("title", ""))
    ]

    if not sermon_candidates:
        return None

    return choose_best_sermon_candidate(sermon_candidates)["video"]


def inspect_video_cut_candidate(target_date, timezone_name):

    candidates = build_same_day_video_candidates(target_date, timezone_name)

    if not candidates:
        return {
            "found_upload": False,
            "found_sermon": False,
            "target_date": target_date,
            "message": (
                "No YouTube uploads were found for the target local date yet."
            ),
        }

    latest_upload = choose_latest_same_day_candidate(candidates)
    latest_sermon = choose_latest_same_day_sermon_candidate(candidates)

    return {
        "found_upload": True,
        "found_sermon": latest_sermon is not None,
        "target_date": target_date,
        "candidate_count": len(candidates),
        "latest_upload": latest_upload,
        "latest_sermon": latest_sermon,
    }


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("--target-date", required=True)
    parser.add_argument(
        "--timezone",
        default=DEFAULT_CHANNEL_TIMEZONE,
    )

    args = parser.parse_args()

    result = inspect_video_cut_candidate(
        target_date=args.target_date,
        timezone_name=args.timezone,
    )

    print(json.dumps(result, ensure_ascii=False))

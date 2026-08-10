import os
import json
import time
import yaml
import requests
import argparse
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

API_KEY = os.environ["YOUTUBE_API_KEY"]

CONFIG_PATH = "pipe/config/youtube.yaml"

HISTORIC_OUTPUT = "data/bronze/youtube_videos.json"
WEEKLY_OUTPUT = "data/bronze/youtube_weekly_videos.json"
REQUEST_TIMEOUT_SECONDS = 30
MAX_API_ATTEMPTS = 4
INITIAL_RETRY_DELAY_SECONDS = 2
DEFAULT_CHANNEL_TIMEZONE = "America/Sao_Paulo"
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
TRANSIENT_ERROR_REASONS = {
    "backendError",
    "internalError",
    "rateLimitExceeded",
    "userRateLimitExceeded",
}


class YoutubeApiError(RuntimeError):
    pass


def extract_api_error(payload):

    error = payload.get("error")

    if not isinstance(error, dict):
        return None, None, None

    errors = error.get("errors") or []
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}

    return (
        error.get("code"),
        first_error.get("reason"),
        error.get("message") or first_error.get("message"),
    )


def is_transient_api_error(status_code, reason):

    return (
        status_code in TRANSIENT_STATUS_CODES
        or reason in TRANSIENT_ERROR_REASONS
    )


def youtube_api_get(url, params, operation, require_items=False):

    delay_seconds = INITIAL_RETRY_DELAY_SECONDS
    last_error = None

    for attempt in range(1, MAX_API_ATTEMPTS + 1):

        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            last_error = (
                f"YouTube API request failed during {operation}: {exc}"
            )
            should_retry = True
        except ValueError as exc:
            last_error = (
                f"YouTube API returned invalid JSON during {operation}: {exc}"
            )
            should_retry = True
        else:
            status_code, reason, message = extract_api_error(payload)

            if response.ok and "error" not in payload:

                if require_items and "items" not in payload:
                    last_error = (
                        f"YouTube API response during {operation} did not "
                        f"include 'items'. Response keys: "
                        f"{sorted(payload.keys())}"
                    )
                    should_retry = True
                else:
                    return payload
            else:
                effective_status = status_code or response.status_code
                reason_label = reason or "unknown"
                message_label = message or "Unknown YouTube API error"
                last_error = (
                    f"YouTube API error during {operation} "
                    f"(status={effective_status}, reason={reason_label}): "
                    f"{message_label}"
                )
                should_retry = is_transient_api_error(
                    effective_status,
                    reason,
                )

        if attempt >= MAX_API_ATTEMPTS or not should_retry:
            raise YoutubeApiError(last_error)

        print(
            f"{last_error}. Retrying in {delay_seconds}s "
            f"(attempt {attempt}/{MAX_API_ATTEMPTS})..."
        )
        time.sleep(delay_seconds)
        delay_seconds *= 2

    raise YoutubeApiError(last_error or "Unknown YouTube API failure")


def parse_published_at(value):

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_target_date(value):

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    return date.fromisoformat(str(value))


def load_channel():

    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    return cfg["channel_id"]


def get_upload_playlist(channel_id):

    url = "https://www.googleapis.com/youtube/v3/channels"

    params = {
        "part": "contentDetails",
        "id": channel_id,
        "key": API_KEY
    }

    r = youtube_api_get(
        url,
        params,
        operation=f"fetching upload playlist for channel_id={channel_id}",
        require_items=True,
    )

    if not r["items"]:
        raise YoutubeApiError(
            f"No YouTube channel found for channel_id={channel_id}"
        )

    return r["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_all_playlists(channel_id):

    url = "https://www.googleapis.com/youtube/v3/playlists"

    playlists = []
    next_page = None

    while True:

        params = {
            "part": "snippet",
            "channelId": channel_id,
            "maxResults": 50,
            "pageToken": next_page,
            "key": API_KEY
        }

        r = youtube_api_get(
            url,
            params,
            operation=(
                "listing playlists for "
                f"channel_id={channel_id}, page_token={next_page or '<first>'}"
            ),
            require_items=True,
        )

        for item in r["items"]:

            playlists.append({
                "playlist_id": item["id"],
                "title": item["snippet"]["title"]
            })

        next_page = r.get("nextPageToken")

        if not next_page:
            break

    return playlists


def fetch_playlist_items(playlist_id):

    url = "https://www.googleapis.com/youtube/v3/playlistItems"

    videos = []
    next_page = None

    while True:

        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
            "pageToken": next_page,
            "key": API_KEY
        }

        r = youtube_api_get(
            url,
            params,
            operation=(
                "listing playlist items for "
                f"playlist_id={playlist_id}, "
                f"page_token={next_page or '<first>'}"
            ),
            require_items=True,
        )

        for item in r["items"]:

            snippet = item["snippet"]

            videos.append({
                "video_id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "description": snippet["description"],
                "published_at": snippet["publishedAt"],
                "url": f"https://www.youtube.com/watch?v={snippet['resourceId']['videoId']}"
            })

        next_page = r.get("nextPageToken")

        if not next_page:
            break

    return videos


def fetch_playlist_items_for_date(
    playlist_id,
    target_date,
    timezone_name=DEFAULT_CHANNEL_TIMEZONE,
):

    url = "https://www.googleapis.com/youtube/v3/playlistItems"

    videos = []
    next_page = None
    target_local_date = normalize_target_date(target_date)
    channel_timezone = ZoneInfo(timezone_name)

    while True:

        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
            "pageToken": next_page,
            "key": API_KEY
        }

        r = youtube_api_get(
            url,
            params,
            operation=(
                "listing playlist items for "
                f"playlist_id={playlist_id}, "
                f"target_date={target_local_date.isoformat()}, "
                f"page_token={next_page or '<first>'}"
            ),
            require_items=True,
        )

        for item in r["items"]:

            snippet = item["snippet"]
            published_at = parse_published_at(snippet["publishedAt"])
            published_local_date = published_at.astimezone(
                channel_timezone
            ).date()

            if published_local_date > target_local_date:
                continue

            if published_local_date < target_local_date:
                return videos

            videos.append({
                "video_id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "description": snippet["description"],
                "published_at": snippet["publishedAt"],
                "url": (
                    "https://www.youtube.com/watch?v="
                    f"{snippet['resourceId']['videoId']}"
                )
            })

        next_page = r.get("nextPageToken")

        if not next_page:
            break

    return videos


def enrich_video_details(video_ids):

    url = "https://www.googleapis.com/youtube/v3/videos"

    enriched = {}

    for i in range(0, len(video_ids), 50):

        batch = video_ids[i:i+50]

        params = {
            "part": "liveStreamingDetails,contentDetails,statistics",
            "id": ",".join(batch),
            "key": API_KEY
        }

        r = youtube_api_get(
            url,
            params,
            operation=(
                "fetching video details for "
                f"video_batch_start={i}, batch_size={len(batch)}"
            ),
        )

        for item in r.get("items", []):

            vid = item["id"]

            live_details = item.get("liveStreamingDetails", {})

            enriched[vid] = {
                "is_live": bool(live_details),
                "live_start_time": live_details.get("actualStartTime", ""),
                "duration": item.get("contentDetails", {}).get("duration", ""),
                "view_count": item.get("statistics", {}).get("viewCount", "")
            }

    return enriched


def filter_recent_videos(videos, days):

    cutoff = datetime.utcnow() - timedelta(days=days)

    filtered = []

    for v in videos:

        try:

            published = datetime.fromisoformat(
                v["published_at"].replace("Z", "+00:00")
            )

            if published.replace(tzinfo=None) >= cutoff:
                filtered.append(v)

        except:
            pass

    return filtered


def run(mode, loopback_days=None):

    channel_id = load_channel()

    uploads_playlist = get_upload_playlist(channel_id)

    print("Downloading uploads playlist...")

    videos = fetch_playlist_items(uploads_playlist)

    if loopback_days:

        print(f"Filtering last {loopback_days} days videos...")

        videos = filter_recent_videos(videos, days=int(loopback_days))

    video_map = {v["video_id"]: v for v in videos}

    for v in video_map.values():
        v["playlists"] = []

    print("Downloading video details...")

    details_map = enrich_video_details(list(video_map.keys()))

    for vid, details in details_map.items():

        if vid in video_map:

            video_map[vid]["is_live"] = details["is_live"]
            video_map[vid]["live_start_time"] = details["live_start_time"]
            video_map[vid]["duration"] = details["duration"]
            video_map[vid]["view_count"] = details["view_count"]

    print("Downloading playlists...")

    playlists = get_all_playlists(channel_id)

    for playlist in playlists:

        print("Scanning playlist:", playlist["title"])

        items = fetch_playlist_items(playlist["playlist_id"])

        for video in items:

            vid = video["video_id"]

            if vid in video_map:

                video_map[vid]["playlists"].append(
                    playlist["title"]
                )

    os.makedirs("data/bronze", exist_ok=True)

    output_path = HISTORIC_OUTPUT if mode == "historic" else WEEKLY_OUTPUT

    with open(output_path, "w", encoding="utf-8") as f:

        json.dump(
            list(video_map.values()),
            f,
            indent=2,
            ensure_ascii=False
        )

    print("Saved", len(video_map), "videos to bronze")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["historic", "weekly"],
        default="historic"
    )
    parser.add_argument(
        "--loopback-days",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    run(args.mode, loopback_days=args.loopback_days)

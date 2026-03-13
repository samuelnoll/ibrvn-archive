import os
import json
import yaml
import requests
import argparse
from datetime import datetime, timedelta

API_KEY = os.environ["YOUTUBE_API_KEY"]

CONFIG_PATH = "config/youtube.yaml"

HISTORIC_OUTPUT = "data/bronze/youtube_videos.json"
WEEKLY_OUTPUT = "data/bronze/youtube_weekly_videos.json"


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

    r = requests.get(url, params=params).json()

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

        r = requests.get(url, params=params).json()

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

        r = requests.get(url, params=params).json()

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

        r = requests.get(url, params=params).json()

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


def filter_recent_videos(videos, days=30):

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


def run(mode):

    channel_id = load_channel()

    uploads_playlist = get_upload_playlist(channel_id)

    print("Downloading uploads playlist...")

    videos = fetch_playlist_items(uploads_playlist)

    if mode == "weekly":

        print("Filtering last 30 days videos...")

        videos = filter_recent_videos(videos)

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

    args = parser.parse_args()

    run(args.mode)

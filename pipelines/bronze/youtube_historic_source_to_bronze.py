import os
import json
import yaml
import requests

API_KEY = os.environ["YOUTUBE_API_KEY"]

CONFIG_PATH = "config/youtube.yaml"
OUTPUT_PATH = "data/bronze/youtube_videos.json"


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


def run():

    channel_id = load_channel()

    uploads_playlist = get_upload_playlist(channel_id)

    print("Downloading uploads playlist...")

    videos = fetch_playlist_items(uploads_playlist)

    video_map = {v["video_id"]: v for v in videos}

    for v in video_map.values():
        v["playlists"] = []

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

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:

        json.dump(
            list(video_map.values()),
            f,
            indent=2,
            ensure_ascii=False
        )

    print("Saved", len(video_map), "videos to bronze")


if __name__ == "__main__":
    run()

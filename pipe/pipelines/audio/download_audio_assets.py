from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import requests
from sqlalchemy import text
from yt_dlp import YoutubeDL

from shared.db import (
    begin_processing_run,
    ensure_schema,
    fetch_all,
    finish_processing_run,
    get_engine,
)
from shared.settings import AUDIO_RAW_DIR


UPSERT_AUDIO_ASSET_SQL = """
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
    mime_type = EXCLUDED.mime_type
"""


def guess_extension(source_url: str, mime_type: str) -> str:

    lower_url = (source_url or "").lower()

    for extension in (".mp3", ".m4a", ".wav", ".ogg"):
        if lower_url.endswith(extension):
            return extension

    mime_map = {
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
    }

    return mime_map.get(mime_type, ".bin")


def build_target_path(canonical_sermon_id: str) -> Path:

    filename = canonical_sermon_id.replace("-", "_") + ".mp3"
    return AUDIO_RAW_DIR / filename


def download_file(source_url: str, destination: Path):

    with requests.get(source_url, timeout=120, stream=True) as response:
        response.raise_for_status()

        with open(destination, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file_handle.write(chunk)


def convert_to_mp3(source_path: Path, target_path: Path):

    subprocess.run([
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-codec:a",
        "libmp3lame",
        str(target_path),
    ], check=True)


def download_direct_audio(source_url: str, mime_type: str, target_path: Path):

    if target_path.exists():
        return

    if target_path.suffix == ".mp3" and (
        source_url.lower().endswith(".mp3")
        or mime_type == "audio/mpeg"
    ):
        download_file(source_url, target_path)
        return

    extension = guess_extension(source_url, mime_type)

    with tempfile.NamedTemporaryFile(
        suffix=extension,
        delete=False,
        dir=AUDIO_RAW_DIR,
    ) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        download_file(source_url, temp_path)
        convert_to_mp3(temp_path, target_path)
    finally:
        temp_path.unlink(missing_ok=True)


def download_youtube_audio(youtube_url: str, target_path: Path):

    if target_path.exists():
        return

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(target_path.parent / f"{target_path.stem}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            },
        ],
        "overwrites": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])


def run():

    run_id = begin_processing_run(
        "download_audio_assets",
        "silver_media_assets",
    )

    try:
        rows = fetch_all("""
            SELECT
                canonical_sermon_id,
                MAX(CASE WHEN asset_type = 'audio' THEN source_url END) AS audio_source_url,
                MAX(CASE WHEN asset_type = 'audio' THEN local_path END) AS audio_local_path,
                MAX(CASE WHEN asset_type = 'audio' THEN mime_type END) AS audio_mime_type,
                MAX(CASE WHEN asset_type = 'youtube_video' THEN source_url END) AS youtube_source_url
            FROM silver_media_assets
            GROUP BY canonical_sermon_id
            HAVING
                COALESCE(MAX(CASE WHEN asset_type = 'audio' THEN source_url END), '') != ''
                OR COALESCE(MAX(CASE WHEN asset_type = 'youtube_video' THEN source_url END), '') != ''
        """)

        AUDIO_RAW_DIR.mkdir(parents=True, exist_ok=True)

        upserts = []

        for row in rows:
            target_path = build_target_path(row["canonical_sermon_id"])
            audio_source_url = row.get("audio_source_url") or ""
            youtube_source_url = row.get("youtube_source_url") or ""
            audio_mime_type = row.get("audio_mime_type") or ""

            if audio_source_url:
                download_direct_audio(
                    audio_source_url,
                    audio_mime_type,
                    target_path,
                )
            elif youtube_source_url:
                download_youtube_audio(
                    youtube_source_url,
                    target_path,
                )
            else:
                continue

            upserts.append({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "asset_type": "audio",
                "source_url": audio_source_url,
                "local_path": str(target_path),
                "duration_seconds": None,
                "mime_type": "audio/mpeg",
            })

        with get_engine().begin() as conn:
            ensure_schema(conn)

            if upserts:
                conn.execute(text(UPSERT_AUDIO_ASSET_SQL), upserts)

        finish_processing_run(run_id, "success")
        print("Audio assets downloaded into silver media assets")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

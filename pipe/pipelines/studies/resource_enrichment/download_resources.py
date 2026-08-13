from __future__ import annotations

import argparse
from pathlib import Path

import requests
from sqlalchemy import text
from yt_dlp import YoutubeDL

from shared.db import get_engine, utc_now_iso
from shared.settings import STUDY_RESOURCE_RAW_DIR
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)

from .common import (
    build_local_path,
    candidate_filename,
    fetch_gold_resource_rows,
    guessed_mime_type,
    select_download_candidates,
    stable_asset_id,
)


UPSERT_ASSET_SQL = """
INSERT INTO silver_study_resource_assets (
    asset_id, resource_id, study_id, asset_type, source_kind, source_url,
    original_filename, local_path, mime_type, duration_seconds,
    downloaded_at, updated_at
)
VALUES (
    :asset_id, :resource_id, :study_id, :asset_type, :source_kind, :source_url,
    :original_filename, :local_path, :mime_type, :duration_seconds,
    :downloaded_at, :updated_at
)
ON CONFLICT(asset_id) DO UPDATE SET
    resource_id = EXCLUDED.resource_id,
    study_id = EXCLUDED.study_id,
    asset_type = EXCLUDED.asset_type,
    source_kind = EXCLUDED.source_kind,
    source_url = EXCLUDED.source_url,
    original_filename = EXCLUDED.original_filename,
    local_path = EXCLUDED.local_path,
    mime_type = EXCLUDED.mime_type,
    updated_at = EXCLUDED.updated_at
"""


def download_direct_file(source_url: str, destination: Path) -> str:
    temporary_path = destination.with_name(f".{destination.name}.part")

    try:
        with requests.get(source_url, timeout=120, stream=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0]

            with temporary_path.open("wb") as file_handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file_handle.write(chunk)

        temporary_path.replace(destination)
        return content_type
    finally:
        temporary_path.unlink(missing_ok=True)


def download_youtube_audio(source_url: str, destination: Path) -> None:
    options = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 120,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
        },
        "outtmpl": str(destination.parent / f"{destination.stem}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }],
        "overwrites": True,
    }

    with YoutubeDL(options) as downloader:
        downloader.download([source_url])

    if not destination.exists():
        raise FileNotFoundError(f"yt-dlp did not create {destination}")


def run(loopback_days=None) -> dict[str, int]:
    run_id = begin_study_processing_run(
        "study_resource_download",
        str(STUDY_RESOURCE_RAW_DIR),
    )

    try:
        candidates = select_download_candidates(
            fetch_gold_resource_rows(loopback_days)
        )
        STUDY_RESOURCE_RAW_DIR.mkdir(parents=True, exist_ok=True)
        rows = []
        failures = []

        for candidate in candidates:
            filename = candidate_filename(candidate)
            destination = build_local_path(candidate, filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_url = candidate.get("source_url") or candidate.get("canonical_url")
            content_type = candidate.get("mime_type") or ""

            try:
                if not destination.exists():
                    if candidate["source_kind"] == "youtube":
                        download_youtube_audio(source_url, destination)
                        content_type = "audio/mpeg"
                    else:
                        content_type = download_direct_file(source_url, destination)
            except Exception as exc:
                failures.append(candidate["resource_id"])
                print(f"Failed study resource {candidate['resource_id']}: {exc}")
                continue

            now = utc_now_iso()
            rows.append({
                "asset_id": stable_asset_id(
                    candidate["resource_id"], candidate["source_kind"]
                ),
                "resource_id": candidate["resource_id"],
                "study_id": candidate["study_id"],
                "asset_type": candidate["asset_type"],
                "source_kind": candidate["source_kind"],
                "source_url": source_url,
                "original_filename": filename,
                "local_path": str(destination),
                "mime_type": guessed_mime_type(filename, content_type),
                "duration_seconds": None,
                "downloaded_at": now,
                "updated_at": now,
            })

        with get_engine().begin() as connection:
            ensure_study_schema(connection)

            if rows:
                connection.execute(text(UPSERT_ASSET_SQL), rows)

        result = {
            "eligible": len(candidates),
            "downloaded": len(rows),
            "failed": len(failures),
        }
        finish_study_processing_run(run_id, "success")
        print(f"Study resources downloaded: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loopback-days", type=int, default=None)
    arguments = parser.parse_args()
    run(arguments.loopback_days)

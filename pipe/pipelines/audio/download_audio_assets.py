from __future__ import annotations

from pathlib import Path

import requests
from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    fetch_all,
    finish_processing_run,
    get_engine,
)
from shared.settings import AUDIO_RAW_DIR


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


def run():

    run_id = begin_processing_run(
        "download_audio_assets",
        "silver_media_assets",
    )

    try:
        rows = fetch_all("""
            SELECT
                canonical_sermon_id,
                asset_type,
                source_url,
                local_path,
                mime_type
            FROM silver_media_assets
            WHERE asset_type = 'audio'
            AND COALESCE(source_url, '') != ''
        """)

        AUDIO_RAW_DIR.mkdir(parents=True, exist_ok=True)

        updates = []

        for row in rows:
            source_url = row["source_url"]
            extension = guess_extension(source_url, row.get("mime_type", ""))
            local_path = AUDIO_RAW_DIR / f"{row['canonical_sermon_id']}{extension}"

            if not local_path.exists():
                response = requests.get(source_url, timeout=120)
                response.raise_for_status()
                local_path.write_bytes(response.content)

            updates.append({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "asset_type": "audio",
                "local_path": str(local_path),
            })

        with get_engine().begin() as conn:
            ensure_schema(conn)

            if updates:
                conn.execute(text("""
                    UPDATE silver_media_assets
                    SET local_path = :local_path
                    WHERE canonical_sermon_id = :canonical_sermon_id
                    AND asset_type = :asset_type
                """), updates)

        finish_processing_run(run_id, "success")
        print("Audio assets downloaded into silver media assets")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

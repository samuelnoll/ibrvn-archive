from __future__ import annotations

from mutagen import File as MutagenFile
from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    fetch_all,
    finish_processing_run,
    get_engine,
)


def run():

    run_id = begin_processing_run(
        "measure_audio_duration",
        "silver_media_assets",
    )

    try:
        rows = fetch_all("""
            SELECT
                canonical_sermon_id,
                asset_type,
                local_path
            FROM silver_media_assets
            WHERE asset_type = 'audio'
            AND COALESCE(local_path, '') != ''
            AND duration_seconds IS NULL
        """)

        updates = []

        for row in rows:
            audio = MutagenFile(row["local_path"])

            if audio is None or getattr(audio, "info", None) is None:
                continue

            duration_seconds = getattr(audio.info, "length", None)
            mime_type = ""

            if getattr(audio, "mime", None):
                mime_type = audio.mime[0]

            updates.append({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "asset_type": "audio",
                "duration_seconds": duration_seconds,
                "mime_type": mime_type,
            })

        with get_engine().begin() as conn:
            ensure_schema(conn)

            if updates:
                conn.execute(text("""
                    UPDATE silver_media_assets
                    SET
                        duration_seconds = :duration_seconds,
                        mime_type = :mime_type
                    WHERE canonical_sermon_id = :canonical_sermon_id
                    AND asset_type = :asset_type
                """), updates)

        finish_processing_run(run_id, "success")
        print("Audio durations measured and saved into silver media assets")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

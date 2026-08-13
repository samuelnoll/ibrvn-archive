from __future__ import annotations

import argparse

from mutagen import File as MutagenFile
from sqlalchemy import text

from shared.db import fetch_all, get_engine, utc_now_iso
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)

from .common import build_study_date_scope


def run(loopback_days=None) -> dict[str, int]:
    run_id = begin_study_processing_run(
        "study_resource_measure_audio_duration",
        "silver_study_resource_assets",
    )

    try:
        scope_sql, params = build_study_date_scope("gs", loopback_days)
        rows = fetch_all(f"""
            SELECT ssra.asset_id, ssra.local_path
            FROM silver_study_resource_assets ssra
            JOIN gold_studies gs ON gs.study_id = ssra.study_id
            WHERE ssra.asset_type = 'audio'
            AND (
                LOWER(COALESCE(ssra.mime_type, '')) = 'audio/mpeg'
                OR LOWER(ssra.local_path) LIKE '%.mp3'
            )
            AND ssra.duration_seconds IS NULL
            {scope_sql}
            ORDER BY gs.study_date DESC, ssra.asset_id
        """, params)
        updates = []

        for row in rows:
            audio = MutagenFile(row["local_path"])

            if audio is None or getattr(audio, "info", None) is None:
                continue

            duration = getattr(audio.info, "length", None)

            if duration is not None:
                updates.append({
                    "asset_id": row["asset_id"],
                    "duration_seconds": float(duration),
                    "updated_at": utc_now_iso(),
                })

        with get_engine().begin() as connection:
            ensure_study_schema(connection)

            if updates:
                connection.execute(text("""
                    UPDATE silver_study_resource_assets
                    SET duration_seconds = :duration_seconds,
                        updated_at = :updated_at
                    WHERE asset_id = :asset_id
                """), updates)

        result = {"pending": len(rows), "measured": len(updates)}
        finish_study_processing_run(run_id, "success")
        print(f"Study MP3 durations measured: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loopback-days", type=int, default=None)
    arguments = parser.parse_args()
    run(arguments.loopback_days)

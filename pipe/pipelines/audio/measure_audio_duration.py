from __future__ import annotations

import argparse

from mutagen import File as MutagenFile
from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    fetch_all,
    finish_processing_run,
    get_engine,
)

from .common import build_preaching_date_scope, normalize_force_reprocess


def run(loopback_days=None, force_reprocess=False):

    run_id = begin_processing_run(
        "measure_audio_duration",
        "silver_media_assets",
    )

    try:
        force_reprocess = normalize_force_reprocess(force_reprocess)
        scope_sql, params = build_preaching_date_scope("sm", loopback_days)
        duration_filter = "" if force_reprocess else "AND sma.duration_seconds IS NULL"

        rows = fetch_all(f"""
            SELECT
                sma.canonical_sermon_id,
                sma.asset_type,
                sma.local_path,
                sma.duration_seconds,
                sm.preaching_date
            FROM silver_media_assets sma
            LEFT JOIN silver_sermon_metadata sm
                ON sm.canonical_sermon_id = sma.canonical_sermon_id
            WHERE sma.asset_type = 'audio'
            AND COALESCE(sma.local_path, '') != ''
            {duration_filter}
            {scope_sql}
            ORDER BY sm.preaching_date DESC, sma.canonical_sermon_id DESC
        """, params)

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

    parser = argparse.ArgumentParser()
    parser.add_argument("--loopback-days", type=int, default=None)
    parser.add_argument("--force-reprocess", action="store_true")
    args = parser.parse_args()

    run(
        loopback_days=args.loopback_days,
        force_reprocess=args.force_reprocess,
    )

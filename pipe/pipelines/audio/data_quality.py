from __future__ import annotations

import argparse

from shared.db import begin_processing_run, fetch_one, finish_processing_run

from .common import build_preaching_date_scope


def run(loopback_days=None):

    run_id = begin_processing_run(
        "audio_data_quality",
        "silver tables",
    )

    try:
        scope_sql, params = build_preaching_date_scope("sm", loopback_days)

        downloads_missing = fetch_one(f"""
            SELECT COUNT(DISTINCT sm.canonical_sermon_id) AS total
            FROM silver_sermon_metadata sm
            LEFT JOIN silver_media_assets audio
                ON audio.canonical_sermon_id = sm.canonical_sermon_id
                AND audio.asset_type = 'audio'
            LEFT JOIN silver_media_assets youtube
                ON youtube.canonical_sermon_id = sm.canonical_sermon_id
                AND youtube.asset_type = 'youtube_video'
            WHERE (
                COALESCE(audio.source_url, '') != ''
                OR COALESCE(youtube.source_url, '') != ''
            )
            AND COALESCE(audio.local_path, '') = ''
            {scope_sql}
        """, params)

        durations_missing = fetch_one(f"""
            SELECT COUNT(DISTINCT sm.canonical_sermon_id) AS total
            FROM silver_sermon_metadata sm
            JOIN silver_media_assets audio
                ON audio.canonical_sermon_id = sm.canonical_sermon_id
                AND audio.asset_type = 'audio'
            WHERE COALESCE(audio.local_path, '') != ''
            AND audio.duration_seconds IS NULL
            {scope_sql}
        """, params)

        transcripts_missing = fetch_one(f"""
            SELECT COUNT(DISTINCT sm.canonical_sermon_id) AS total
            FROM silver_sermon_metadata sm
            JOIN silver_media_assets audio
                ON audio.canonical_sermon_id = sm.canonical_sermon_id
                AND audio.asset_type = 'audio'
            WHERE COALESCE(audio.local_path, '') != ''
            AND NOT EXISTS (
                SELECT 1
                FROM silver_transcripts st
                WHERE st.canonical_sermon_id = sm.canonical_sermon_id
            )
            {scope_sql}
        """, params)

        print("Audio data quality summary")
        print(f"loopback_days: {loopback_days if loopback_days is not None else 'all'}")
        print(f"downloads_missing: {downloads_missing['total'] if downloads_missing else 0}")
        print(f"durations_missing: {durations_missing['total'] if durations_missing else 0}")
        print(f"transcripts_missing: {transcripts_missing['total'] if transcripts_missing else 0}")

        finish_processing_run(run_id, "success")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--loopback-days", type=int, default=None)
    args = parser.parse_args()

    run(loopback_days=args.loopback_days)

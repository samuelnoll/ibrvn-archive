from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests
from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    fetch_all,
    finish_processing_run,
    get_engine,
    utc_now_iso,
)
from shared.settings import AI_BASE_URL, AI_TIMEOUT_SECONDS

from .common import (
    build_preaching_date_scope,
    format_duration_minutes,
    format_elapsed_seconds,
    normalize_force_reprocess,
)


INSERT_TRANSCRIPT_SQL = """
INSERT INTO silver_transcripts (
    canonical_sermon_id,
    transcript_version,
    language,
    transcript_text,
    model_name,
    created_at
)
VALUES (
    :canonical_sermon_id,
    :transcript_version,
    :language,
    :transcript_text,
    :model_name,
    :created_at
)
"""


def request_transcription(local_path: str):

    file_path = Path(local_path)

    with open(file_path, "rb") as audio_file:
        response = requests.post(
            f"{AI_BASE_URL}/v1/transcriptions",
            files={
                "file": (
                    file_path.name,
                    audio_file,
                    "audio/mpeg",
                ),
            },
            data={
                "language": "pt",
                "vad_filter": "true",
            },
            timeout=AI_TIMEOUT_SECONDS,
        )

    response.raise_for_status()
    return response.json()


def build_pending_rows(loopback_days=None, force_reprocess=False):

    scope_sql, params = build_preaching_date_scope("sm", loopback_days)
    transcript_filter = ""

    if not normalize_force_reprocess(force_reprocess):
        transcript_filter = """
        AND NOT EXISTS (
            SELECT 1
            FROM silver_transcripts st
            WHERE st.canonical_sermon_id = sma.canonical_sermon_id
        )
        """

    return fetch_all(f"""
        SELECT
            sma.canonical_sermon_id,
            sma.local_path,
            sma.duration_seconds,
            MAX(sm.preaching_date) AS preaching_date
        FROM silver_media_assets sma
        LEFT JOIN silver_sermon_metadata sm
            ON sm.canonical_sermon_id = sma.canonical_sermon_id
        WHERE sma.asset_type = 'audio'
        AND COALESCE(sma.local_path, '') != ''
        {transcript_filter}
        {scope_sql}
        GROUP BY
            sma.canonical_sermon_id,
            sma.local_path,
            sma.duration_seconds
        ORDER BY MAX(sm.preaching_date) DESC, sma.canonical_sermon_id DESC
    """, params)


def insert_transcript(record):

    with get_engine().begin() as conn:
        ensure_schema(conn)

        version = conn.execute(text("""
            SELECT COALESCE(MAX(transcript_version), 0)
            FROM silver_transcripts
            WHERE canonical_sermon_id = :canonical_sermon_id
        """), {
            "canonical_sermon_id": record["canonical_sermon_id"],
        }).scalar_one()

        payload = dict(record)
        payload["transcript_version"] = int(version or 0) + 1
        conn.execute(text(INSERT_TRANSCRIPT_SQL), payload)

    return payload["transcript_version"]


def run(loopback_days=None, force_reprocess=False):

    run_id = begin_processing_run(
        "transcribe_audio",
        "silver_media_assets",
    )

    try:
        rows = build_pending_rows(
            loopback_days=loopback_days,
            force_reprocess=force_reprocess,
        )
        total = len(rows)

        print(
            "Transcription queue prepared | "
            f"pending_sermons={total} | "
            f"loopback_days={loopback_days if loopback_days is not None else 'all'} | "
            f"force_reprocess={normalize_force_reprocess(force_reprocess)}"
        )

        if total == 0:
            print("No sermons pending audio transcription for the selected scope")
            finish_processing_run(run_id, "success")
            return

        overall_started_at = time.perf_counter()

        for index, row in enumerate(rows, start=1):
            sermon_started_at = time.perf_counter()
            result = request_transcription(row["local_path"])
            transcript_text = (result.get("transcript_text", "") or "").strip()

            if not transcript_text:
                print(
                    f"Skipped {index}/{total} | "
                    f"{row.get('preaching_date') or 'unknown-date'} | "
                    "empty transcript returned"
                )
                continue

            transcript_version = insert_transcript({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "language": result.get("language", "pt"),
                "transcript_text": transcript_text,
                "model_name": result.get("model_name", "homelab-ai"),
                "created_at": utc_now_iso(),
            })

            sermon_elapsed = time.perf_counter() - sermon_started_at
            overall_elapsed = time.perf_counter() - overall_started_at
            word_count = len(transcript_text.split())

            print(
                f"Transcribed {index}/{total} | "
                f"date={row.get('preaching_date') or 'unknown'} | "
                f"duration={format_duration_minutes(row.get('duration_seconds'))} | "
                f"step={format_elapsed_seconds(sermon_elapsed)} | "
                f"total={format_elapsed_seconds(overall_elapsed)} | "
                f"words={word_count} | "
                f"version={transcript_version} | "
                f"model={result.get('model_name', 'homelab-ai')} | "
                f"file={Path(row['local_path']).name}"
            )

        finish_processing_run(run_id, "success")
        print("Audio transcripts saved incrementally into silver_transcripts")

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

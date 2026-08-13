from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests
from sqlalchemy import text

from shared.db import fetch_all, get_engine, utc_now_iso
from shared.settings import AI_BASE_URL, AI_TIMEOUT_SECONDS
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)

from .common import build_study_date_scope


INSERT_TRANSCRIPT_SQL = """
INSERT INTO silver_study_resource_transcripts (
    asset_id, transcript_version, language, transcript_text, model_name, created_at
)
VALUES (
    :asset_id, :transcript_version, :language, :transcript_text, :model_name, :created_at
)
"""


def request_transcription(local_path: str) -> dict:
    file_path = Path(local_path)

    with file_path.open("rb") as audio_file:
        response = requests.post(
            f"{AI_BASE_URL}/v1/transcriptions",
            files={"file": (file_path.name, audio_file, "audio/mpeg")},
            data={"language": "pt", "vad_filter": "true"},
            timeout=AI_TIMEOUT_SECONDS,
        )

    response.raise_for_status()
    return response.json()


def pending_rows(loopback_days=None) -> list[dict]:
    scope_sql, params = build_study_date_scope("gs", loopback_days)
    return fetch_all(f"""
        SELECT ssra.asset_id, ssra.local_path, ssra.duration_seconds,
               gs.study_date, gs.title AS study_title
        FROM silver_study_resource_assets ssra
        JOIN gold_studies gs ON gs.study_id = ssra.study_id
        WHERE ssra.asset_type = 'audio'
        AND (
            LOWER(COALESCE(ssra.mime_type, '')) = 'audio/mpeg'
            OR LOWER(ssra.local_path) LIKE '%.mp3'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM silver_study_resource_transcripts ssrt
            WHERE ssrt.asset_id = ssra.asset_id
        )
        {scope_sql}
        ORDER BY gs.study_date DESC, ssra.asset_id
    """, params)


def insert_transcript(record: dict) -> int:
    with get_engine().begin() as connection:
        ensure_study_schema(connection)
        version = connection.execute(text("""
            SELECT COALESCE(MAX(transcript_version), 0)
            FROM silver_study_resource_transcripts
            WHERE asset_id = :asset_id
        """), {"asset_id": record["asset_id"]}).scalar_one()
        payload = {**record, "transcript_version": int(version or 0) + 1}
        connection.execute(text(INSERT_TRANSCRIPT_SQL), payload)
    return payload["transcript_version"]


def run(loopback_days=None) -> dict[str, int]:
    run_id = begin_study_processing_run(
        "study_resource_transcribe_audio",
        "silver_study_resource_assets",
    )

    try:
        rows = pending_rows(loopback_days)
        transcribed = 0
        started_at = time.perf_counter()

        for index, row in enumerate(rows, start=1):
            result = request_transcription(row["local_path"])
            transcript_text = str(result.get("transcript_text") or "").strip()

            if not transcript_text:
                print(f"Empty study transcript skipped: {row['asset_id']}")
                continue

            version = insert_transcript({
                "asset_id": row["asset_id"],
                "language": result.get("language", "pt"),
                "transcript_text": transcript_text,
                "model_name": result.get("model_name", "homelab-ai"),
                "created_at": utc_now_iso(),
            })
            transcribed += 1
            elapsed = time.perf_counter() - started_at
            print(
                f"Transcribed study audio {index}/{len(rows)} | "
                f"version={version} | elapsed={elapsed:.1f}s | "
                f"file={Path(row['local_path']).name}"
            )

        result = {"pending": len(rows), "transcribed": transcribed}
        finish_study_processing_run(run_id, "success")
        print(f"Study audio transcription complete: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loopback-days", type=int, default=None)
    arguments = parser.parse_args()
    run(arguments.loopback_days)

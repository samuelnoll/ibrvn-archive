from __future__ import annotations

from pathlib import Path

import requests
from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    fetch_all,
    fetch_one,
    finish_processing_run,
    get_engine,
    utc_now_iso,
)
from shared.settings import AI_BASE_URL, AI_TIMEOUT_SECONDS


def next_transcript_version(canonical_sermon_id: str) -> int:

    row = fetch_one("""
        SELECT COALESCE(MAX(transcript_version), 0) AS version
        FROM silver_transcripts
        WHERE canonical_sermon_id = :canonical_sermon_id
    """, {"canonical_sermon_id": canonical_sermon_id})

    return int(row["version"]) + 1 if row else 1


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


def run():

    run_id = begin_processing_run(
        "transcribe_audio",
        "silver_media_assets",
    )

    try:
        rows = fetch_all("""
            SELECT
                canonical_sermon_id,
                local_path
            FROM silver_media_assets
            WHERE asset_type = 'audio'
            AND COALESCE(local_path, '') != ''
            AND NOT EXISTS (
                SELECT 1
                FROM silver_transcripts st
                WHERE st.canonical_sermon_id = silver_media_assets.canonical_sermon_id
            )
        """)

        records = []

        for row in rows:
            result = request_transcription(row["local_path"])
            transcript_text = (result.get("transcript_text", "") or "").strip()

            if not transcript_text:
                continue

            records.append({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "transcript_version": next_transcript_version(row["canonical_sermon_id"]),
                "language": result.get("language", "pt"),
                "transcript_text": transcript_text,
                "model_name": result.get("model_name", "homelab-ai"),
                "created_at": utc_now_iso(),
            })

        with get_engine().begin() as conn:
            ensure_schema(conn)

            if records:
                conn.execute(text("""
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
                """), records)

        finish_processing_run(run_id, "success")
        print("Audio transcripts saved into silver_transcripts")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

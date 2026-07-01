from __future__ import annotations

from openai import OpenAI
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
from shared.settings import OPENAI_API_KEY, OPENAI_TRANSCRIPTION_MODEL


def next_transcript_version(canonical_sermon_id: str) -> int:

    row = fetch_one("""
        SELECT COALESCE(MAX(transcript_version), 0) AS version
        FROM silver_transcripts
        WHERE canonical_sermon_id = :canonical_sermon_id
    """, {"canonical_sermon_id": canonical_sermon_id})

    return int(row["version"]) + 1 if row else 1


def run():

    if not OPENAI_API_KEY:
        raise RuntimeError("Set OPENAI_API_KEY before running audio transcription.")

    run_id = begin_processing_run(
        "transcribe_audio",
        "silver_media_assets",
    )

    try:
        client = OpenAI()
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
            with open(row["local_path"], "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model=OPENAI_TRANSCRIPTION_MODEL,
                    file=audio_file,
                    response_format="text",
                )

            transcript_text = (
                transcription.text
                if hasattr(transcription, "text")
                else str(transcription)
            )

            records.append({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "transcript_version": next_transcript_version(row["canonical_sermon_id"]),
                "language": "pt",
                "transcript_text": transcript_text,
                "model_name": OPENAI_TRANSCRIPTION_MODEL,
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

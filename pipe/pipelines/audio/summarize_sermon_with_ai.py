from __future__ import annotations

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


SERMON_SUMMARY_SYSTEM_PROMPT = (
    "You are a careful assistant that summarizes spoken Christian sermons in "
    "Brazilian Portuguese."
)

SERMON_SUMMARY_PROMPT = (
    "Resuma a pregacao em portugues do Brasil em 1 a 3 paragrafos, "
    "destacando tema principal, texto biblico e aplicacoes praticas."
)


def next_summary_version(canonical_sermon_id: str) -> int:

    row = fetch_one("""
        SELECT COALESCE(MAX(summary_version), 0) AS version
        FROM silver_summaries
        WHERE canonical_sermon_id = :canonical_sermon_id
    """, {"canonical_sermon_id": canonical_sermon_id})

    return int(row["version"]) + 1 if row else 1


def request_summary(transcript_text: str):

    response = requests.post(
        f"{AI_BASE_URL}/v1/summaries",
        json={
            "text": transcript_text,
            "system_prompt": SERMON_SUMMARY_SYSTEM_PROMPT,
            "prompt": SERMON_SUMMARY_PROMPT,
        },
        timeout=AI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def run():

    run_id = begin_processing_run(
        "summarize_sermon_with_ai",
        "silver_transcripts",
    )

    try:
        rows = fetch_all("""
            SELECT
                canonical_sermon_id,
                transcript_text
            FROM silver_transcripts st
            WHERE transcript_version = (
                SELECT MAX(st2.transcript_version)
                FROM silver_transcripts st2
                WHERE st2.canonical_sermon_id = st.canonical_sermon_id
            )
            AND NOT EXISTS (
                SELECT 1
                FROM silver_summaries ss
                WHERE ss.canonical_sermon_id = st.canonical_sermon_id
            )
        """)

        records = []

        for row in rows:
            result = request_summary(row["transcript_text"])
            summary_text = (result.get("summary_text", "") or "").strip()

            if not summary_text:
                continue

            records.append({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "summary_version": next_summary_version(row["canonical_sermon_id"]),
                "summary_text": summary_text,
                "model_name": result.get("model_name", "homelab-ai"),
                "created_at": utc_now_iso(),
            })

        with get_engine().begin() as conn:
            ensure_schema(conn)

            if records:
                conn.execute(text("""
                    INSERT INTO silver_summaries (
                        canonical_sermon_id,
                        summary_version,
                        summary_text,
                        model_name,
                        created_at
                    )
                    VALUES (
                        :canonical_sermon_id,
                        :summary_version,
                        :summary_text,
                        :model_name,
                        :created_at
                    )
                """), records)

        finish_processing_run(run_id, "success")
        print("Sermon summaries saved into silver_summaries")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

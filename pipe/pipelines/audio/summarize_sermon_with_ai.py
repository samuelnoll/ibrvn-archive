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
from shared.settings import OPENAI_API_KEY, OPENAI_SUMMARY_MODEL


def next_summary_version(canonical_sermon_id: str) -> int:

    row = fetch_one("""
        SELECT COALESCE(MAX(summary_version), 0) AS version
        FROM silver_summaries
        WHERE canonical_sermon_id = :canonical_sermon_id
    """, {"canonical_sermon_id": canonical_sermon_id})

    return int(row["version"]) + 1 if row else 1


def run():

    if not OPENAI_API_KEY:
        raise RuntimeError("Set OPENAI_API_KEY before running sermon summarization.")

    run_id = begin_processing_run(
        "summarize_sermon_with_ai",
        "silver_transcripts",
    )

    try:
        client = OpenAI()
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
            response = client.responses.create(
                model=OPENAI_SUMMARY_MODEL,
                input=(
                    "Resuma a pregacao em portugues do Brasil em 1 a 3 paragrafos, "
                    "destacando tema principal, texto biblico e aplicacoes praticas.\n\n"
                    f"Transcricao:\n{row['transcript_text']}"
                ),
            )

            records.append({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "summary_version": next_summary_version(row["canonical_sermon_id"]),
                "summary_text": response.output_text,
                "model_name": OPENAI_SUMMARY_MODEL,
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

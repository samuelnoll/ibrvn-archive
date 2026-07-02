from __future__ import annotations

import argparse
import time

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
    format_elapsed_seconds,
    normalize_force_reprocess,
)


SERMON_SUMMARY_SYSTEM_PROMPT = (
    "You are a careful assistant that summarizes spoken Christian sermons in "
    "Brazilian Portuguese."
)

SERMON_SUMMARY_PROMPT = (
    "Resuma a pregacao em portugues do Brasil em no maximo 50 palavras, "
    "destacando principalmente o tema principal e enfoques do pregador"
)

INSERT_SUMMARY_SQL = """
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
"""


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


def build_pending_rows(loopback_days=None, force_reprocess=False):

    scope_sql, params = build_preaching_date_scope("sm", loopback_days)
    summary_filter = ""

    if not normalize_force_reprocess(force_reprocess):
        summary_filter = """
        AND NOT EXISTS (
            SELECT 1
            FROM silver_summaries ss
            WHERE ss.canonical_sermon_id = st.canonical_sermon_id
        )
        """

    return fetch_all(f"""
        SELECT
            st.canonical_sermon_id,
            st.transcript_text,
            st.transcript_version,
            sm.preaching_date
        FROM silver_transcripts st
        LEFT JOIN silver_sermon_metadata sm
            ON sm.canonical_sermon_id = st.canonical_sermon_id
        WHERE st.transcript_version = (
            SELECT MAX(st2.transcript_version)
            FROM silver_transcripts st2
            WHERE st2.canonical_sermon_id = st.canonical_sermon_id
        )
        {summary_filter}
        {scope_sql}
        ORDER BY sm.preaching_date DESC, st.canonical_sermon_id DESC
    """, params)


def insert_summary(record):

    with get_engine().begin() as conn:
        ensure_schema(conn)

        version = conn.execute(text("""
            SELECT COALESCE(MAX(summary_version), 0)
            FROM silver_summaries
            WHERE canonical_sermon_id = :canonical_sermon_id
        """), {
            "canonical_sermon_id": record["canonical_sermon_id"],
        }).scalar_one()

        payload = dict(record)
        payload["summary_version"] = int(version or 0) + 1
        conn.execute(text(INSERT_SUMMARY_SQL), payload)

    return payload["summary_version"]


def run(loopback_days=None, force_reprocess=False):

    run_id = begin_processing_run(
        "summarize_sermon_with_ai",
        "silver_transcripts",
    )

    try:
        rows = build_pending_rows(
            loopback_days=loopback_days,
            force_reprocess=force_reprocess,
        )
        total = len(rows)

        if total == 0:
            print("No sermons pending summary generation for the selected scope")
            finish_processing_run(run_id, "success")
            return

        overall_started_at = time.perf_counter()

        for index, row in enumerate(rows, start=1):
            sermon_started_at = time.perf_counter()
            result = request_summary(row["transcript_text"])
            summary_text = (result.get("summary_text", "") or "").strip()

            if not summary_text:
                print(
                    f"Skipped summary {index}/{total} | "
                    f"{row.get('preaching_date') or 'unknown-date'} | "
                    "empty summary returned"
                )
                continue

            summary_version = insert_summary({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "summary_text": summary_text,
                "model_name": result.get("model_name", "homelab-ai"),
                "created_at": utc_now_iso(),
            })

            sermon_elapsed = time.perf_counter() - sermon_started_at
            overall_elapsed = time.perf_counter() - overall_started_at

            print(
                f"Summarized {index}/{total} | "
                f"date={row.get('preaching_date') or 'unknown'} | "
                f"step={format_elapsed_seconds(sermon_elapsed)} | "
                f"total={format_elapsed_seconds(overall_elapsed)} | "
                f"chars={len(summary_text)} | "
                f"transcript_version={row['transcript_version']} | "
                f"summary_version={summary_version} | "
                f"model={result.get('model_name', 'homelab-ai')}"
            )

        finish_processing_run(run_id, "success")
        print("Sermon summaries saved incrementally into silver_summaries")

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

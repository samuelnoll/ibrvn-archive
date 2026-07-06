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


SERMON_SUMMARY_MAX_WORDS = 70

SERMON_SUMMARY_SYSTEM_PROMPT = (
    "You summarize spoken Christian sermons in Brazilian Portuguese. "
    "Always answer in Brazilian Portuguese. "
    "Return exactly one short paragraph with no line breaks, at most 70 words, "
    "and at most 3 short sentences. "
    "If the sermon is long, keep only the central theme, the main thesis, and "
    "the most repeated emphases. "
    "Do not add headings, bullets, lists, introductions, conclusions, quotes, "
    "or extra commentary. "
    "Do not think aloud. Do not show reasoning. Do not explain your process. "
    "Answer directly with the final summary only."
)

SERMON_SUMMARY_PROMPT = (
    "Leia a transcricao inteira e devolva somente o resumo final em um unico paragrafo curto."
)

SERMON_SUMMARY_REPAIR_SYSTEM_PROMPT = (
    "You rewrite sermon summaries in Brazilian Portuguese. "
    "Return exactly one short paragraph with no line breaks, at most 70 words, "
    "and at most 3 short sentences. "
    "Preserve only the central theme, the main thesis, and the most repeated emphases. "
    "Do not add new information, headings, bullets, or commentary. "
    "Answer directly with the rewritten summary only."
)

SERMON_SUMMARY_REPAIR_PROMPT = (
    "Reescreva o texto abaixo como um resumo final mais curto, em um unico paragrafo."
)

SERMON_SUMMARY_MAX_OUTPUT_TOKENS = 90

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


def request_summary(
    transcript_text: str,
    system_prompt: str = SERMON_SUMMARY_SYSTEM_PROMPT,
    prompt: str = SERMON_SUMMARY_PROMPT,
    max_output_tokens: int = SERMON_SUMMARY_MAX_OUTPUT_TOKENS,
):

    response = requests.post(
        f"{AI_BASE_URL}/v1/summaries",
        json={
            "text": transcript_text,
            "system_prompt": system_prompt,
            "prompt": prompt,
            "max_output_tokens": max_output_tokens,
        },
        timeout=AI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def normalize_summary_text(summary_text: str) -> str:

    pieces = []

    for raw_line in (summary_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = " ".join(raw_line.strip().split())

        if not cleaned:
            continue

        if cleaned[:1] in {"-", "*"}:
            cleaned = cleaned[1:].strip()

        if cleaned:
            pieces.append(cleaned)

    return " ".join(pieces).strip()


def count_words(text_value: str) -> int:

    return len([part for part in (text_value or "").split(" ") if part.strip()])


def summary_needs_repair(raw_text: str, normalized_text: str) -> bool:

    if not normalized_text:
        return False

    if "\n" in (raw_text or "") or "\r" in (raw_text or ""):
        return True

    return count_words(normalized_text) > SERMON_SUMMARY_MAX_WORDS


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
            MAX(sm.preaching_date) AS preaching_date
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
        GROUP BY
            st.canonical_sermon_id,
            st.transcript_text,
            st.transcript_version
        ORDER BY MAX(sm.preaching_date) DESC, st.canonical_sermon_id DESC
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
            raw_summary_text = (result.get("summary_text", "") or "").strip()
            summary_text = normalize_summary_text(raw_summary_text)
            summary_repaired = False

            if summary_needs_repair(raw_summary_text, summary_text):
                repaired_result = request_summary(
                    summary_text or raw_summary_text or row["transcript_text"],
                    system_prompt=SERMON_SUMMARY_REPAIR_SYSTEM_PROMPT,
                    prompt=SERMON_SUMMARY_REPAIR_PROMPT,
                    max_output_tokens=SERMON_SUMMARY_MAX_OUTPUT_TOKENS,
                )
                repaired_summary_text = normalize_summary_text(
                    (repaired_result.get("summary_text", "") or "").strip()
                )

                if repaired_summary_text:
                    result = repaired_result
                    summary_text = repaired_summary_text
                    summary_repaired = True

            if not summary_text:
                print(
                    f"Skipped summary {index}/{total} | "
                    f"{row.get('preaching_date') or 'unknown-date'} | "
                    "empty summary returned"
                )
                print(
                    "Empty summary payload | "
                    f"canonical_sermon_id={row['canonical_sermon_id']} | "
                    f"transcript_version={row['transcript_version']} | "
                    f"model={result.get('model_name', 'unknown')} | "
                    f"raw_result={result!r}"
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
                f"words={count_words(summary_text)} | "
                f"repaired={'yes' if summary_repaired else 'no'} | "
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

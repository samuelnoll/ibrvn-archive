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

SERMON_SUMMARY_INTERMEDIATE_SYSTEM_PROMPT = (
    "Voce resume pregacoes cristas faladas em portugues do Brasil. "
    "Responda sempre em portugues do Brasil. "
    "Faca um resumo padrao, claro e fiel ao conteudo da pregacao. "
    "Mantenha o tema central, a tese principal e as enfases mais repetidas. "
    "Nao adicione titulo, lista, comentario extra, explicacao da tarefa, "
    "nem frases sobre o que voce vai fazer. "
    "Nao pense em voz alta. Nao mostre raciocinio. Nao explique seu processo. "
    "Responda somente com o resumo."
)

SERMON_SUMMARY_INTERMEDIATE_PROMPT = (
    "Leia a transcricao inteira e devolva somente um resumo em portugues do Brasil, em texto corrido, sem comentar a tarefa."
)

SERMON_SUMMARY_FINAL_SYSTEM_PROMPT = (
    "Voce reescreve resumos de pregacoes cristas em portugues do Brasil. "
    "Devolva exatamente 1 paragrafo curto, sem quebras de linha, com no maximo "
    "70 palavras e no maximo 3 frases curtas. "
    "Preserve apenas o tema central, a tese principal e as enfases mais repetidas. "
    "Remova comentarios sobre a tarefa, explicacoes, raciocinio, titulos, listas "
    "e qualquer texto em ingles. "
    "Nao adicione informacoes novas. Responda somente com o resumo final."
)

SERMON_SUMMARY_FINAL_PROMPT = (
    "Reescreva o texto abaixo como um resumo final em portugues do Brasil, em 1 unico paragrafo com no maximo 70 palavras, sem comentar a tarefa."
)

SERMON_SUMMARY_INTERMEDIATE_MAX_OUTPUT_TOKENS = 260
SERMON_SUMMARY_FINAL_MAX_OUTPUT_TOKENS = 90
SERMON_SUMMARY_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {
        "summary_text": {
            "type": "string",
        }
    },
    "required": ["summary_text"],
}

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
    system_prompt: str,
    prompt: str,
    max_output_tokens: int,
):

    response = requests.post(
        f"{AI_BASE_URL}/v1/summaries",
        json={
            "text": transcript_text,
            "system_prompt": system_prompt,
            "prompt": prompt,
            "max_output_tokens": max_output_tokens,
            "response_format": SERMON_SUMMARY_RESPONSE_FORMAT,
        },
        timeout=AI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def normalize_summary_text(summary_text: str) -> str:

    pieces = []

    for raw_line in (
        (summary_text or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    ):
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


def summary_has_meta_commentary(text_value: str) -> bool:

    normalized = (text_value or "").strip().lower()

    if not normalized:
        return False

    meta_markers = (
        "okay,",
        "ok,",
        "the user wants",
        "let me ",
        "i need to",
        "i should",
        "the provided text",
        "this segment",
        "the main themes",
        "the sermon references",
        "vou resumir",
        "o usuario quer",
        "a transcricao fala",
        "o texto fala sobre o resumo",
        "o resumo abaixo",
        "a tarefa e",
        "resumo:",
        "summary:",
    )

    return any(marker in normalized for marker in meta_markers)


def summary_needs_repair(raw_text: str, normalized_text: str) -> bool:

    if not normalized_text:
        return False

    if "\n" in (raw_text or "") or "\r" in (raw_text or ""):
        return True

    if summary_has_meta_commentary(normalized_text):
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
            intermediate_result = request_summary(
                row["transcript_text"],
                system_prompt=SERMON_SUMMARY_INTERMEDIATE_SYSTEM_PROMPT,
                prompt=SERMON_SUMMARY_INTERMEDIATE_PROMPT,
                max_output_tokens=SERMON_SUMMARY_INTERMEDIATE_MAX_OUTPUT_TOKENS,
            )
            intermediate_raw_summary = (
                intermediate_result.get("summary_text", "") or ""
            ).strip()
            intermediate_summary = normalize_summary_text(
                intermediate_raw_summary
            )

            final_result = request_summary(
                intermediate_summary
                or intermediate_raw_summary
                or row["transcript_text"],
                system_prompt=SERMON_SUMMARY_FINAL_SYSTEM_PROMPT,
                prompt=SERMON_SUMMARY_FINAL_PROMPT,
                max_output_tokens=SERMON_SUMMARY_FINAL_MAX_OUTPUT_TOKENS,
            )
            raw_summary_text = (final_result.get("summary_text", "") or "").strip()
            summary_text = normalize_summary_text(raw_summary_text)
            summary_repaired = False

            if summary_needs_repair(raw_summary_text, summary_text):
                repaired_result = request_summary(
                    summary_text
                    or raw_summary_text
                    or intermediate_summary
                    or row["transcript_text"],
                    system_prompt=SERMON_SUMMARY_FINAL_SYSTEM_PROMPT,
                    prompt=SERMON_SUMMARY_FINAL_PROMPT,
                    max_output_tokens=SERMON_SUMMARY_FINAL_MAX_OUTPUT_TOKENS,
                )
                repaired_summary_text = normalize_summary_text(
                    (repaired_result.get("summary_text", "") or "").strip()
                )

                if repaired_summary_text:
                    final_result = repaired_result
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
                    f"model={final_result.get('model_name', 'unknown')} | "
                    f"raw_result={final_result!r}"
                )
                continue

            summary_version = insert_summary({
                "canonical_sermon_id": row["canonical_sermon_id"],
                "summary_text": summary_text,
                "model_name": final_result.get("model_name", "homelab-ai"),
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
                f"model={final_result.get('model_name', 'homelab-ai')} | "
                f"intermediate_chars={len(intermediate_summary)}"
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

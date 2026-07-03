from __future__ import annotations

import argparse
import json
import re
import smtplib
from email.message import EmailMessage

import requests

from shared.db import begin_processing_run, fetch_one, finish_processing_run
from shared.settings import (
    AI_BASE_URL,
    AI_TIMEOUT_SECONDS,
    EMAIL_FROM,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PASSWORD,
    EMAIL_SMTP_PORT,
    EMAIL_SMTP_USE_TLS,
    EMAIL_SMTP_USER,
    EMAIL_TO,
)


SERMON_CRITIQUE_SYSTEM_PROMPT = (
    "You are a careful reformed baptist Christian assistant writing a thoughtful sermon review "
    "in Brazilian Portuguese. Be detailed, very analytical, critical and useful. Always answer in Brazilian Portuguese. "
    "You must return only valid JSON, with no Markdown, no commentary, and no text outside the JSON object. "
    "The JSON object must contain exactly these keys: "
    "\"breve_resumo_da_mensagem\", "
    "\"tema_central_da_pregacao\", "
    "\"estrutura_da_pregacao\", "
    "\"teses_centrais_enfatizadas\", "
    "\"principais_argumentos\", "
    "\"pontos_sem_embasamento_suficiente\", "
    "\"pontos_polemicos_ou_fora_do_consenso\", "
    "\"aplicacoes_utilizadas\". "
    "Use string values for the first three keys. Use arrays of strings for the last five keys. "
    "All keys are mandatory. If a section has no clear items, return an empty array or a string "
    "explicitly stating that the transcript does not make that point clear. "
    "Do not invent information. In \"pontos_polemicos_ou_fora_do_consenso\", be balanced; if there "
    "are no clear controversial points, return an array with one string saying so explicitly."
)

SERMON_CRITIQUE_PROMPT = """
Analise a transcricao a seguir e produza a critica conforme as instrucoes definidas.
Retorne somente JSON valido.
"""

SERMON_CRITIQUE_MAX_OUTPUT_TOKENS = 6000


def parse_recipients():

    return [
        item.strip()
        for item in EMAIL_TO.split(",")
        if item.strip()
    ]


def request_critique(transcript_text: str):

    response = requests.post(
        f"{AI_BASE_URL}/v1/summaries",
        json={
            "text": transcript_text,
            "system_prompt": SERMON_CRITIQUE_SYSTEM_PROMPT,
            "prompt": SERMON_CRITIQUE_PROMPT.strip(),
            "max_output_tokens": SERMON_CRITIQUE_MAX_OUTPUT_TOKENS,
            "response_format": "json",
            "enable_thinking": True,
        },
        timeout=AI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def extract_json_payload(text_value: str):

    content = (text_value or "").strip()

    if not content:
        raise ValueError("Critique response is empty")

    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content.strip())

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)

    if not match:
        raise ValueError(f"Critique response is not valid JSON: {content[:800]}")

    return json.loads(match.group(0))


def normalize_list(value):

    if value is None:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    text_value = str(value).strip()
    return [text_value] if text_value else []


def resolve_target_sermon(preaching_date: str = ""):

    if preaching_date:
        row = fetch_one("""
            SELECT
                canonical_sermon_id,
                preaching_date,
                title,
                preacher_name,
                text_reference,
                serie,
                youtube_link,
                wordpress_link,
                media_link,
                download_link
            FROM gold_sermons
            WHERE preaching_date = :preaching_date
        """, {"preaching_date": preaching_date})

        if not row:
            raise ValueError(
                f"No sermon found in gold for preaching_date={preaching_date}"
            )

        return row

    return fetch_one("""
        SELECT
            canonical_sermon_id,
            preaching_date,
            title,
            preacher_name,
            text_reference,
            serie,
            youtube_link,
            wordpress_link,
            media_link,
            download_link
        FROM gold_sermons
        ORDER BY preaching_date DESC
        LIMIT 1
    """)


def fetch_latest_transcript(canonical_sermon_id: str):

    return fetch_one("""
        SELECT
            canonical_sermon_id,
            transcript_version,
            transcript_text,
            model_name,
            created_at
        FROM silver_transcripts
        WHERE canonical_sermon_id = :canonical_sermon_id
        ORDER BY transcript_version DESC
        LIMIT 1
    """, {"canonical_sermon_id": canonical_sermon_id})


def build_email_subject(sermon):

    return (
        "Resumo-critica da pregacao "
        f"{sermon['preaching_date']}"
    )


def build_email_body(sermon, transcript, critique_data, model_name: str):

    metadata_lines = [
        f"Data: {sermon.get('preaching_date', '')}",
        f"Titulo: {sermon.get('title', '')}",
        f"Pregador: {sermon.get('preacher_name', '')}",
        f"Texto: {sermon.get('text_reference', '')}",
        f"Serie: {sermon.get('serie', '')}",
        f"YouTube: {sermon.get('youtube_link', '')}",
        f"Pagina: {sermon.get('wordpress_link', '')}",
        f"Audio: {sermon.get('media_link', '')}",
        f"Transcript version: {transcript.get('transcript_version', '')}",
        f"Transcript model: {transcript.get('model_name', '')}",
        f"Critique model: {model_name}",
    ]

    metadata = "\n".join(line for line in metadata_lines if not line.endswith(": "))

    sections = [
        ("1. Breve resumo da mensagem", critique_data.get("breve_resumo_da_mensagem", "")),
        ("2. Tema central da pregacao", critique_data.get("tema_central_da_pregacao", "")),
        ("3. Estrutura da pregacao", critique_data.get("estrutura_da_pregacao", "")),
        ("4. Teses centrais enfatizadas", normalize_list(critique_data.get("teses_centrais_enfatizadas"))),
        ("5. Principais argumentos", normalize_list(critique_data.get("principais_argumentos"))),
        ("6. Pontos sem embasamento suficiente", normalize_list(critique_data.get("pontos_sem_embasamento_suficiente"))),
        ("7. Pontos polemicos ou fora do consenso", normalize_list(critique_data.get("pontos_polemicos_ou_fora_do_consenso"))),
        ("8. Aplicacoes utilizadas", normalize_list(critique_data.get("aplicacoes_utilizadas"))),
    ]

    section_blocks = []

    for title, content in sections:
        if isinstance(content, list):
            if content:
                body = "\n".join(f"- {item}" for item in content)
            else:
                body = "- Nao identificado com clareza na transcricao."
        else:
            body = str(content).strip() or "Nao identificado com clareza na transcricao."

        section_blocks.append(f"{title}\n{body}")

    critique_body = "\n\n".join(section_blocks).strip()

    return (
        f"{metadata}\n\n"
        f"{critique_body}\n"
    )


def send_email(subject: str, body: str):

    recipients = parse_recipients()

    if not EMAIL_SMTP_HOST:
        raise ValueError("ARCHIVE_EMAIL_SMTP_HOST is not configured")

    if not EMAIL_FROM:
        raise ValueError("ARCHIVE_EMAIL_FROM is not configured")

    if not recipients:
        raise ValueError("ARCHIVE_EMAIL_TO is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    print(
        f"Connecting to SMTP host={EMAIL_SMTP_HOST} "
        f"port={EMAIL_SMTP_PORT} tls={EMAIL_SMTP_USE_TLS}"
    )

    with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=60) as smtp:
        smtp.ehlo()

        if EMAIL_SMTP_USE_TLS:
            smtp.starttls()
            smtp.ehlo()

        if EMAIL_SMTP_USER:
            smtp.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)

        smtp.send_message(message)

    print(f"Email sent to {len(recipients)} recipient(s)")


def run(preaching_date: str = ""):

    input_ref = preaching_date or "latest-sermon-in-gold"
    run_id = begin_processing_run(
        "send_sermon_critique_email",
        input_ref,
    )

    try:
        print("Resolving target sermon from gold table...")
        sermon = resolve_target_sermon(preaching_date=preaching_date)

        if not sermon:
            print("No sermons found in gold_sermons. Skipping email workflow.")
            finish_processing_run(run_id, "success")
            return

        print(
            "Target sermon resolved | "
            f"date={sermon.get('preaching_date')} | "
            f"title={sermon.get('title', '')}"
        )

        print("Fetching latest transcript from silver_transcripts...")
        transcript = fetch_latest_transcript(sermon["canonical_sermon_id"])

        if not transcript or not (transcript.get("transcript_text") or "").strip():
            print(
                "No transcript found for target sermon. "
                "Skipping critique generation and email send."
            )
            finish_processing_run(run_id, "success")
            return

        print(
            "Transcript found | "
            f"version={transcript.get('transcript_version')} | "
            f"chars={len(transcript.get('transcript_text', ''))}"
        )

        print("Requesting detailed sermon critique from AI service...")
        critique = request_critique(transcript["transcript_text"])
        critique_text = (critique.get("summary_text", "") or "").strip()

        if not critique_text:
            raise ValueError("AI service returned an empty critique")

        critique_data = extract_json_payload(critique_text)

        print(
            "Critique generated | "
            f"chars={len(critique_text)} | "
            f"model={critique.get('model_name', 'unknown')}"
        )

        print("Building email payload...")
        subject = build_email_subject(sermon)
        body = build_email_body(
            sermon,
            transcript,
            critique_data,
            critique.get("model_name", "unknown"),
        )

        print("Sending email to configured recipients...")
        send_email(subject, body)

        finish_processing_run(run_id, "success")
        print("Weekly sermon critique email workflow completed")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--preaching-date", default="")
    args = parser.parse_args()

    run(preaching_date=(args.preaching_date or "").strip())

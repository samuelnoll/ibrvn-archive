from __future__ import annotations

import argparse
import smtplib
from email.message import EmailMessage

import requests

from shared.db import begin_processing_run, fetch_one, finish_processing_run
from shared.settings import (
    EMAIL_FROM,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PASSWORD,
    EMAIL_SMTP_PORT,
    EMAIL_SMTP_USE_TLS,
    EMAIL_SMTP_USER,
    EMAIL_TO,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENAI_TIMEOUT_SECONDS,
)


SERMON_CRITIQUE_SYSTEM_PROMPT = (
    "You are a careful reformed baptist Christian assistant writing a thoughtful sermon review "
    "in Brazilian Portuguese. Be detailed, very analytical, critical and useful. "
    "Always answer in Brazilian Portuguese. Do not invent information. "
    "Write a normal plain-text response, not JSON. Avoid Markdown tables. "
    "Organize the response with clear titled sections."
)

SERMON_CRITIQUE_PROMPT = """
Analise a transcricao a seguir e produza uma critica detalhada em texto normal.
Organize a resposta com secoes claras para:
1. Breve resumo da mensagem
2. Tema central da pregacao
3. Estrutura da pregacao
4. Teses centrais enfatizadas
5. Principais argumentos
6. Pontos sem embasamento suficiente
7. Pontos polemicos ou fora do consenso
8. Aplicacoes utilizadas

Seja especifico e cite o conteudo real da transcricao. Nao seja generico.
"""

SERMON_CRITIQUE_MAX_OUTPUT_TOKENS = 6000


def parse_recipients():

    return [
        item.strip()
        for item in EMAIL_TO.split(",")
        if item.strip()
    ]


def request_critique(transcript_text: str):

    if not OPENAI_API_KEY:
        raise ValueError("ARCHIVE_OPENAI_API_KEY is not configured")

    response = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": SERMON_CRITIQUE_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        f"{SERMON_CRITIQUE_PROMPT.strip()}\n\n"
                        f"TRANSCRICAO:\n{transcript_text}"
                    ),
                },
            ],
            "max_completion_tokens": SERMON_CRITIQUE_MAX_OUTPUT_TOKENS,
        },
        timeout=OPENAI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices", []) or []

    if not choices:
        raise ValueError("OpenAI response does not contain choices")

    message = choices[0].get("message", {}) or {}
    critique_text = (message.get("content", "") or "").strip()

    if not critique_text:
        raise ValueError("OpenAI returned an empty critique")

    return {
        "model_name": payload.get("model", OPENAI_MODEL),
        "critique_text": critique_text,
    }


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


def build_email_body(sermon, transcript, critique_text: str, model_name: str):

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

    return (
        f"{metadata}\n\n"
        f"{critique_text.strip()}\n"
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
        critique_text = (critique.get("critique_text", "") or "").strip()

        if not critique_text:
            raise ValueError("AI service returned an empty critique")

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
            critique_text,
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

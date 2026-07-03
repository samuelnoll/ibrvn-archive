from __future__ import annotations

import argparse
import html
import smtplib
from email.message import EmailMessage

import markdown
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


SERMON_CRITIQUE_SYSTEM_PROMPT = """
Você é um assistente reformado batista, analítico e criterioso. A teologia a ser considerada correta é da linha batista reformada equilibrada.

Quero uma crítica real, não apenas um resumo respeitoso. Se houver afirmações vagas, saltos argumentativos, aplicações pouco sustentadas ou pontos teológicos discutíveis, destaque isso com clareza e equilíbrio. Não suavize demais a análise.

A sua resposta deve conter os seguintes itens:

No começo, intitulado 'Resumo da pregação', faça um resumo em 3 parágrafos no máximo contendo sobre o que foi essa pregação e a tese principal. Logo após esse resumo, cite as teses (focos) enfatizadas da pregação.

Depois, intitulado 'Avaliação crítica', faça uma avaliação crítica a partir dos seguintes títulos: alinhamento teológico dos enfoques, coerência do sermão, força dos argumentos, qualidade da fundamentação bíblica, clareza das aplicações e possíveis fragilidades no raciocínio. Algo em torno de 3 parágrafos por título tem um bom tamanho.

No final, intitulado 'Análise geral', finalize com um veredito final com os pontos fortes e fracos de no máximo 2 parágrafos.

Será enviado a seguir a transcrição da pregação.
"""

SERMON_CRITIQUE_PROMPT = ""

SERMON_CRITIQUE_MAX_OUTPUT_TOKENS = 15000
SERMON_CRITIQUE_REASONING_EFFORT = "high"


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
        f"{OPENAI_BASE_URL}/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "instructions": SERMON_CRITIQUE_SYSTEM_PROMPT,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"{SERMON_CRITIQUE_PROMPT.strip()}\n\n"
                                f"TRANSCRIÇÃO:\n{transcript_text}"
                            ),
                        }
                    ],
                },
            ],
            "max_output_tokens": SERMON_CRITIQUE_MAX_OUTPUT_TOKENS,
            "reasoning": {
                "effort": SERMON_CRITIQUE_REASONING_EFFORT,
            },
            "text": {
                "format": {
                    "type": "text",
                }
            },
        },
        timeout=OPENAI_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            "OpenAI /responses request failed "
            f"status={response.status_code} body={response.text}"
        )

    payload = response.json()
    critique_text = (payload.get("output_text", "") or "").strip()

    if not critique_text:
        output_items = payload.get("output", []) or []

        for item in output_items:
            if item.get("type") != "message":
                continue

            for content_item in item.get("content", []) or []:
                if content_item.get("type") != "output_text":
                    continue

                critique_text = (content_item.get("text", "") or "").strip()

                if critique_text:
                    break

            if critique_text:
                break

    if not critique_text:
        raise ValueError(
            "OpenAI returned an empty critique "
            f"(status={payload.get('status')}, incomplete_details={payload.get('incomplete_details')})"
        )

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


def build_email_html(body: str):

    sections = body.split("\n\n", 1)
    metadata_block = sections[0].strip()
    critique_block = sections[1].strip() if len(sections) > 1 else ""

    metadata_items = []

    for line in metadata_block.splitlines():
        cleaned = line.strip()

        if not cleaned:
            continue

        if ": " in cleaned:
            label, value = cleaned.split(": ", 1)
            metadata_items.append(
                f"<li><strong>{html.escape(label)}:</strong> {html.escape(value)}</li>"
            )
        else:
            metadata_items.append(f"<li>{html.escape(cleaned)}</li>")

    metadata_html = "\n".join(metadata_items)

    critique_html = markdown.markdown(
        critique_block,
        extensions=[
            "extra",
            "sane_lists",
            "nl2br",
        ],
    )

    return f"""
<html>
  <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #222;">
    <div style="margin-bottom: 24px;">
      <h2 style="margin: 0 0 12px 0; font-size: 20px;">Dados da avaliação</h2>
      <ul style="margin: 0; padding-left: 20px;">
        {metadata_html}
      </ul>
    </div>
    <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
    <div>
      {critique_html}
    </div>
  </body>
</html>
""".strip()


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
    message.add_alternative(build_email_html(body), subtype="html")

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

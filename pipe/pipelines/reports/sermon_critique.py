from __future__ import annotations

import argparse
import html
import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import markdown
import requests

from shared.db import (
    begin_processing_run,
    execute,
    fetch_one,
    finish_processing_run,
    initialize_database,
)
from shared.settings import (
    EMAIL_FROM,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PASSWORD,
    EMAIL_SMTP_PORT,
    EMAIL_SMTP_USE_TLS,
    EMAIL_SMTP_USER,
    EMAIL_TO,
    LOCAL_TIMEZONE,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENAI_TIMEOUT_SECONDS,
    WHATSAPP_CRITIQUE_TARGET_LABEL,
    WHATSAPP_CRITIQUE_TARGET_TYPE,
    WHATSAPP_CRITIQUE_TARGET_VALUE,
    WHATSAPP_SCHEDULER_BASE_URL,
    WHATSAPP_SCHEDULER_TIMEOUT_SECONDS,
)


SERMON_CRITIQUE_SYSTEM_PROMPT = """
Voce e um assistente batista reformado, analitico, criterioso e atento a detalhes. Sua tarefa e fazer uma critica realista, fria e extremamente honesta de uma pregacao a partir da transcricao fornecida.

Voce nao deve tentar equilibrar artificialmente pontos positivos e negativos. A analise deve refletir a realidade da pregacao. Se a pregacao for ruim, a maior parte da analise deve ser negativa. Se for boa, a maior parte da analise pode ser positiva. Se houver poucos acertos relevantes, nao invente nem amplie pontos positivos pequenos apenas para parecer equilibrado.

Nao suavize a analise. Nao use elogios genericos, compensatorios ou pouco relevantes. So mencione um ponto positivo se ele for realmente significativo para a qualidade da pregacao. Acertos obvios, triviais, superficiais ou meramente formais nao devem receber destaque, especialmente se houver problemas teologicos, hermeneuticos ou argumentativos mais graves.

De peso proporcional a gravidade dos problemas. Um erro teologico serio, uma distorcao do texto biblico, uma aplicacao moralista, uma tese sem base exegetica ou uma acusacao injusta contra uma posicao teologica plausivel deve pesar mais do que varios acertos menores. A analise nao deve contar pontos positivos e negativos como se todos tivessem o mesmo valor.

Voce deve ser especialmente atento a:

* enfoques que nao surgem claramente do texto biblico pregado;
* frases que ensinam algo sem fundamentacao biblica suficiente;
* uso inadequado, superficial ou seletivo de textos biblicos;
* saltos argumentativos;
* afirmacoes vagas ou emocionalmente fortes, mas pouco demonstradas;
* aplicacoes desconectadas do sentido do texto;
* desprezo, caricatura ou ataque injusto a uma vertente teologica plausivel;
* moralismo, pragmatismo, psicologizacao ou antropocentrismo;
* ausencia de Cristo, do evangelho, da graca, da obra redentiva ou da centralidade biblica quando isso for relevante ao texto.

A sua resposta deve conter as seguintes secoes: resumo da pregacao, avaliacao critica e analise geral.

'Resumo da pregacao'

Faca um resumo em ate 3 paragrafos dizendo sobre o que foi a pregacao, qual foi sua tese principal e quais foram os focos mais enfatizados.

Depois do resumo, liste as principais teses ou enfases da pregacao. Nao avalie ainda; apenas descreva.

'Avaliacao critica'

Faca uma avaliacao critica usando os seguintes titulos:

* Coerencia com os enfoques do texto base
* Qualidade hermeneutica
* Forca dos argumentos
* Qualidade da fundamentacao biblica
* Qualidades teologicas
* Fragilidades teologicas

Em cada titulo, escreva em paragrafos. Nao force a presenca de pontos positivos e negativos em cada secao. Se a secao tiver apenas problemas relevantes, trate apenas dos problemas. Se tiver apenas acertos relevantes, trate apenas dos acertos. Se os acertos forem pequenos demais para serem importantes, ignore-os.

Em cada secao, priorize os pontos mais relevantes. Comece pelos problemas mais graves quando eles existirem. Nao esconda problemas importantes no meio de observacoes brandas.

Quando identificar um problema, explique no texto corrido:

* qual e o problema;
* por que ele e problematico;
* qual trecho, ideia ou linha de raciocinio da pregacao levou a essa avaliacao;
* qual seria uma forma mais biblica, hermeneutica ou teologicamente cuidadosa de tratar o ponto, quando isso for possivel.

Classifique implicitamente a gravidade dos problemas pela forma como escreve. Problemas graves devem receber mais espaco e enfase. Problemas menores nao devem ocupar o mesmo espaco que problemas centrais.

'Analise geral'

Finalize com um veredito final em no maximo 2 paragrafos.

O veredito deve ser proporcional a qualidade real da pregacao. Nao tente terminar de forma encorajadora se a pregacao foi fraca, problematica ou teologicamente perigosa. Se os problemas forem graves, diga isso claramente. Se os acertos forem poucos ou secundarios, nao os apresente como se compensassem os problemas centrais.

No veredito, deixe claro se a pregacao foi:

* fiel e bem conduzida;
* parcialmente util, mas com problemas importantes;
* fraca;
* confusa;
* seriamente problematica;
* ou teologicamente perigosa.

Sera enviada a seguir a transcricao da pregacao.
"""

SERMON_CRITIQUE_PROMPT = ""
SERMON_CRITIQUE_MAX_OUTPUT_TOKENS = 20000
SERMON_CRITIQUE_REASONING_EFFORT = "medium"
WHATSAPP_MESSAGE_TITLE = "Mensagem para Critica da pregacao"


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
                                f"TRANSCRICAO:\n{transcript_text}"
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


def fetch_latest_critique(canonical_sermon_id: str):

    return fetch_one("""
        SELECT
            canonical_sermon_id,
            critique_version,
            transcript_version,
            critique_text,
            model_name,
            created_at
        FROM silver_critique
        WHERE canonical_sermon_id = :canonical_sermon_id
        ORDER BY critique_version DESC
        LIMIT 1
    """, {"canonical_sermon_id": canonical_sermon_id})


def save_critique(
    canonical_sermon_id: str,
    transcript_version: int | None,
    critique_text: str,
    model_name: str,
):

    row = fetch_one("""
        SELECT COALESCE(MAX(critique_version), 0) + 1 AS next_version
        FROM silver_critique
        WHERE canonical_sermon_id = :canonical_sermon_id
    """, {"canonical_sermon_id": canonical_sermon_id})
    critique_version = int((row or {}).get("next_version") or 1)

    execute("""
        INSERT INTO silver_critique (
            canonical_sermon_id,
            critique_version,
            transcript_version,
            critique_text,
            model_name,
            created_at
        )
        VALUES (
            :canonical_sermon_id,
            :critique_version,
            :transcript_version,
            :critique_text,
            :model_name,
            :created_at
        )
    """, {
        "canonical_sermon_id": canonical_sermon_id,
        "critique_version": critique_version,
        "transcript_version": transcript_version,
        "critique_text": critique_text,
        "model_name": model_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return critique_version


def build_email_subject(sermon):

    return (
        "[Homelab] Analise critica da pregacao de "
        f"{sermon['preaching_date']}"
    )


def build_email_body(sermon, transcript, critique):

    transcript = transcript or {}
    metadata_lines = [
        f"Data: {sermon.get('preaching_date', '')}",
        f"Titulo: {sermon.get('title', '')}",
        f"Pregador: {sermon.get('preacher_name', '')}",
        f"Texto: {sermon.get('text_reference', '')}",
        f"Serie: {sermon.get('serie', '')}",
        f"YouTube: {sermon.get('youtube_link', '')}",
        f"Pagina: {sermon.get('wordpress_link', '')}",
        f"Audio: {sermon.get('media_link', '')}",
        f"Versao da transcricao: {transcript.get('transcript_version', '')}",
        f"Modelo da transcricao: {transcript.get('model_name', '')}",
        f"Versao da critica: {critique.get('critique_version', '')}",
        f"Modelo da critica: {critique.get('model_name', '')}",
    ]

    metadata = "\n".join(
        line for line in metadata_lines
        if not line.endswith(": ")
    )

    return (
        f"{metadata}\n\n"
        f"{(critique.get('critique_text', '') or '').strip()}\n"
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
      <h2 style="margin: 0 0 12px 0; font-size: 20px;">Dados da avaliacao</h2>
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


def build_whatsapp_message(sermon, transcript, critique):

    transcript = transcript or {}
    critique_text = (critique.get("critique_text", "") or "").strip()
    metadata_lines = [
        "*Critica da pregacao*",
        f"*Data:* {sermon.get('preaching_date', '')}",
        f"*Titulo:* {sermon.get('title', '')}",
        f"*Pregador:* {sermon.get('preacher_name', '')}",
        f"*Texto:* {sermon.get('text_reference', '')}",
        f"*Serie:* {sermon.get('serie', '')}",
        f"*YouTube:* {sermon.get('youtube_link', '')}",
        f"*Pagina:* {sermon.get('wordpress_link', '')}",
        f"*Audio:* {sermon.get('media_link', '')}",
        f"*Versao da transcricao:* {transcript.get('transcript_version', '')}",
        f"*Modelo da transcricao:* {transcript.get('model_name', '')}",
        f"*Versao da critica:* {critique.get('critique_version', '')}",
        f"*Modelo da critica:* {critique.get('model_name', '')}",
        "",
        critique_text,
    ]
    return "\n".join(metadata_lines).strip()


def build_whatsapp_schedule_payload(sermon, transcript, critique):

    if not WHATSAPP_SCHEDULER_BASE_URL:
        raise ValueError("ARCHIVE_WHATSAPP_SCHEDULER_BASE_URL is not configured")

    if not WHATSAPP_CRITIQUE_TARGET_VALUE:
        raise ValueError("ARCHIVE_WHATSAPP_CRITIQUE_TARGET_VALUE is not configured")

    send_at = (
        datetime.now(ZoneInfo(LOCAL_TIMEZONE)) + timedelta(minutes=5)
    ).strftime("%Y-%m-%dT%H:%M")

    return {
        "title": f"{WHATSAPP_MESSAGE_TITLE} {sermon.get('preaching_date', '')}".strip(),
        "target_type": WHATSAPP_CRITIQUE_TARGET_TYPE or "group",
        "target_value": WHATSAPP_CRITIQUE_TARGET_VALUE,
        "target_label": WHATSAPP_CRITIQUE_TARGET_LABEL or "Critica da pregacao",
        "message_text": build_whatsapp_message(sermon, transcript, critique),
        "send_at": send_at,
        "recurrence": "once",
        "image_path": None,
        "image_name": None,
        "is_active": True,
    }


def create_whatsapp_schedule(payload: dict):

    url = f"{WHATSAPP_SCHEDULER_BASE_URL}/api/schedules"
    print(f"WhatsApp scheduler request url={url}")
    print(
        "WhatsApp scheduler request metadata "
        f"timeout_seconds={WHATSAPP_SCHEDULER_TIMEOUT_SECONDS} "
        f"message_length={len(payload.get('message_text', ''))}"
    )
    print(
        "WhatsApp scheduler request payload="
        f"{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=WHATSAPP_SCHEDULER_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        print(
            "WhatsApp scheduler request failed before response "
            f"error={exc!r}"
        )
        raise

    print(
        "WhatsApp scheduler response "
        f"status={response.status_code} body={response.text}"
    )

    if response.status_code >= 400:
        raise RuntimeError(
            "WhatsApp scheduler request failed "
            f"status={response.status_code} body={response.text}"
        )

    data = response.json()
    print(
        "WhatsApp scheduler parsed response "
        f"payload={json.dumps(data, ensure_ascii=False)}"
    )
    return data


def run_generate(preaching_date: str = ""):

    initialize_database()
    input_ref = preaching_date or "latest-sermon-in-gold"
    run_id = begin_processing_run(
        "generate_sermon_critique",
        input_ref,
    )

    try:
        print("Resolving target sermon from gold table...")
        sermon = resolve_target_sermon(preaching_date=preaching_date)

        if not sermon:
            print("No sermons found in gold_sermons. Skipping critique generation.")
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
                "Skipping critique generation."
            )
            finish_processing_run(run_id, "success")
            return

        print(
            "Transcript found | "
            f"version={transcript.get('transcript_version')} | "
            f"chars={len(transcript.get('transcript_text', ''))}"
        )

        print("Requesting detailed sermon critique from OpenAI Responses API...")
        critique = request_critique(transcript["transcript_text"])
        critique_text = (critique.get("critique_text", "") or "").strip()

        if not critique_text:
            raise ValueError("OpenAI returned an empty critique")

        print(
            "Critique generated | "
            f"chars={len(critique_text)} | "
            f"model={critique.get('model_name', 'unknown')}"
        )

        critique_version = save_critique(
            canonical_sermon_id=sermon["canonical_sermon_id"],
            transcript_version=transcript.get("transcript_version"),
            critique_text=critique_text,
            model_name=critique.get("model_name", "unknown"),
        )

        print(
            "Critique saved to silver_critique | "
            f"version={critique_version} | "
            f"canonical_sermon_id={sermon['canonical_sermon_id']}"
        )

        finish_processing_run(run_id, "success")
        print("Sermon critique generation workflow completed")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


def run_send_email(preaching_date: str = "", skip_email_report: bool = False):

    initialize_database()
    input_ref = preaching_date or "latest-sermon-in-gold"
    run_id = begin_processing_run(
        "send_sermon_critique_email",
        input_ref,
    )

    try:
        if skip_email_report:
            print("Skipping sermon critique email report because skip_email_report=true.")
            finish_processing_run(run_id, "success")
            return

        print("Resolving target sermon from gold table for email report...")
        sermon = resolve_target_sermon(preaching_date=preaching_date)

        if not sermon:
            print("No sermons found in gold_sermons. Skipping email report.")
            finish_processing_run(run_id, "success")
            return

        critique = fetch_latest_critique(sermon["canonical_sermon_id"])

        if not critique or not (critique.get("critique_text") or "").strip():
            print("No critique found in silver_critique. Skipping email report.")
            finish_processing_run(run_id, "success")
            return

        transcript = fetch_latest_transcript(sermon["canonical_sermon_id"])

        print("Building email payload from latest saved critique...")
        subject = build_email_subject(sermon)
        body = build_email_body(sermon, transcript, critique)

        print("Sending email to configured recipients...")
        send_email(subject, body)

        finish_processing_run(run_id, "success")
        print("Sermon critique email workflow completed")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


def run_schedule_whatsapp(preaching_date: str = "", skip_whatsapp_report: bool = False):

    initialize_database()
    input_ref = preaching_date or "latest-sermon-in-gold"
    run_id = begin_processing_run(
        "schedule_sermon_critique_whatsapp",
        input_ref,
    )

    try:
        if skip_whatsapp_report:
            print(
                "Skipping sermon critique WhatsApp report because "
                "skip_whatsapp_report=true."
            )
            finish_processing_run(run_id, "success")
            return

        print("Resolving target sermon from gold table for WhatsApp report...")
        sermon = resolve_target_sermon(preaching_date=preaching_date)

        if not sermon:
            print("No sermons found in gold_sermons. Skipping WhatsApp report.")
            finish_processing_run(run_id, "success")
            return

        critique = fetch_latest_critique(sermon["canonical_sermon_id"])

        if not critique or not (critique.get("critique_text") or "").strip():
            print("No critique found in silver_critique. Skipping WhatsApp report.")
            finish_processing_run(run_id, "success")
            return

        transcript = fetch_latest_transcript(sermon["canonical_sermon_id"])

        print("Building WhatsApp scheduler payload from latest saved critique...")
        payload = build_whatsapp_schedule_payload(sermon, transcript, critique)
        response_payload = create_whatsapp_schedule(payload)

        print(
            "WhatsApp schedule created successfully | "
            f"response={json.dumps(response_payload, ensure_ascii=False)}"
        )

        finish_processing_run(run_id, "success")
        print("Sermon critique WhatsApp scheduling workflow completed")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


def run(
    action: str,
    preaching_date: str = "",
    skip_email_report: bool = False,
    skip_whatsapp_report: bool = False,
):

    normalized_action = (action or "").strip().lower()

    if normalized_action == "generate":
        run_generate(preaching_date=preaching_date)
        return

    if normalized_action == "email":
        run_send_email(
            preaching_date=preaching_date,
            skip_email_report=skip_email_report,
        )
        return

    if normalized_action == "whatsapp":
        run_schedule_whatsapp(
            preaching_date=preaching_date,
            skip_whatsapp_report=skip_whatsapp_report,
        )
        return

    raise ValueError(f"Unsupported action={action}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--action",
        required=True,
        choices=["generate", "email", "whatsapp"],
    )
    parser.add_argument("--preaching-date", default="")
    parser.add_argument("--skip-email-report", action="store_true")
    parser.add_argument("--skip-whatsapp-report", action="store_true")
    args = parser.parse_args()

    run(
        action=args.action,
        preaching_date=(args.preaching_date or "").strip(),
        skip_email_report=args.skip_email_report,
        skip_whatsapp_report=args.skip_whatsapp_report,
    )

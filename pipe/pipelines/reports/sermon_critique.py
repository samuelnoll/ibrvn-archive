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
Você é um assistente batista reformado, analítico, criterioso, teologicamente instruído e extremamente atento a detalhes. Sua tarefa é examinar a transcrição de uma pregação e selecionar suas principais afirmações, argumentos, possíveis erros e inconsistências para discussão em um grupo de estudo teológico.

O objetivo NÃO é produzir uma crítica com julgamentos de valor, nem determinar se a pregação foi boa ou ruim. Sua função é identificar e organizar os elementos mais relevantes para que um grupo intelectualmente preparado possa avaliá-los e discuti-los.

PRINCÍPIOS GERAIS

1. Priorize a fidelidade ao que o pregador realmente disse. Não atribua a ele ideias que não estejam presentes na transcrição. Diferencie citações literais de paráfrases.

2. Seja extremamente seletivo. Inclua SOMENTE pontos substanciais, que realmente mereçam discussão teológica, hermenêutica ou argumentativa. Não registre observações triviais, óbvias, redundantes ou secundárias.

3. Os limites de itens são TETOS, NÃO METAS. Não tente preencher uma seção até seu limite. Uma seção pode ter apenas 1 ou 2 itens, ou nenhum, caso não existam observações suficientemente relevantes. Antes de incluir qualquer item, pergunte-se: "Esse ponto realmente merece o tempo de discussão de um grupo teologicamente preparado?" Se a resposta for não, descarte-o.

4. Não busque equilíbrio artificial entre acertos e problemas. Não suavize nem omita afirmações potencialmente problemáticas.

5. Não transforme divergências teológicas legítimas em erros definitivos. Diferencie afirmações aparentemente contrárias à Escritura, interpretações controversas e afirmações simplesmente não demonstradas.

6. Evite explicações longas, elogios, repreensões, recomendações e vereditos. Cada item deve apresentar uma ideia específica, com apenas a contextualização necessária para sua compreensão.

7. Considere especialmente a tradição batista reformada, mas não trate interpretações plausíveis de outras tradições cristãs como erros apenas por divergirem dessa perspectiva.

ESTRUTURA DA RESPOSTA

Use headings Markdown (##) sem numeração para todas as seis seções. Coloque uma linha horizontal (---) imediatamente antes de cada novo heading, exceto o primeiro.

## Resumo da pregação

Escreva um único parágrafo resumindo o assunto, o texto bíblico principal, a tese central e as ênfases predominantes.

Ao final, classifique brevemente a pregação como predominantemente:

- Expositiva: quando a tese e a argumentação principal surgem do próprio texto bíblico.
- Temática: quando o texto serve principalmente como ponto de partida para desenvolver um tema mais amplo.

Caso apresente características dos dois modelos, indique qual predomina e por quê.

---

## Fluxo lógico da pregação

Reconstrua a progressão das principais ideias da pregação, desde a introdução até a conclusão.

Apresente o fluxo em uma sequência de frases curtas, conectadas por setas (→), em vez de tópicos ou parágrafos explicativos.

O objetivo é visualizar como o pregador desenvolveu seu pensamento, quais foram as transições entre os assuntos e como chegou às conclusões.

Registre o fluxo efetivamente apresentado, mesmo que contenha saltos argumentativos ou mudanças bruscas de assunto.

---

## Grandes teses defendidas

Liste NO MÁXIMO 4 das principais teses ou ensinamentos defendidos pelo pregador.

- Formule cada tese como uma afirmação, e não como um assunto genérico.
- Priorize as teses centrais e mais enfatizadas.
- Preserve o sentido efetivamente defendido pelo pregador.
- Não avalie se são verdadeiras ou falsas.
- Não inclua teses secundárias apenas para atingir o limite de 4.

---

## Argumentos levantados

Liste NO MÁXIMO 8 dos argumentos mais relevantes utilizados pelo pregador para sustentar suas teses.

- Identifique a afirmação defendida e o raciocínio utilizado para sustentá-la.
- Registre passagens bíblicas, analogias, exemplos ou relações de causa e efeito utilizados.
- Destaque pressupostos não demonstrados, saltos lógicos ou conclusões que aparentemente ultrapassem as premissas.
- Não refute os argumentos; apenas apresente sua estrutura e os pontos que merecem discussão.
- Não inclua argumentos repetitivos, triviais ou pouco relevantes apenas para atingir o limite de 8.

---

## Frases aparentemente incorretas teologicamente

Selecione NO MÁXIMO 6 das afirmações mais relevantes que possam suscitar problemas teológicos, hermenêuticos ou doutrinários.

Preste atenção especialmente a:

- Afirmações aparentemente contrárias ao ensino bíblico.
- Interpretações que extrapolam o sentido do texto.
- Generalizações teológicas indevidas.
- Afirmações categóricas sobre assuntos teologicamente discutíveis.
- Frases teologicamente ambíguas ou imprecisas.
- Contradições internas da pregação.
- Caricaturas ou ataques injustos a posições teológicas plausíveis.
- Afirmações feitas com convicção, mas sem fundamentação bíblica suficiente.

Para cada item, apresente preferencialmente uma frase literal do pregador e acrescente uma observação breve identificando o possível problema ou a questão teológica envolvida.

Não é necessário demonstrar que a afirmação esteja errada. Basta existir uma razão concreta para considerá-la digna de exame. Não desenvolva refutações nem formule conclusões definitivas.

Priorize os problemas mais substanciais e potencialmente graves. Não inclua pequenas imprecisões ou controvérsias artificiais apenas para atingir o limite de 6.

---

## Aplicações: aproximação do ensino com a realidade dos ouvintes

Selecione NO MÁXIMO 3 das aplicações mais relevantes realizadas pelo pregador.

Identifique:

- As principais aplicações práticas propostas.
- As situações humanas ou experiências utilizadas para aproximar o texto da realidade.
- As relações estabelecidas entre doutrina e vida cristã.
- Aplicações cuja conexão com o texto bíblico não ficou demonstrada.
- Possíveis aplicações moralistas, pragmáticas ou antropocêntricas, quando houver fundamento concreto para essa observação.

Priorize o registro das aplicações efetivamente feitas, sem avaliar sua eficácia emocional ou formular aplicações alternativas.

Não inclua aplicações genéricas, repetitivas ou pouco significativas apenas para atingir o limite de 3.

REGRAS FINAIS

- Todas as seis seções devem possuir headings Markdown (##), sem numeração.
- Coloque uma linha horizontal (---) antes de cada heading, exceto o primeiro.
- Nas seções Grandes teses, Argumentos, Frases aparentemente incorretas e Aplicação, todos os itens devem ser numerados (1., 2., 3. etc.).
- O fluxo lógico deve aparecer exclusivamente em frases conectadas por setas (→).
- Limites máximos: Grandes teses (4), Argumentos (8), Frases aparentemente incorretas (6) e Aplicação (3).
- OS LIMITES NÃO SÃO METAS. É preferível apresentar 2 observações realmente relevantes a 6 observações de importância desigual. Não inclua itens para completar listas.
- Cada item deve ser curto, preferencialmente de uma a três frases.
- Não repita observações desnecessariamente.
- Não invente passagens bíblicas, citações, argumentos ou intenções do pregador.
- Utilize aspas somente para citações literais.
- Considere possíveis erros de transcrição antes de identificar afirmações problemáticas.
- Não acrescente conclusão, análise geral, classificação de qualidade ou veredito final.

O resultado deve ser uma pauta concisa, criteriosa e intelectualmente relevante para discussão teológica, não uma crítica já concluída.

Será enviada a seguir a transcrição da pregação.
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

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
Você é um assistente batista reformado, analítico, criterioso e atento a detalhes. Sua tarefa é fazer uma crítica realista, fria e extremamente honesta de uma pregação a partir da transcrição fornecida.

Você não deve tentar equilibrar artificialmente pontos positivos e negativos. A análise deve refletir a realidade da pregação. Se a pregação for ruim, a maior parte da análise deve ser negativa. Se for boa, a maior parte da análise pode ser positiva. Se houver poucos acertos relevantes, não invente nem amplie pontos positivos pequenos apenas para parecer equilibrado.

Não suavize a análise. Não use elogios genéricos, compensatórios ou pouco relevantes. Só mencione um ponto positivo se ele for realmente significativo para a qualidade da pregação. Acertos óbvios, triviais, superficiais ou meramente formais não devem receber destaque, especialmente se houver problemas teológicos, hermenêuticos ou argumentativos mais graves.

Dê peso proporcional à gravidade dos problemas. Um erro teológico sério, uma distorção do texto bíblico, uma aplicação moralista, uma tese sem base exegética ou uma acusação injusta contra uma posição teológica plausível deve pesar mais do que vários acertos menores. A análise não deve contar pontos positivos e negativos como se todos tivessem o mesmo valor.

Você deve ser especialmente atento a:

* enfoques que não surgem claramente do texto bíblico pregado;
* frases que ensinam algo sem fundamentação bíblica suficiente;
* uso inadequado, superficial ou seletivo de textos bíblicos;
* saltos argumentativos;
* afirmações vagas ou emocionalmente fortes, mas pouco demonstradas;
* aplicações desconectadas do sentido do texto;
* desprezo, caricatura ou ataque injusto a uma vertente teológica plausível;
* moralismo, pragmatismo, psicologização ou antropocentrismo;
* ausência de Cristo, do evangelho, da graça, da obra redentiva ou da centralidade bíblica quando isso for relevante ao texto.

A sua resposta deve conter as seguintes seções: resumo da pregação, avaliação crítica e análise geral.

'Resumo da pregação'

Faça um resumo em até 3 parágrafos dizendo sobre o que foi a pregação, qual foi sua tese principal e quais foram os focos mais enfatizados.

Depois do resumo, liste as principais teses ou ênfases da pregação. Não avalie ainda; apenas descreva.

'Avaliação crítica'

Faça uma avaliação crítica usando os seguintes títulos:

* Coerência com os enfoques do texto base
* Qualidade hermenêutica
* Força dos argumentos
* Qualidade da fundamentação bíblica
* Qualidades teológicas
* Fragilidades teológicas

Em cada título, escreva em parágrafos. Não force a presença de pontos positivos e negativos em cada seção. Se a seção tiver apenas problemas relevantes, trate apenas dos problemas. Se tiver apenas acertos relevantes, trate apenas dos acertos. Se os acertos forem pequenos demais para serem importantes, ignore-os.

Em cada seção, priorize os pontos mais relevantes. Comece pelos problemas mais graves quando eles existirem. Não esconda problemas importantes no meio de observações brandas.

Quando identificar um problema, explique no texto corrido:

* qual é o problema;
* por que ele é problemático;
* qual trecho, ideia ou linha de raciocínio da pregação levou a essa avaliação;
* qual seria uma forma mais bíblica, hermenêutica ou teologicamente cuidadosa de tratar o ponto, quando isso for possível.

Classifique implicitamente a gravidade dos problemas pela forma como escreve. Problemas graves devem receber mais espaço e ênfase. Problemas menores não devem ocupar o mesmo espaço que problemas centrais.

'Análise geral'

Finalize com um veredito final em no máximo 2 parágrafos.

O veredito deve ser proporcional à qualidade real da pregação. Não tente terminar de forma encorajadora se a pregação foi fraca, problemática ou teologicamente perigosa. Se os problemas forem graves, diga isso claramente. Se os acertos forem poucos ou secundários, não os apresente como se compensassem os problemas centrais.

No veredito, deixe claro se a pregação foi:

* fiel e bem conduzida;
* parcialmente útil, mas com problemas importantes;
* fraca;
* confusa;
* seriamente problemática;
* ou teologicamente perigosa.

Será enviada a seguir a transcrição da pregação.
"""

SERMON_CRITIQUE_PROMPT = ""

SERMON_CRITIQUE_MAX_OUTPUT_TOKENS = 20000
SERMON_CRITIQUE_REASONING_EFFORT = "medium"


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
        "[Homelab] Análise crítica da pregação de "
        f"{sermon['preaching_date']}"
    )


def build_email_body(sermon, transcript, critique_text: str, model_name: str):

    metadata_lines = [
        f"Data: {sermon.get('preaching_date', '')}",
        f"Título: {sermon.get('title', '')}",
        f"Pregador: {sermon.get('preacher_name', '')}",
        f"Texto: {sermon.get('text_reference', '')}",
        f"Série: {sermon.get('serie', '')}",
        f"YouTube: {sermon.get('youtube_link', '')}",
        f"Página: {sermon.get('wordpress_link', '')}",
        f"Áudio: {sermon.get('media_link', '')}",
        f"Versão da transcrição: {transcript.get('transcript_version', '')}",
        f"Modelo da transcrição: {transcript.get('model_name', '')}",
        f"Modelo da : {model_name}",
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

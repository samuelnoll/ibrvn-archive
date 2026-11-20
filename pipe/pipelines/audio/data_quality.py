from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text

from shared.db import fetch_all, get_engine, initialize_database, utc_now_iso
from shared.settings import (
    LOCAL_TIMEZONE,
    QUALITY_CHECK_EXTERNAL_LINKS,
    QUALITY_LINK_TIMEOUT_SECONDS,
    QUALITY_MAX_AUDIO_MINUTES,
    QUALITY_MIN_AUDIO_MINUTES,
    QUALITY_SHORT_TRANSCRIPT_WORDS,
    QUALITY_START_DATE,
    QUALITY_SUNDAY_GRACE_DAYS,
)


RULE_VERSION = "1"
MINIMUM_SUNDAY_SCOPE_START = date(2009, 1, 1)

METRICS = [
    ("total_sermons", "Pregações no catálogo", "info", "Total publicado na camada gold."),
    ("missing_mp3", "Sem arquivo MP3", "critical", "Pregações sem arquivo de áudio local."),
    ("mp3_file_missing", "MP3 referenciado, mas ausente", "critical", "O banco aponta para um arquivo local que não existe."),
    ("mp3_without_transcript", "Com MP3, sem transcrição", "warning", "Áudio local disponível sem transcrição."),
    ("youtube_link", "Com link para YouTube", "good", "Cobertura de links para o YouTube."),
    ("wordpress_link", "Com link para o site", "good", "Cobertura de links para o site da igreja."),
    ("no_external_source", "Sem fonte externa", "critical", "Sem link para o site e sem link para o YouTube."),
    ("missing_duration", "Sem duração calculada", "warning", "Áudio local sem duração registrada."),
    ("suspicious_duration", "Duração suspeita", "warning", "Áudio fora da faixa de duração configurada."),
    ("missing_title", "Sem título", "warning", "Pregações sem título."),
    ("missing_preacher", "Sem pregador", "warning", "Pregações sem pregador identificado."),
    ("missing_bible_reference", "Sem referência bíblica", "warning", "Pregações sem texto bíblico identificado."),
    ("missing_series", "Sem série", "info", "Informativo: nem toda pregação pertence a uma série."),
    ("short_transcript", "Transcrição muito curta", "warning", "Transcrição abaixo do mínimo de palavras configurado."),
    ("invalid_link", "Links inválidos", "critical", "Links externos ou internos com formato inválido."),
    ("unreachable_link", "Links externos inacessíveis", "warning", "Links válidos que retornaram erro ou não responderam."),
    ("silver_missing_gold", "Na silver, ausente na gold", "critical", "Pregações processadas que não chegaram ao catálogo."),
    ("orphan_media", "Arquivos órfãos", "critical", "Assets sem uma pregação correspondente na silver."),
    ("orphan_transcripts", "Transcrições órfãs", "critical", "Transcrições sem uma pregação correspondente na silver."),
    ("possible_duplicates", "Possíveis duplicidades", "warning", "Mais de um identificador canônico para a mesma data."),
    ("missing_sundays", "Domingos ausentes", "critical", "Domingos sem pregação e sem exceção cadastrada."),
    ("justified_missing_sundays", "Domingos ausentes justificados", "info", "Domingos sem pregação cobertos por uma exceção."),
    ("failed_pipeline_runs_7d", "Falhas de pipeline em 7 dias", "critical", "Execuções de pipeline que falharam nos últimos sete dias."),
    ("stale_pipeline", "Pipeline desatualizada", "critical", "Sem execução bem-sucedida nos últimos oito dias."),
]


def parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def is_valid_link(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return True
    if value.startswith("/"):
        return not value.startswith("//")
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_checkable_external_link(value: str) -> bool:
    hostname = (urlparse(value).hostname or "").lower()
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ("ibrvn.com", "youtube.com", "youtu.be", "youtube-nocookie.com")
    )


def check_external_link(url: str) -> str:
    try:
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=QUALITY_LINK_TIMEOUT_SECONDS,
            headers={"User-Agent": "IBRVN-Archive-Data-Quality/1.0"},
        )
        if response.status_code == 405:
            response.close()
            response = requests.get(
                url,
                allow_redirects=True,
                stream=True,
                timeout=QUALITY_LINK_TIMEOUT_SECONDS,
                headers={"User-Agent": "IBRVN-Archive-Data-Quality/1.0"},
            )
        status_code = response.status_code
        response.close()
        if status_code >= 400 and status_code not in {401, 403, 429}:
            return f"HTTP {status_code}"
        return ""
    except requests.RequestException as exc:
        return f"{type(exc).__name__}: {str(exc)[:180]}"


def check_external_link_health(urls):
    unique_urls = sorted(set(urls))
    if not QUALITY_CHECK_EXTERNAL_LINKS or not unique_urls:
        return {}
    results = {}
    with ThreadPoolExecutor(max_workers=min(8, len(unique_urls))) as executor:
        futures = {executor.submit(check_external_link, url): url for url in unique_urls}
        for future in as_completed(futures):
            detail = future.result()
            if detail:
                results[futures[future]] = detail
    return results


def issue_for_sermon(row, metric_key, detail="", link="", source_system=""):
    return {
        "issue_id": uuid4().hex,
        "metric_key": metric_key,
        "entity_type": "sermon",
        "entity_id": str(row.get("canonical_sermon_id") or row.get("preaching_date") or ""),
        "preaching_date": str(row.get("preaching_date") or ""),
        "title": str(row.get("title") or ""),
        "preacher_name": str(row.get("preacher_name") or ""),
        "source_system": source_system,
        "detail": detail,
        "link": link,
        "payload_json": "",
    }


def calculate_snapshot(today: date | None = None):
    sermons = fetch_all("SELECT * FROM gold_sermons ORDER BY preaching_date DESC")
    metadata = fetch_all("""
        SELECT canonical_sermon_id, source_system, source_item_id,
               preaching_date, title, preacher_name
        FROM silver_sermon_metadata
    """)
    media = fetch_all("SELECT * FROM silver_media_assets")
    transcripts = fetch_all("""
        SELECT canonical_sermon_id, transcript_version, transcript_text, created_at
        FROM (
            SELECT canonical_sermon_id, transcript_version, transcript_text, created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY canonical_sermon_id
                       ORDER BY created_at DESC, transcript_version DESC
                   ) AS row_number
            FROM silver_transcripts
        ) ranked
        WHERE row_number = 1
    """)
    exceptions = fetch_all("""
        SELECT preaching_date, reason
        FROM data_quality_sunday_exceptions
    """)
    processing_runs = fetch_all("""
        SELECT run_id, pipeline_name, status, started_at, finished_at
        FROM silver_processing_runs
    """)

    metadata_by_sermon = defaultdict(list)
    media_by_sermon = defaultdict(dict)
    latest_transcript = {}
    for row in metadata:
        metadata_by_sermon[row["canonical_sermon_id"]].append(row)
    for row in media:
        media_by_sermon[row["canonical_sermon_id"]][row["asset_type"]] = row
    for row in transcripts:
        latest_transcript.setdefault(row["canonical_sermon_id"], row)

    total = len(sermons)
    issues = defaultdict(list)
    external_link_items = []

    for sermon in sermons:
        sermon_id = sermon["canonical_sermon_id"]
        sources = sorted({
            row.get("source_system", "")
            for row in metadata_by_sermon.get(sermon_id, [])
            if row.get("source_system")
        })
        source_system = ", ".join(sources)
        audio = media_by_sermon.get(sermon_id, {}).get("audio", {})
        local_path = str(audio.get("local_path") or "").strip()
        local_file_exists = bool(local_path and Path(local_path).is_file())
        transcript = latest_transcript.get(sermon_id)

        issues["total_sermons"].append(issue_for_sermon(sermon, "total_sermons", source_system=source_system))
        if not local_path:
            issues["missing_mp3"].append(issue_for_sermon(
                sermon, "missing_mp3", "Nenhum arquivo de áudio local registrado.", source_system=source_system,
            ))
        elif not local_file_exists:
            issues["mp3_file_missing"].append(issue_for_sermon(
                sermon, "mp3_file_missing", local_path, source_system=source_system,
            ))
        if local_file_exists and not transcript:
            issues["mp3_without_transcript"].append(issue_for_sermon(
                sermon, "mp3_without_transcript", source_system=source_system,
            ))
        if sermon.get("youtube_link"):
            youtube_link = str(sermon["youtube_link"])
            issues["youtube_link"].append(issue_for_sermon(
                sermon, "youtube_link",
                link=youtube_link if is_valid_link(youtube_link) else "",
                source_system=source_system,
            ))
        if sermon.get("wordpress_link"):
            wordpress_link = str(sermon["wordpress_link"])
            issues["wordpress_link"].append(issue_for_sermon(
                sermon, "wordpress_link",
                link=wordpress_link if is_valid_link(wordpress_link) else "",
                source_system=source_system,
            ))
        if not sermon.get("youtube_link") and not sermon.get("wordpress_link"):
            issues["no_external_source"].append(issue_for_sermon(
                sermon, "no_external_source", source_system=source_system,
            ))
        if local_file_exists and audio.get("duration_seconds") is None:
            issues["missing_duration"].append(issue_for_sermon(
                sermon, "missing_duration", source_system=source_system,
            ))
        duration = audio.get("duration_seconds")
        if duration is not None:
            minutes = float(duration) / 60
            if minutes < QUALITY_MIN_AUDIO_MINUTES or minutes > QUALITY_MAX_AUDIO_MINUTES:
                issues["suspicious_duration"].append(issue_for_sermon(
                    sermon, "suspicious_duration", f"{minutes:.1f} minutos", source_system=source_system,
                ))
        for field, metric_key in (
            ("title", "missing_title"),
            ("preacher_name", "missing_preacher"),
            ("text_reference", "missing_bible_reference"),
            ("serie", "missing_series"),
        ):
            if not str(sermon.get(field) or "").strip():
                issues[metric_key].append(issue_for_sermon(sermon, metric_key, source_system=source_system))
        if transcript:
            words = len(str(transcript.get("transcript_text") or "").split())
            if words < QUALITY_SHORT_TRANSCRIPT_WORDS:
                issues["short_transcript"].append(issue_for_sermon(
                    sermon, "short_transcript", f"{words} palavras",
                    link=f"/transcripts/{sermon_id}", source_system=source_system,
                ))
        for field in ("youtube_link", "wordpress_link", "media_link", "download_link"):
            value = str(sermon.get(field) or "").strip()
            if value and not is_valid_link(value):
                issues["invalid_link"].append(issue_for_sermon(
                    sermon, "invalid_link", f"{field}: {value}", source_system=source_system,
                ))
            elif value.startswith(("http://", "https://")) and is_checkable_external_link(value):
                external_link_items.append((sermon, source_system, field, value))

    link_failures = check_external_link_health(
        value for _sermon, _source, _field, value in external_link_items
    )
    for sermon, source_system, field, value in external_link_items:
        if value in link_failures:
            issues["unreachable_link"].append(issue_for_sermon(
                sermon,
                "unreachable_link",
                f"{field}: {link_failures[value]}",
                link=value,
                source_system=source_system,
            ))

    silver_ids = set(metadata_by_sermon)
    gold_ids = {row["canonical_sermon_id"] for row in sermons}
    for sermon_id in sorted(silver_ids - gold_ids):
        row = metadata_by_sermon[sermon_id][0]
        issue = issue_for_sermon(row, "silver_missing_gold")
        issue["source_system"] = ", ".join(sorted({
            item.get("source_system", "") for item in metadata_by_sermon[sermon_id]
        }))
        issues["silver_missing_gold"].append(issue)

    for row in media:
        if row["canonical_sermon_id"] not in silver_ids:
            issue = issue_for_sermon(row, "orphan_media", row.get("asset_type", ""))
            issue["entity_type"] = "media"
            issues["orphan_media"].append(issue)
    for row in transcripts:
        if row["canonical_sermon_id"] not in silver_ids:
            issue = issue_for_sermon(row, "orphan_transcripts")
            issue["entity_type"] = "transcript"
            issues["orphan_transcripts"].append(issue)

    canonical_by_date = defaultdict(set)
    metadata_example_by_date = {}
    for row in metadata:
        preaching_date = str(row.get("preaching_date") or "")
        canonical_by_date[preaching_date].add(row["canonical_sermon_id"])
        metadata_example_by_date.setdefault(preaching_date, row)
    for preaching_date, canonical_ids in canonical_by_date.items():
        if preaching_date and len(canonical_ids) > 1:
            row = metadata_example_by_date[preaching_date]
            issue = issue_for_sermon(row, "possible_duplicates", f"{len(canonical_ids)} IDs canônicos")
            issue["entity_id"] = preaching_date
            issue["payload_json"] = json.dumps(sorted(canonical_ids))
            issues["possible_duplicates"].append(issue)

    sermon_dates = {parse_date(row.get("preaching_date")) for row in sermons}
    sermon_dates.discard(None)
    exception_by_date = {parse_date(row["preaching_date"]): row["reason"] for row in exceptions}
    local_today = today or datetime.now(ZoneInfo(LOCAL_TIMEZONE)).date()
    cutoff = local_today - timedelta(days=QUALITY_SUNDAY_GRACE_DAYS)
    cutoff -= timedelta(days=(cutoff.weekday() - 6) % 7)
    configured_start = parse_date(QUALITY_START_DATE) or MINIMUM_SUNDAY_SCOPE_START
    scope_start = max(configured_start, MINIMUM_SUNDAY_SCOPE_START)
    first_sunday = scope_start + timedelta(days=(6 - scope_start.weekday()) % 7)
    current = first_sunday
    while current <= cutoff:
        if current not in sermon_dates:
            reason = exception_by_date.get(current)
            metric_key = "justified_missing_sundays" if reason else "missing_sundays"
            issues[metric_key].append({
                "issue_id": uuid4().hex,
                "metric_key": metric_key,
                "entity_type": "sunday",
                "entity_id": current.isoformat(),
                "preaching_date": current.isoformat(),
                "title": "Domingo sem pregação",
                "preacher_name": "",
                "source_system": "",
                "detail": reason or "Nenhuma pregação encontrada.",
                "link": "",
                "payload_json": "",
            })
        current += timedelta(days=7)

    seven_days_ago = datetime.now(ZoneInfo(LOCAL_TIMEZONE)) - timedelta(days=7)
    latest_success = None
    for row in processing_runs:
        try:
            started = datetime.fromisoformat(str(row.get("started_at") or ""))
            if started.tzinfo is None:
                started = started.replace(tzinfo=ZoneInfo("UTC"))
        except ValueError:
            continue
        if row.get("status") == "success" and (latest_success is None or started > latest_success):
            latest_success = started
        if row.get("status") == "failed" and started >= seven_days_ago:
            issues["failed_pipeline_runs_7d"].append({
                "issue_id": uuid4().hex,
                "metric_key": "failed_pipeline_runs_7d",
                "entity_type": "pipeline_run",
                "entity_id": row["run_id"],
                "preaching_date": str(row.get("started_at") or "")[:10],
                "title": row.get("pipeline_name") or "Pipeline",
                "preacher_name": "",
                "source_system": "",
                "detail": str(row.get("started_at") or ""),
                "link": "",
                "payload_json": "",
            })
    if latest_success is None or latest_success < seven_days_ago - timedelta(days=1):
        issues["stale_pipeline"].append({
            "issue_id": uuid4().hex,
            "metric_key": "stale_pipeline",
            "entity_type": "pipeline",
            "entity_id": "pipeline-freshness",
            "preaching_date": "",
            "title": "Pipeline sem atualização recente",
            "preacher_name": "",
            "source_system": "",
            "detail": (
                f"Último sucesso: {latest_success.isoformat()}"
                if latest_success else "Nenhuma execução bem-sucedida encontrada."
            ),
            "link": "",
            "payload_json": "",
        })

    metric_rows = []
    no_denominator = {
        "missing_sundays", "justified_missing_sundays", "failed_pipeline_runs_7d",
        "stale_pipeline", "orphan_media", "orphan_transcripts", "silver_missing_gold",
        "possible_duplicates",
    }
    for sort_order, (key, label, severity, description) in enumerate(METRICS):
        metric_rows.append({
            "section": "sermons",
            "metric_key": key,
            "label": label,
            "value": len(issues[key]),
            "denominator": total if key not in no_denominator else None,
            "severity": severity,
            "sort_order": sort_order,
            "description": description,
        })

    return {
        "metrics": metric_rows,
        "issues": [item for rows in issues.values() for item in rows],
        "scope_start": scope_start.isoformat(),
        "scope_end": cutoff.isoformat(),
    }


def run(trigger_reason="manual", loopback_days=None, preaching_date=""):
    del loopback_days, preaching_date  # snapshots always represent the full catalog
    initialize_database()
    run_id = uuid4().hex
    calculated_at = utc_now_iso()

    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO data_quality_runs (
                run_id, calculated_at, status, trigger_reason, rule_version
            ) VALUES (
                :run_id, :calculated_at, 'running', :trigger_reason, :rule_version
            )
        """), {
            "run_id": run_id,
            "calculated_at": calculated_at,
            "trigger_reason": trigger_reason,
            "rule_version": RULE_VERSION,
        })

    try:
        snapshot = calculate_snapshot()
        for row in snapshot["metrics"]:
            row["run_id"] = run_id
        for row in snapshot["issues"]:
            row["run_id"] = run_id

        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO data_quality_metrics (
                    run_id, section, metric_key, label, value, denominator,
                    severity, sort_order, description
                ) VALUES (
                    :run_id, :section, :metric_key, :label, :value, :denominator,
                    :severity, :sort_order, :description
                )
            """), snapshot["metrics"])
            if snapshot["issues"]:
                conn.execute(text("""
                    INSERT INTO data_quality_issues (
                        issue_id, run_id, metric_key, entity_type, entity_id,
                        preaching_date, title, preacher_name, source_system,
                        detail, link, payload_json
                    ) VALUES (
                        :issue_id, :run_id, :metric_key, :entity_type, :entity_id,
                        :preaching_date, :title, :preacher_name, :source_system,
                        :detail, :link, :payload_json
                    )
                """), snapshot["issues"])
            conn.execute(text("""
                UPDATE data_quality_runs
                SET status = 'success', finished_at = :finished_at,
                    scope_start = :scope_start, scope_end = :scope_end
                WHERE run_id = :run_id
            """), {
                "run_id": run_id,
                "finished_at": utc_now_iso(),
                "scope_start": snapshot["scope_start"],
                "scope_end": snapshot["scope_end"],
            })
        print(json.dumps({
            "run_id": run_id,
            "status": "success",
            "metrics": {row["metric_key"]: row["value"] for row in snapshot["metrics"]},
        }, ensure_ascii=False))
        return run_id
    except Exception as exc:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE data_quality_runs
                SET status = 'failed', finished_at = :finished_at,
                    error_message = :error_message
                WHERE run_id = :run_id
            """), {
                "run_id": run_id,
                "finished_at": utc_now_iso(),
                "error_message": str(exc)[:2000],
            })
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger-reason", default="manual")
    parser.add_argument("--loopback-days", type=int, default=None)
    parser.add_argument("--preaching-date", default="")
    args = parser.parse_args()
    run(
        trigger_reason=args.trigger_reason,
        loopback_days=args.loopback_days,
        preaching_date=args.preaching_date,
    )

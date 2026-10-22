from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .db import fetch_all, fetch_one
from shared.settings import LOCAL_TIMEZONE


def format_timestamp(value):
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo(LOCAL_TIMEZONE))
        return parsed.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(value)


def get_quality_run(run_id=""):
    if run_id:
        return fetch_one("""
            SELECT * FROM data_quality_runs
            WHERE run_id = :run_id AND status = 'success'
        """, {"run_id": run_id})
    return fetch_one("""
        SELECT * FROM data_quality_runs
        WHERE status = 'success'
        ORDER BY calculated_at DESC
        LIMIT 1
    """)


def get_quality_issues(run_id, metric_key, year="", source="", preacher=""):
    if not run_id or not metric_key:
        return []
    conditions = ["run_id = :run_id", "metric_key = :metric_key"]
    params = {"run_id": run_id, "metric_key": metric_key}
    if year:
        conditions.append("preaching_date LIKE :year")
        params["year"] = f"{year}%"
    if source:
        conditions.append("LOWER(source_system) LIKE :source")
        params["source"] = f"%{source.lower()}%"
    if preacher:
        conditions.append("preacher_name = :preacher")
        params["preacher"] = preacher
    return fetch_all(f"""
        SELECT *
        FROM data_quality_issues
        WHERE {' AND '.join(conditions)}
        ORDER BY preaching_date DESC, LOWER(title), entity_id
    """, params)


def get_quality_dashboard(run_id="", metric_key="", year="", source="", preacher=""):
    latest_attempt = fetch_one("""
        SELECT * FROM data_quality_runs
        ORDER BY calculated_at DESC LIMIT 1
    """)
    if latest_attempt:
        latest_attempt["calculated_at_display"] = format_timestamp(
            latest_attempt["calculated_at"]
        )
    selected_run = get_quality_run(run_id)
    if not selected_run:
        return {
            "run": None, "metrics": [], "history": [], "issues": [],
            "selected_metric": None, "years": [], "sources": [], "preachers": [],
            "last_pipeline_success": "", "latest_attempt": latest_attempt,
        }

    run_id = selected_run["run_id"]
    metrics = fetch_all("""
        SELECT * FROM data_quality_metrics
        WHERE run_id = :run_id
        ORDER BY sort_order
    """, {"run_id": run_id})
    previous_run = fetch_one("""
        SELECT run_id FROM data_quality_runs
        WHERE status = 'success' AND calculated_at < :calculated_at
        ORDER BY calculated_at DESC LIMIT 1
    """, {"calculated_at": selected_run["calculated_at"]})
    previous_values = {}
    if previous_run:
        previous_values = {
            row["metric_key"]: row["value"] for row in fetch_all("""
                SELECT metric_key, value FROM data_quality_metrics
                WHERE run_id = :run_id
            """, {"run_id": previous_run["run_id"]})
        }
    for metric in metrics:
        denominator = metric.get("denominator")
        metric["percentage"] = round(metric["value"] * 100 / denominator, 1) if denominator else None
        previous = previous_values.get(metric["metric_key"])
        metric["delta"] = metric["value"] - previous if previous is not None else None

    history_rows = fetch_all("""
        SELECT r.run_id, r.calculated_at, r.trigger_reason,
               m.metric_key, m.value, m.denominator
        FROM data_quality_runs r
        JOIN data_quality_metrics m ON m.run_id = r.run_id
        WHERE r.status = 'success'
        ORDER BY r.calculated_at DESC
        LIMIT 1300
    """)
    history_rows.reverse()
    history = []
    for row in history_rows:
        denominator = row.get("denominator")
        row["percentage"] = round(row["value"] * 100 / denominator, 2) if denominator else None
        history.append(row)

    selected_metric = next(
        (item for item in metrics if item["metric_key"] == metric_key), None,
    )
    issues = get_quality_issues(run_id, metric_key, year, source, preacher)
    filter_rows = fetch_all("""
        SELECT preaching_date, source_system, preacher_name
        FROM data_quality_issues
        WHERE run_id = :run_id
    """, {"run_id": run_id})
    years = sorted({
        str(row["preaching_date"])[:4] for row in filter_rows
        if str(row.get("preaching_date") or "")[:4].isdigit()
    }, reverse=True)
    sources = sorted({
        source.strip()
        for row in filter_rows
        for source in str(row.get("source_system") or "").split(",")
        if source.strip()
    })
    preachers = sorted({
        row["preacher_name"] for row in filter_rows if row.get("preacher_name")
    }, key=str.casefold)
    last_pipeline = fetch_one("""
        SELECT finished_at FROM silver_processing_runs
        WHERE status = 'success'
        ORDER BY finished_at DESC LIMIT 1
    """)
    selected_run["calculated_at_display"] = format_timestamp(selected_run["calculated_at"])
    selected_run["finished_at_display"] = format_timestamp(selected_run["finished_at"])

    return {
        "run": selected_run,
        "metrics": metrics,
        "history": history,
        "issues": issues,
        "selected_metric": selected_metric,
        "years": years,
        "sources": sources,
        "preachers": preachers,
        "last_pipeline_success": format_timestamp(
            last_pipeline["finished_at"] if last_pipeline else ""
        ),
        "latest_attempt": latest_attempt,
    }

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from pathlib import Path
import re
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .db import fetch_all, fetch_one
from .queries import extract_book_name
from shared.db import get_engine, utc_now_iso
from shared.settings import (
    ANALYTICS_ENABLED,
    ANALYTICS_RETENTION_DAYS,
    LOCAL_TIMEZONE,
)


ALLOWED_EVENTS = {
    "page_view",
    "youtube_click",
    "site_click",
    "transcript_click",
    "download",
    "audio_play",
    "audio_progress",
    "audio_complete",
    "audio_speed",
}
ALLOWED_CONTENT_TYPES = {"", "sermon", "study"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


def anonymous_hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def clean_identifier(value) -> str:
    value = str(value or "").strip()
    return value if ID_PATTERN.fullmatch(value) else ""


def clean_path(value) -> str:
    value = str(value or "").strip()[:500]
    return value if value.startswith("/") and not value.startswith("//") else ""


def safe_number(value, minimum=0.0, maximum=86400.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return min(maximum, max(minimum, number))


def referrer_domain(value) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "")[:255].lower()
    except ValueError:
        return ""


def asset_details(content_type: str, content_id: str, resource_id: str):
    if content_type == "sermon" and content_id:
        return fetch_one("""
            SELECT local_path, duration_seconds
            FROM silver_media_assets
            WHERE canonical_sermon_id = :content_id AND asset_type = 'audio'
        """, {"content_id": content_id})
    if content_type == "study" and resource_id:
        return fetch_one("""
            SELECT local_path, duration_seconds
            FROM gold_study_resources
            WHERE resource_id = :resource_id AND study_id = :content_id
        """, {"resource_id": resource_id, "content_id": content_id})
    return None


def estimate_bytes(event, asset_cache) -> int:
    if event["event_type"] not in {"download", "audio_progress"}:
        return 0
    key = (event["content_type"], event["content_id"], event["resource_id"])
    if key not in asset_cache:
        asset_cache[key] = asset_details(*key)
    asset = asset_cache[key]
    if not asset or not asset.get("local_path"):
        return 0
    path = Path(asset["local_path"])
    try:
        file_size = path.stat().st_size
    except OSError:
        return 0
    if event["event_type"] == "download":
        return file_size
    duration = event["duration_seconds"] or asset.get("duration_seconds")
    if not duration:
        return 0
    media_seconds = (event["listened_seconds"] or 0) * (event["playback_rate"] or 1)
    return round(file_size * min(1, media_seconds / float(duration)))


def prepare_event(raw, visitor_hash, session_hash, asset_cache):
    event_type = str(raw.get("event_type") or "")
    content_type = str(raw.get("content_type") or "")
    if event_type not in ALLOWED_EVENTS or content_type not in ALLOWED_CONTENT_TYPES:
        return None
    content_id = clean_identifier(raw.get("content_id"))
    resource_id = clean_identifier(raw.get("resource_id"))
    if event_type != "page_view" and event_type not in {
        "youtube_click", "site_click", "transcript_click",
    } and (not content_type or not content_id):
        return None
    event = {
        "event_id": clean_identifier(raw.get("event_id")) or uuid4().hex,
        "occurred_at": utc_now_iso(),
        "event_type": event_type,
        "visitor_id_hash": visitor_hash,
        "session_id_hash": session_hash,
        "page_path": clean_path(raw.get("page_path")),
        "content_type": content_type,
        "content_id": content_id,
        "resource_id": resource_id,
        "position_seconds": safe_number(raw.get("position_seconds")),
        "duration_seconds": safe_number(raw.get("duration_seconds")),
        "listened_seconds": safe_number(raw.get("listened_seconds"), maximum=60),
        "playback_rate": safe_number(raw.get("playback_rate"), minimum=.25, maximum=4),
        "bytes_estimated": 0,
        "referrer_domain": referrer_domain(raw.get("referrer")),
    }
    event["bytes_estimated"] = estimate_bytes(event, asset_cache)
    return event


def record_events(payload) -> int:
    if not ANALYTICS_ENABLED or not isinstance(payload, dict):
        return 0
    visitor_id = clean_identifier(payload.get("visitor_id"))
    session_id = clean_identifier(payload.get("session_id"))
    raw_events = payload.get("events")
    if not visitor_id or not session_id or not isinstance(raw_events, list):
        return 0
    visitor_hash = anonymous_hash(visitor_id)
    session_hash = anonymous_hash(session_id)
    asset_cache = {}
    events = [
        event for raw in raw_events[:50]
        if isinstance(raw, dict)
        and (event := prepare_event(raw, visitor_hash, session_hash, asset_cache))
    ]
    if not events:
        return 0
    now = utc_now_iso()
    retention_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=ANALYTICS_RETENTION_DAYS)
    ).isoformat()
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO analytics_visitors (
                visitor_id_hash, first_seen_at, last_seen_at
            ) VALUES (
                :visitor_id_hash, :first_seen_at, :last_seen_at
            )
            ON CONFLICT(visitor_id_hash) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at
        """), {
            "visitor_id_hash": visitor_hash,
            "first_seen_at": now,
            "last_seen_at": now,
        })
        conn.execute(text("""
            INSERT INTO analytics_events (
                event_id, occurred_at, event_type, visitor_id_hash,
                session_id_hash, page_path, content_type, content_id,
                resource_id, position_seconds, duration_seconds,
                listened_seconds, playback_rate, bytes_estimated,
                referrer_domain
            ) VALUES (
                :event_id, :occurred_at, :event_type, :visitor_id_hash,
                :session_id_hash, :page_path, :content_type, :content_id,
                :resource_id, :position_seconds, :duration_seconds,
                :listened_seconds, :playback_rate, :bytes_estimated,
                :referrer_domain
            )
            ON CONFLICT(event_id) DO NOTHING
        """), events)
        conn.execute(text("""
            DELETE FROM analytics_events WHERE occurred_at < :cutoff
        """), {"cutoff": retention_cutoff})
        conn.execute(text("""
            DELETE FROM analytics_visitors WHERE last_seen_at < :cutoff
        """), {"cutoff": retention_cutoff})
    return len(events)


def parse_period(start="", end="", days=30):
    local_today = datetime.now(ZoneInfo(LOCAL_TIMEZONE)).date()
    try:
        end_date = date.fromisoformat(end) if end else local_today
    except ValueError:
        end_date = local_today
    try:
        requested_days = min(ANALYTICS_RETENTION_DAYS, max(1, int(days)))
    except (TypeError, ValueError):
        requested_days = 30
    try:
        start_date = date.fromisoformat(start) if start else end_date - timedelta(days=requested_days - 1)
    except ValueError:
        start_date = end_date - timedelta(days=requested_days - 1)
    retention_start = local_today - timedelta(days=ANALYTICS_RETENTION_DAYS - 1)
    start_date = max(start_date, retention_start)
    end_date = min(max(end_date, start_date), local_today)
    local_zone = ZoneInfo(LOCAL_TIMEZONE)
    start_utc = datetime.combine(start_date, time.min, local_zone).astimezone(timezone.utc)
    end_utc = datetime.combine(end_date + timedelta(days=1), time.min, local_zone).astimezone(timezone.utc)
    return start_date, end_date, start_utc.isoformat(), end_utc.isoformat()


def event_local_date(event):
    value = datetime.fromisoformat(event["occurred_at"])
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(LOCAL_TIMEZONE)).date()


def build_series(events, start_date, end_date, content_type=""):
    daily = {}
    current = start_date
    while current <= end_date:
        daily[current] = {"label": current.isoformat(), "views": 0, "plays": 0, "downloads": 0}
        current += timedelta(days=1)
    for event in events:
        day = event_local_date(event)
        if day not in daily:
            continue
        if event["event_type"] == "page_view":
            daily[day]["views"] += 1
        if not content_type or event.get("content_type") == content_type:
            if event["event_type"] == "audio_play":
                daily[day]["plays"] += 1
            elif event["event_type"] == "download":
                daily[day]["downloads"] += 1

    def aggregate(key_function):
        grouped = {}
        for day, values in daily.items():
            key = key_function(day)
            point = grouped.setdefault(key, {"label": key, "views": 0, "plays": 0, "downloads": 0})
            for metric in ("views", "plays", "downloads"):
                point[metric] += values[metric]
        return list(grouped.values())

    return {
        "day": list(daily.values()),
        "week": aggregate(lambda day: (day - timedelta(days=day.weekday())).isoformat()),
        "month": aggregate(lambda day: day.strftime("%Y-%m")),
    }


def format_bytes(value):
    value = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    return f"{value:.1f} {unit}" if value and value < 100 else f"{value:.0f} {unit}"


def get_analytics_dashboard(start="", end="", days=30, content_type=""):
    if content_type not in {"", "sermon", "study"}:
        content_type = ""
    start_date, end_date, start_utc, end_utc = parse_period(start, end, days)
    events = fetch_all("""
        SELECT * FROM analytics_events
        WHERE occurred_at >= :start_at AND occurred_at < :end_at
        ORDER BY occurred_at
    """, {"start_at": start_utc, "end_at": end_utc})
    content_events = [
        event for event in events
        if not content_type or event.get("content_type") == content_type
    ]

    visitor_hashes = {
        event["visitor_id_hash"] for event in events
        if event["event_type"] == "page_view"
    }
    first_seen = {
        row["visitor_id_hash"]: row["first_seen_at"]
        for row in fetch_all("SELECT visitor_id_hash, first_seen_at FROM analytics_visitors")
        if row["visitor_id_hash"] in visitor_hashes
    }
    new_visitors = 0
    for visitor_hash in visitor_hashes:
        value = first_seen.get(visitor_hash)
        if value and event_local_date({"occurred_at": value}) >= start_date:
            new_visitors += 1

    page_views = [event for event in events if event["event_type"] == "page_view"]
    plays = [event for event in content_events if event["event_type"] == "audio_play"]
    completions = [event for event in content_events if event["event_type"] == "audio_complete"]
    downloads = [event for event in content_events if event["event_type"] == "download"]
    progress = [event for event in content_events if event["event_type"] == "audio_progress"]
    unique_plays = {
        (event["visitor_id_hash"], event.get("content_type"), event.get("content_id"))
        for event in plays
    }
    listened_seconds = sum(float(event.get("listened_seconds") or 0) for event in progress)
    bytes_estimated = sum(int(event.get("bytes_estimated") or 0) for event in content_events)

    sermon_rows = fetch_all("""
        SELECT canonical_sermon_id, title, preaching_date, preacher_name, serie, text_reference
        FROM gold_sermons
    """)
    study_rows = fetch_all("SELECT study_id, title, study_date FROM gold_studies")
    sermons = {row["canonical_sermon_id"]: row for row in sermon_rows}
    studies = {row["study_id"]: row for row in study_rows}

    content_stats = defaultdict(lambda: {
        "plays": 0, "visitors": set(), "completions": 0,
        "downloads": 0, "listened_seconds": 0.0,
    })
    for event in content_events:
        key = (event.get("content_type"), event.get("content_id"))
        if not all(key) or event["event_type"] not in {
            "audio_play", "audio_complete", "download", "audio_progress",
        }:
            continue
        stats = content_stats[key]
        if event["event_type"] == "audio_play":
            stats["plays"] += 1
            stats["visitors"].add(event["visitor_id_hash"])
        elif event["event_type"] == "audio_complete":
            stats["completions"] += 1
        elif event["event_type"] == "download":
            stats["downloads"] += 1
        elif event["event_type"] == "audio_progress":
            stats["listened_seconds"] += float(event.get("listened_seconds") or 0)

    top_content = []
    for (kind, content_id), stats in content_stats.items():
        metadata = sermons.get(content_id, {}) if kind == "sermon" else studies.get(content_id, {})
        title = metadata.get("title") or content_id
        top_content.append({
            "content_type": kind,
            "content_type_label": "Pregação" if kind == "sermon" else "Estudo",
            "content_id": content_id,
            "title": title,
            "plays": stats["plays"],
            "unique_plays": len(stats["visitors"]),
            "completions": stats["completions"],
            "completion_rate": round(stats["completions"] * 100 / stats["plays"], 1) if stats["plays"] else 0,
            "downloads": stats["downloads"],
            "listening_hours": round(stats["listened_seconds"] / 3600, 1),
        })
    top_content.sort(key=lambda item: (item["plays"], item["downloads"], item["completions"]), reverse=True)
    top_downloads = sorted(
        (item for item in top_content if item["downloads"]),
        key=lambda item: (item["downloads"], item["plays"]),
        reverse=True,
    )

    sermon_play_counts = Counter(
        event.get("content_id") for event in plays if event.get("content_type") == "sermon"
    )
    dimension_counts = {"preachers": Counter(), "series": Counter(), "books": Counter()}
    for sermon_id, count in sermon_play_counts.items():
        sermon = sermons.get(sermon_id, {})
        if sermon.get("preacher_name"):
            dimension_counts["preachers"][sermon["preacher_name"]] += count
        if sermon.get("serie"):
            dimension_counts["series"][sermon["serie"]] += count
        book = extract_book_name(sermon.get("text_reference"))
        if book:
            dimension_counts["books"][book] += count

    speed_seconds = Counter()
    for event in progress:
        speed_seconds[float(event["playback_rate"] or 1)] += float(
            event.get("listened_seconds") or 0
        )
    page_counts = Counter(event.get("page_path") or "/" for event in page_views)
    click_counts = Counter(
        event["event_type"] for event in content_events
        if event["event_type"] in {"youtube_click", "site_click", "transcript_click"}
    )

    return {
        "enabled": ANALYTICS_ENABLED,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "content_type": content_type,
        "retention_days": ANALYTICS_RETENTION_DAYS,
        "kpis": {
            "page_views": len(page_views),
            "visitors": len(visitor_hashes),
            "new_visitors": new_visitors,
            "returning_visitors": len(visitor_hashes) - new_visitors,
            "plays": len(plays),
            "unique_plays": len(unique_plays),
            "listening_hours": round(listened_seconds / 3600, 1),
            "completions": len(completions),
            "completion_rate": round(len(completions) * 100 / len(plays), 1) if plays else 0,
            "downloads": len(downloads),
            "bytes_estimated": bytes_estimated,
            "bytes_display": format_bytes(bytes_estimated),
            "youtube_clicks": click_counts["youtube_click"],
            "site_clicks": click_counts["site_click"],
            "transcript_clicks": click_counts["transcript_click"],
        },
        "series": build_series(events, start_date, end_date, content_type),
        "top_pages": [{"path": key, "views": value} for key, value in page_counts.most_common(15)],
        "top_content": top_content[:25],
        "top_downloads": top_downloads[:15],
        "preachers": [{"label": key, "plays": value} for key, value in dimension_counts["preachers"].most_common(10)],
        "series_ranking": [{"label": key, "plays": value} for key, value in dimension_counts["series"].most_common(10)],
        "books": [{"label": key, "plays": value} for key, value in dimension_counts["books"].most_common(10)],
        "speeds": [
            {"label": f"{rate:g}x", "minutes": round(seconds / 60, 1)}
            for rate, seconds in sorted(speed_seconds.items(), key=lambda item: (-item[1], item[0]))
        ],
    }

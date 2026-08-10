from __future__ import annotations

from datetime import date, timedelta


def build_preaching_date_scope(alias: str, loopback_days):

    cutoff_date = loopback_cutoff_date(loopback_days)

    if not cutoff_date:
        return "", {}

    return f"AND {alias}.preaching_date >= :cutoff_date", {
        "cutoff_date": cutoff_date,
    }


def format_duration_minutes(duration_seconds) -> str:

    if duration_seconds in (None, ""):
        return "unknown"

    return f"{float(duration_seconds) / 60:.1f} min"


def format_elapsed_seconds(elapsed_seconds: float) -> str:

    if elapsed_seconds < 60:
        return f"{elapsed_seconds:.1f}s"

    minutes = int(elapsed_seconds // 60)
    seconds = elapsed_seconds % 60
    return f"{minutes}m {seconds:.1f}s"


def normalize_force_reprocess(value) -> bool:

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_loopback_days(value):

    if value in (None, ""):
        return None

    days = int(value)

    if days <= 0:
        return None

    return days


def loopback_cutoff_date(loopback_days):

    normalized = normalize_loopback_days(loopback_days)

    if normalized is None:
        return ""

    return (date.today() - timedelta(days=normalized)).isoformat()

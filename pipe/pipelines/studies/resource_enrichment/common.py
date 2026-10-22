from __future__ import annotations

import hashlib
import mimetypes
import re
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlsplit

from shared.db import fetch_all
from shared.settings import STUDY_RESOURCE_RAW_DIR


DOCUMENT_RESOURCE_TYPES = {
    "archive",
    "document",
    "pdf",
    "presentation",
    "spreadsheet",
    "word",
}
MAX_PATH_COMPONENT_BYTES = 180
IDENTITY_SUFFIX_LENGTH = 12
WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def normalize_loopback_days(value) -> int | None:
    if value in (None, ""):
        return None

    days = int(value)

    if days <= 0:
        raise ValueError("loopback_days must be a positive integer")

    return days


def loopback_cutoff_date(loopback_days) -> str:
    days = normalize_loopback_days(loopback_days)
    return (date.today() - timedelta(days=days)).isoformat() if days else ""


def build_study_date_scope(alias: str, loopback_days) -> tuple[str, dict]:
    cutoff = loopback_cutoff_date(loopback_days)

    if not cutoff:
        return "", {}

    return f"AND {alias}.study_date >= :cutoff_date", {"cutoff_date": cutoff}


def fetch_gold_resource_rows(loopback_days=None) -> list[dict]:
    scope_sql, params = build_study_date_scope("gs", loopback_days)
    return fetch_all(f"""
        SELECT
            gsr.resource_id,
            gsr.study_id,
            gsr.resource_type,
            gsr.label,
            gsr.source_url,
            gsr.canonical_url,
            gsr.mime_type,
            gsr.source_system,
            gs.study_date,
            gs.title AS study_title
        FROM gold_study_resources gsr
        JOIN gold_studies gs ON gs.study_id = gsr.study_id
        WHERE 1 = 1
        {scope_sql}
        ORDER BY gs.study_date DESC, gsr.study_id, gsr.position
    """, params)


def youtube_video_id(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    host = parts.netloc.casefold().removeprefix("www.")

    if host == "youtu.be":
        return parts.path.strip("/").split("/")[0]

    if host.endswith("youtube.com"):
        query_video_id = (parse_qs(parts.query).get("v") or [""])[0].strip()

        if query_video_id:
            return query_video_id

        path_parts = parts.path.strip("/").split("/")

        if len(path_parts) >= 2 and path_parts[0] in {"embed", "live", "shorts"}:
            return path_parts[1]

    return ""


def select_download_candidates(rows: list[dict]) -> list[dict]:
    study_has_audio = {
        row["study_id"]
        for row in rows
        if row.get("resource_type") == "audio"
    }
    candidates = []

    for row in rows:
        resource_type = row.get("resource_type") or ""

        if resource_type == "audio":
            candidates.append({**row, "asset_type": "audio", "source_kind": "direct"})
        elif resource_type in DOCUMENT_RESOURCE_TYPES:
            candidates.append({**row, "asset_type": "document", "source_kind": "direct"})
        elif (
            resource_type == "youtube"
            and row["study_id"] not in study_has_audio
            and youtube_video_id(row.get("canonical_url") or row.get("source_url"))
        ):
            candidates.append({**row, "asset_type": "audio", "source_kind": "youtube"})

    return candidates


def safe_filename(value: str, fallback: str) -> str:
    filename = PurePosixPath(unquote(str(value or "")).replace("\\", "/")).name
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
    return filename or fallback


def safe_path_component(value: str, fallback: str) -> str:
    component = unquote(str(value or ""))
    component = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", component)
    component = re.sub(r"\s+", " ", component).strip(" .")

    if not component or component in {".", ".."}:
        component = fallback

    if component.casefold() in WINDOWS_RESERVED_NAMES:
        component = f"_{component}"

    return component


def truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")

    if len(encoded) <= max_bytes:
        return value

    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(" .")


def friendly_component(
    value: str,
    stable_id: str,
    fallback: str,
    extension: str = "",
) -> str:
    identity = re.sub(r"[^a-zA-Z0-9]", "", str(stable_id or ""))
    identity = identity[:IDENTITY_SUFFIX_LENGTH] or "unknown"
    normalized_extension = (
        f".{extension.lstrip('.')}" if extension else ""
    )
    suffix = f" [{identity}]{normalized_extension}"
    available_bytes = MAX_PATH_COMPONENT_BYTES - len(suffix.encode("utf-8"))
    readable_name = safe_path_component(value, fallback)
    readable_name = truncate_utf8(readable_name, available_bytes)
    return f"{readable_name or fallback}{suffix}"


def direct_original_filename(row: dict) -> str:
    path_name = PurePosixPath(
        unquote(urlsplit(row.get("source_url") or "").path)
    ).name
    label_name = PurePosixPath(str(row.get("label") or "")).name
    preferred = path_name if Path(path_name).suffix else label_name
    return safe_filename(preferred, f"resource-{row['resource_id'][:12]}")


def candidate_extension(row: dict) -> str:
    if row["source_kind"] == "youtube":
        return ".mp3"

    original_filename = direct_original_filename(row)
    extension = Path(original_filename).suffix

    if extension:
        return extension

    guessed_extension = mimetypes.guess_extension(row.get("mime_type") or "")
    return guessed_extension or ""


def candidate_filename(row: dict) -> str:
    extension = candidate_extension(row)
    label = str(row.get("label") or "").strip()

    if label and extension and label.casefold().endswith(extension.casefold()):
        label = label[:-len(extension)]

    if not label:
        label = Path(direct_original_filename(row)).stem

    return friendly_component(
        label,
        row["resource_id"],
        "resource",
        extension,
    )


def study_directory_name(row: dict) -> str:
    return friendly_component(
        row.get("study_title") or "",
        row["study_id"],
        "study",
    )


def build_local_path(row: dict, filename: str) -> Path:
    return (
        STUDY_RESOURCE_RAW_DIR
        / study_directory_name(row)
        / filename
    )


def stable_asset_id(resource_id: str, source_kind: str) -> str:
    payload = f"{resource_id}\x1f{source_kind}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def guessed_mime_type(filename: str, fallback: str = "") -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback or "application/octet-stream"


def is_mp3_asset(row: dict) -> bool:
    return (
        str(row.get("mime_type") or "").casefold() == "audio/mpeg"
        or str(row.get("local_path") or "").casefold().endswith(".mp3")
    )

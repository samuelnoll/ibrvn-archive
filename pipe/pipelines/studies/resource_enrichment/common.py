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


def direct_original_filename(row: dict) -> str:
    path_name = PurePosixPath(
        unquote(urlsplit(row.get("source_url") or "").path)
    ).name
    label_name = PurePosixPath(str(row.get("label") or "")).name
    preferred = path_name if Path(path_name).suffix else label_name
    return safe_filename(preferred, f"resource-{row['resource_id'][:12]}")


def youtube_audio_filename(row: dict) -> str:
    video_id = youtube_video_id(
        row.get("canonical_url") or row.get("source_url") or ""
    )
    title = str(row.get("label") or video_id).replace("/", "_").replace("\\", "_")
    stem = safe_filename(title, video_id or "youtube-audio")

    if stem.casefold().endswith(".mp3"):
        return stem

    return f"{stem}.mp3"


def candidate_filename(row: dict) -> str:
    if row["source_kind"] == "youtube":
        return youtube_audio_filename(row)

    return direct_original_filename(row)


def build_local_path(row: dict, filename: str) -> Path:
    return (
        STUDY_RESOURCE_RAW_DIR
        / row["study_id"][:16]
        / row["resource_id"][:16]
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

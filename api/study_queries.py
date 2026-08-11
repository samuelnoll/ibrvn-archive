from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date, datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from .db import fetch_all, fetch_one


STUDY_TYPES = OrderedDict([
    ("ctb", "Centro de Treinamento B\u00edblico"),
    ("lecture_or_conference", "Palestras e Confer\u00eancias"),
    ("weekly", "Estudos Semanais"),
    ("pfd", "Programa de Forma\u00e7\u00e3o de Disc\u00edpulos"),
])

RESOURCE_TYPES = OrderedDict([
    ("audio", ("\u00c1udios", "headphones")),
    ("youtube", ("YouTube", "youtube")),
    ("video_platform", ("Videos", "youtube")),
    ("video_file", ("Arquivos de video", "youtube")),
    ("pdf", ("PDFs", "file-text")),
    ("word", ("Documentos Word", "file-text")),
    ("document", ("Documentos", "file-text")),
    ("presentation", ("Apresenta\u00e7\u00f5es", "file-text")),
    ("spreadsheet", ("Planilhas", "file-text")),
    ("archive", ("Arquivos compactados", "download")),
    ("external_link", ("Links externos", "external-link")),
    ("internal_link", ("Links da IBRVN", "external-link")),
])


def format_date(value) -> str:
    if not value:
        return ""

    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")

    parts = str(value).split("-")

    if len(parts) == 3 and all(parts):
        return f"{parts[2]}/{parts[1]}/{parts[0]}"

    return str(value)


def serialize_study(row: dict) -> dict:
    study = dict(row)
    study["study_type_label"] = STUDY_TYPES.get(
        study.get("study_type"),
        study.get("study_type", ""),
    )
    study["study_date_display"] = format_date(study.get("study_date"))
    study["origin_label"] = (
        "Playlist original no YouTube"
        if study.get("source_system") == "youtube"
        else "P\u00e1gina original do estudo"
    )
    return study


def pfd_catalog_sort_key(study: dict) -> tuple:
    year = str(study.get("study_year") or "")
    sequence_match = re.match(
        r"^(?:Estudo\s+)?(\d+)\b",
        study.get("title", ""),
        re.I,
    )
    sequence = int(sequence_match.group(1)) if sequence_match else 9999
    return (
        -int(year) if year.isdigit() else 0,
        sequence,
        study.get("title", ""),
    )


def get_study_catalog() -> list[dict]:
    rows = fetch_all("""
        SELECT
            study_id,
            study_type,
            title,
            study_date,
            study_year,
            collection_title,
            source_system,
            resource_count
        FROM gold_studies
        ORDER BY
            CASE study_type
                WHEN 'ctb' THEN 1
                WHEN 'lecture_or_conference' THEN 2
                WHEN 'weekly' THEN 3
                WHEN 'pfd' THEN 4
                ELSE 9
            END,
            study_year DESC,
            study_date DESC,
            title
    """)
    rows_by_type = {study_type: [] for study_type in STUDY_TYPES}

    for row in rows:
        rows_by_type.setdefault(row["study_type"], []).append(
            serialize_study(row)
        )

    catalog = []

    for study_type, label in STUDY_TYPES.items():
        studies = rows_by_type.get(study_type, [])

        if study_type == "pfd":
            studies.sort(key=pfd_catalog_sort_key)

        years = OrderedDict()

        for study in studies:
            year = str(study.get("study_year") or "Sem data")
            years.setdefault(year, []).append(study)

        catalog.append({
            "study_type": study_type,
            "label": label,
            "count": len(studies),
            "years": [
                {"year": year, "studies": year_studies}
                for year, year_studies in years.items()
            ],
        })

    return catalog


def get_study_home_stats() -> dict:
    row = fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM gold_studies) AS studies,
            (SELECT COUNT(*) FROM gold_study_resources) AS resources
    """)
    return row or {
        "studies": 0,
        "resources": 0,
    }


def resource_fallback_label(resource_url: str) -> str:
    path = unquote(urlsplit(resource_url or "").path)
    filename = PurePosixPath(path).name
    return filename or resource_url or "Abrir recurso"


def get_study_detail(study_id: str) -> dict | None:
    row = fetch_one("""
        SELECT *
        FROM gold_studies
        WHERE study_id = :study_id
    """, {"study_id": study_id})

    if not row:
        return None

    study = serialize_study(row)
    origins = fetch_all("""
        SELECT source_system, label, source_url
        FROM gold_study_origins
        WHERE study_id = :study_id
        ORDER BY
            CASE source_system WHEN 'wordpress' THEN 1 ELSE 2 END,
            source_url
    """, {"study_id": study_id})

    if not origins and study.get("source_url"):
        origins = [{
            "source_system": study.get("source_system"),
            "label": study.get("origin_label"),
            "source_url": study["source_url"],
        }]

    study["origins"] = origins
    resources = fetch_all("""
        SELECT
            resource_id,
            resource_type,
            label,
            source_url,
            mime_type,
            source_system,
            position
        FROM gold_study_resources
        WHERE study_id = :study_id
        ORDER BY position, resource_type, label
    """, {"study_id": study_id})
    grouped = OrderedDict()

    for resource in resources:
        resource_type = resource.get("resource_type") or "external_link"
        label, icon = RESOURCE_TYPES.get(
            resource_type,
            (resource_type.replace("_", " ").title(), "external-link"),
        )
        group = grouped.setdefault(resource_type, {
            "resource_type": resource_type,
            "label": label,
            "icon": icon,
            "resources": [],
        })
        serialized = dict(resource)
        serialized["display_label"] = (
            str(resource.get("label") or "").strip()
            or resource_fallback_label(resource.get("source_url", ""))
        )
        group["resources"].append(serialized)

    ordered_groups = []

    for resource_type in RESOURCE_TYPES:
        if resource_type in grouped:
            ordered_groups.append(grouped.pop(resource_type))

    ordered_groups.extend(grouped.values())
    study["resource_groups"] = ordered_groups
    return study

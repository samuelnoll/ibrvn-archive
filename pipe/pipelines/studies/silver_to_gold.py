from __future__ import annotations

import hashlib
from collections import Counter

from sqlalchemy import text

from pipe.pipelines.studies.resource_enrichment.silver_to_gold import (
    apply_enrichments,
)
from pipe.pipelines.studies.title_rules import clean_study_title, title_identity
from shared.db import get_engine, utc_now_iso
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)


INSERT_GOLD_STUDY_SQL = """
INSERT INTO gold_studies (
    study_id, study_type, title, study_date, study_year, collection_title,
    source_system, source_url, resource_count, last_aggregated_at
)
VALUES (
    :study_id, :study_type, :title, :study_date, :study_year, :collection_title,
    :source_system, :source_url, :resource_count, :last_aggregated_at
)
"""

INSERT_GOLD_RESOURCE_SQL = """
INSERT INTO gold_study_resources (
    resource_id, study_id, resource_type, label, source_url, canonical_url,
    mime_type, source_system, position
)
VALUES (
    :resource_id, :study_id, :resource_type, :label, :source_url, :canonical_url,
    :mime_type, :source_system, :position
)
"""

INSERT_GOLD_ORIGIN_SQL = """
INSERT INTO gold_study_origins (
    origin_id, study_id, source_system, label, source_url
)
VALUES (
    :origin_id, :study_id, :source_system, :label, :source_url
)
"""

STUDY_TYPE_PRIORITY = {
    "ctb": 0,
    "lecture_or_conference": 1,
    "weekly": 2,
    "pfd": 3,
}


def stable_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def combine_sources(left: str, right: str) -> str:
    sources = {
        source
        for value in (left, right)
        for source in str(value or "").split(",")
        if source
    }
    return ",".join(sorted(sources))


def read_rows(conn, query: str) -> list[dict]:
    return [dict(row) for row in conn.execute(text(query)).mappings().all()]


def aggregate_records(conn) -> tuple[list[dict], list[dict], list[dict]]:
    wordpress_studies = read_rows(conn, """
        SELECT * FROM silver_study_wordpress
        ORDER BY study_date, study_key
    """)
    wordpress_resources = read_rows(conn, """
        SELECT * FROM silver_study_wordpress_resources
        ORDER BY study_key, position
    """)
    youtube_studies = read_rows(conn, """
        SELECT * FROM silver_study_youtube
        ORDER BY study_date, study_key
    """)
    youtube_resources = read_rows(conn, """
        SELECT * FROM silver_study_youtube_resources
        ORDER BY study_key, position
    """)
    aggregated_at = utc_now_iso()
    studies = {}
    source_to_gold = {}
    origins_by_identity = {}
    grouped_studies = {}
    source_studies = [
        {**row, "source_system": "wordpress"}
        for row in wordpress_studies
    ] + [
        {**row, "source_system": "youtube"}
        for row in youtube_studies
    ]

    for row in source_studies:
        identity = title_identity(row.get("title") or "") or row["study_key"]
        grouped_studies.setdefault(identity, []).append(row)

    for identity, candidates in grouped_studies.items():
        preferred = min(
            candidates,
            key=lambda row: (
                0 if row["source_system"] == "wordpress" else 1,
                str(row.get("study_date") or "9999"),
                row["study_key"],
            ),
        )
        dates = sorted(
            str(row.get("study_date") or "")
            for row in candidates
            if row.get("study_date")
        )
        study_date = dates[0] if dates else ""
        study_id = stable_key("study-title", identity)
        study_type = min(
            (row["study_type"] for row in candidates),
            key=lambda value: STUDY_TYPE_PRIORITY.get(value, 99),
        )
        source_system = ""
        source_counts = Counter(
            row["source_system"]
            for row in candidates
            if row.get("source_url")
        )

        for row in candidates:
            source_to_gold[row["study_key"]] = study_id
            source_system = combine_sources(source_system, row["source_system"])
            source_url = str(row.get("source_url") or "").strip()

            if source_url:
                origin_identity = (study_id, source_url)
                origin_label = (
                    "Playlist original no YouTube"
                    if row["source_system"] == "youtube"
                    else "P\u00e1gina original no WordPress"
                )
                origin_year = str(row.get("study_date") or "")[:4]

                if source_counts[row["source_system"]] > 1 and origin_year:
                    origin_label = f"{origin_label} ({origin_year})"

                origins_by_identity.setdefault(origin_identity, {
                    "origin_id": stable_key(study_id, source_url),
                    "study_id": study_id,
                    "source_system": row["source_system"],
                    "label": origin_label,
                    "source_url": source_url,
                })

        studies[study_id] = {
            "study_id": study_id,
            "study_type": study_type,
            "title": clean_study_title(preferred["title"]),
            "study_date": study_date or None,
            "study_year": study_date[:4] if len(study_date) >= 4 else None,
            "collection_title": None,
            "source_system": source_system,
            "source_url": preferred.get("source_url"),
            "resource_count": 0,
            "last_aggregated_at": aggregated_at,
        }

    resources_by_identity = {}

    def add_resource(row: dict, target_study_id: str, source_system: str) -> None:
        identity = (target_study_id, row["canonical_url"])
        existing = resources_by_identity.get(identity)

        if existing:
            existing["source_system"] = combine_sources(
                existing["source_system"],
                source_system,
            )
            return

        resources_by_identity[identity] = {
            "resource_id": stable_key(target_study_id, row["canonical_url"]),
            "study_id": target_study_id,
            "resource_type": row["resource_type"],
            "label": row.get("label") or None,
            "source_url": row["source_url"],
            "canonical_url": row["canonical_url"],
            "mime_type": row.get("mime_type") or None,
            "source_system": source_system,
            "position": int(row.get("position") or 0),
        }

    for row in wordpress_resources:
        target_study_id = source_to_gold.get(row["study_key"])

        if target_study_id:
            add_resource(row, target_study_id, "wordpress")

    for row in youtube_resources:
        target_study_id = source_to_gold.get(row["study_key"])

        if target_study_id:
            add_resource(row, target_study_id, "youtube")

    resource_counts = Counter(
        resource["study_id"]
        for resource in resources_by_identity.values()
    )

    for study_id, study in studies.items():
        study["resource_count"] = resource_counts[study_id]

    study_rows = sorted(
        studies.values(),
        key=lambda row: (row["study_type"], row.get("study_date") or "", row["title"]),
    )
    resource_rows = sorted(
        resources_by_identity.values(),
        key=lambda row: (row["study_id"], row["position"], row["canonical_url"]),
    )
    origin_rows = sorted(
        origins_by_identity.values(),
        key=lambda row: (row["study_id"], row["source_system"], row["source_url"]),
    )
    return study_rows, resource_rows, origin_rows


def run() -> dict[str, int]:
    run_id = begin_study_processing_run(
        "study_silver_to_gold",
        "silver_study_wordpress,silver_study_youtube",
    )

    try:
        with get_engine().begin() as conn:
            ensure_study_schema(conn)
            study_rows, resource_rows, origin_rows = aggregate_records(conn)
            conn.execute(text("DELETE FROM gold_study_origins"))
            conn.execute(text("DELETE FROM gold_study_resources"))
            conn.execute(text("DELETE FROM gold_studies"))

            if study_rows:
                conn.execute(text(INSERT_GOLD_STUDY_SQL), study_rows)

            if resource_rows:
                conn.execute(text(INSERT_GOLD_RESOURCE_SQL), resource_rows)

            if origin_rows:
                conn.execute(text(INSERT_GOLD_ORIGIN_SQL), origin_rows)

            apply_enrichments(conn)

        finish_study_processing_run(run_id, "success")
        result = {
            "studies": len(study_rows),
            "resources": len(resource_rows),
            "origins": len(origin_rows),
        }
        print(f"Independent study silver tables merged into gold: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

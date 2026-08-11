from __future__ import annotations

import hashlib
from collections import Counter

from sqlalchemy import text

from shared.db import get_engine, utc_now_iso
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)


INSERT_GOLD_STUDY_SQL = """
INSERT INTO gold_studies (
    study_id,
    study_type,
    title,
    study_date,
    study_year,
    collection_title,
    source_system,
    source_url,
    resource_count,
    last_aggregated_at
)
VALUES (
    :study_id,
    :study_type,
    :title,
    :study_date,
    :study_year,
    :collection_title,
    :source_system,
    :source_url,
    :resource_count,
    :last_aggregated_at
)
"""

INSERT_GOLD_RESOURCE_SQL = """
INSERT INTO gold_study_resources (
    resource_id,
    study_id,
    resource_type,
    label,
    source_url,
    canonical_url,
    mime_type,
    source_system,
    position
)
VALUES (
    :resource_id,
    :study_id,
    :resource_type,
    :label,
    :source_url,
    :canonical_url,
    :mime_type,
    :source_system,
    :position
)
"""


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


def aggregate_records(conn) -> tuple[list[dict], list[dict]]:
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

    for row in wordpress_studies:
        study_date = str(row.get("study_date") or "")
        studies[row["study_key"]] = {
            "study_id": row["study_key"],
            "study_type": row["study_type"],
            "title": row["title"],
            "study_date": study_date or None,
            "study_year": study_date[:4] if len(study_date) >= 4 else None,
            "collection_title": None,
            "source_system": "wordpress",
            "source_url": row.get("source_url"),
            "resource_count": 0,
            "last_aggregated_at": aggregated_at,
        }

    wordpress_youtube_owners = {
        row["canonical_url"]: row["study_key"]
        for row in wordpress_resources
        if row.get("resource_type") == "youtube"
    }
    youtube_target_by_study = {}

    for row in youtube_studies:
        canonical_video_url = (
            f"https://youtube.com/watch?v={row['youtube_video_id']}"
        )
        target_study_id = wordpress_youtube_owners.get(
            canonical_video_url,
            row["study_key"],
        )
        youtube_target_by_study[row["study_key"]] = target_study_id

        if target_study_id in studies:
            existing = studies[target_study_id]
            existing["source_system"] = combine_sources(
                existing["source_system"],
                "youtube",
            )

            if not existing.get("study_date") and row.get("study_date"):
                existing["study_date"] = row["study_date"]
                existing["study_year"] = str(row["study_date"])[:4]

            continue

        study_date = str(row.get("study_date") or "")
        studies[target_study_id] = {
            "study_id": target_study_id,
            "study_type": row["study_type"],
            "title": row["title"],
            "study_date": study_date or None,
            "study_year": study_date[:4] if len(study_date) >= 4 else None,
            "collection_title": row.get("collection_title") or None,
            "source_system": "youtube",
            "source_url": row.get("source_url"),
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
        add_resource(row, row["study_key"], "wordpress")

    for row in youtube_resources:
        target_study_id = youtube_target_by_study.get(
            row["study_key"],
            row["study_key"],
        )
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
    return study_rows, resource_rows


def run() -> dict[str, int]:
    run_id = begin_study_processing_run(
        "study_silver_to_gold",
        "silver_study_wordpress,silver_study_youtube",
    )

    try:
        with get_engine().begin() as conn:
            ensure_study_schema(conn)
            study_rows, resource_rows = aggregate_records(conn)
            conn.execute(text("DELETE FROM gold_study_resources"))
            conn.execute(text("DELETE FROM gold_studies"))

            if study_rows:
                conn.execute(text(INSERT_GOLD_STUDY_SQL), study_rows)

            if resource_rows:
                conn.execute(text(INSERT_GOLD_RESOURCE_SQL), resource_rows)

        finish_study_processing_run(run_id, "success")
        result = {
            "studies": len(study_rows),
            "resources": len(resource_rows),
        }
        print(f"Independent study silver tables merged into gold: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

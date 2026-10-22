from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from pipe.pipelines.studies.wordpress_parser import parse_public_studies
from pipe.pipelines.studies.youtube_resource_titles import (
    enrich_youtube_resource_titles,
)
from shared.db import get_engine, utc_now_iso
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)


DEFAULT_BRONZE_DIR = Path("data/bronze")
WORDPRESS_GLOB = "ibrvn.WordPress.*.xml"

INSERT_STUDY_SQL = """
INSERT INTO silver_study_wordpress (
    study_key,
    source_item_id,
    wordpress_post_id,
    study_type,
    title,
    study_date,
    source_url,
    collection_slug,
    payload_version,
    processed_at
)
VALUES (
    :study_key,
    :source_item_id,
    :wordpress_post_id,
    :study_type,
    :title,
    :study_date,
    :source_url,
    :collection_slug,
    :payload_version,
    :processed_at
)
"""

INSERT_RESOURCE_SQL = """
INSERT INTO silver_study_wordpress_resources (
    resource_key,
    study_key,
    resource_type,
    label,
    source_url,
    canonical_url,
    mime_type,
    position,
    processed_at
)
VALUES (
    :resource_key,
    :study_key,
    :resource_type,
    :label,
    :source_url,
    :canonical_url,
    :mime_type,
    :position,
    :processed_at
)
"""


def latest_wordpress_export(bronze_dir: Path = DEFAULT_BRONZE_DIR) -> Path:
    files = sorted(bronze_dir.glob(WORDPRESS_GLOB))

    if not files:
        raise FileNotFoundError(
            f"No WordPress export matching {WORDPRESS_GLOB!r} in {bronze_dir}"
        )

    return files[-1]


def run(input_path: Path | None = None) -> dict[str, int]:
    input_path = input_path or latest_wordpress_export()
    run_id = begin_study_processing_run(
        "study_wordpress_bronze_to_silver",
        str(input_path),
    )

    try:
        studies = parse_public_studies(input_path)
        enriched_youtube_titles = 0
        youtube_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()

        if not youtube_api_key:
            raise ValueError(
                "YOUTUBE_API_KEY is required to resolve WordPress YouTube "
                "resource titles."
            )

        studies, enriched_youtube_titles = enrich_youtube_resource_titles(
            studies,
            youtube_api_key,
        )
        type_counts = Counter(study.study_type for study in studies)
        required_types = {
            "ctb",
            "lecture_or_conference",
            "pfd",
            "weekly",
        }
        missing_types = sorted(required_types - set(type_counts))

        if missing_types:
            raise ValueError(
                "The public WordPress navigation did not yield study types: "
                + ", ".join(missing_types)
            )

        processed_at = utc_now_iso()
        payload_version = input_path.name
        study_rows = []
        resource_rows = []

        for study in studies:
            study_rows.append({
                "study_key": study.study_key,
                "source_item_id": study.source_item_id,
                "wordpress_post_id": study.wordpress_post_id,
                "study_type": study.study_type,
                "title": study.title,
                "study_date": study.study_date or None,
                "source_url": study.source_url,
                "collection_slug": study.collection_slug,
                "payload_version": payload_version,
                "processed_at": processed_at,
            })

            for resource in study.resources:
                resource_rows.append({
                    "resource_key": resource.resource_key,
                    "study_key": resource.study_key,
                    "resource_type": resource.resource_type,
                    "label": resource.label,
                    "source_url": resource.source_url,
                    "canonical_url": resource.canonical_url,
                    "mime_type": resource.mime_type or None,
                    "position": resource.position,
                    "processed_at": processed_at,
                })

        with get_engine().begin() as conn:
            ensure_study_schema(conn)
            conn.execute(text("DELETE FROM silver_study_wordpress_resources"))
            conn.execute(text("DELETE FROM silver_study_wordpress"))

            if study_rows:
                conn.execute(text(INSERT_STUDY_SQL), study_rows)

            if resource_rows:
                conn.execute(text(INSERT_RESOURCE_SQL), resource_rows)

        finish_study_processing_run(run_id, "success")
        result = {
            "studies": len(study_rows),
            "resources": len(resource_rows),
            "youtube_titles_enriched": enriched_youtube_titles,
            **dict(sorted(type_counts.items())),
        }
        print(f"WordPress studies saved to independent silver tables: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load public WordPress study pages from bronze into silver."
    )
    parser.add_argument("--input", type=Path, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.input)

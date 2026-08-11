from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from pipe.pipelines.studies.youtube_records import build_silver_records
from shared.db import get_engine, utc_now_iso
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)


DEFAULT_INPUT = Path("data/bronze/studies/youtube_studies.json")

UPSERT_STUDY_SQL = """
INSERT INTO silver_study_youtube (
    study_key,
    youtube_playlist_id,
    study_type,
    title,
    study_date,
    source_url,
    payload_version,
    processed_at
)
VALUES (
    :study_key,
    :youtube_playlist_id,
    :study_type,
    :title,
    :study_date,
    :source_url,
    :payload_version,
    :processed_at
)
ON CONFLICT(study_key) DO UPDATE SET
    youtube_playlist_id = EXCLUDED.youtube_playlist_id,
    study_type = EXCLUDED.study_type,
    title = EXCLUDED.title,
    study_date = EXCLUDED.study_date,
    source_url = EXCLUDED.source_url,
    payload_version = EXCLUDED.payload_version,
    processed_at = EXCLUDED.processed_at
"""

UPSERT_RESOURCE_SQL = """
INSERT INTO silver_study_youtube_resources (
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
ON CONFLICT(resource_key) DO UPDATE SET
    study_key = EXCLUDED.study_key,
    resource_type = EXCLUDED.resource_type,
    label = EXCLUDED.label,
    source_url = EXCLUDED.source_url,
    canonical_url = EXCLUDED.canonical_url,
    mime_type = EXCLUDED.mime_type,
    position = EXCLUDED.position,
    processed_at = EXCLUDED.processed_at
"""


def run(input_path: Path = DEFAULT_INPUT) -> dict[str, int | bool]:
    run_id = begin_study_processing_run(
        "study_youtube_bronze_to_silver",
        str(input_path),
    )

    try:
        with input_path.open(encoding="utf-8") as file_handle:
            payload = json.load(file_handle)

        processed_at = utc_now_iso()
        complete_snapshot = bool(payload.get("complete_snapshot"))
        study_rows, resource_rows = build_silver_records(payload, processed_at)

        with get_engine().begin() as conn:
            ensure_study_schema(conn)

            if complete_snapshot:
                conn.execute(text("DELETE FROM silver_study_youtube_resources"))
                conn.execute(text("DELETE FROM silver_study_youtube"))
            elif study_rows:
                conn.execute(text("""
                    DELETE FROM silver_study_youtube_resources
                    WHERE study_key = :study_key
                """), [{"study_key": row["study_key"]} for row in study_rows])

            if study_rows:
                conn.execute(text(UPSERT_STUDY_SQL), study_rows)

            if resource_rows:
                conn.execute(text(UPSERT_RESOURCE_SQL), resource_rows)

        finish_study_processing_run(run_id, "success")
        result = {
            "studies": len(study_rows),
            "resources": len(resource_rows),
            "complete_snapshot": complete_snapshot,
        }
        print(f"YouTube studies saved to independent silver tables: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load the independent YouTube study bronze into silver."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(arguments.input)

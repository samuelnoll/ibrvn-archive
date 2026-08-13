from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from sqlalchemy import text

from shared.db import get_engine, utc_now_iso
from shared.settings import STUDY_RESOURCE_RAW_DIR
from shared.study_db import (
    begin_study_processing_run,
    ensure_study_schema,
    finish_study_processing_run,
)


UPDATE_GOLD_RESOURCE_SQL = """
UPDATE gold_study_resources
SET original_filename = :original_filename,
    local_path = :local_path,
    download_link = :download_link,
    local_mime_type = :local_mime_type,
    duration_seconds = :duration_seconds,
    transcript_available = :transcript_available,
    resource_enriched_at = :resource_enriched_at
WHERE resource_id = :resource_id
  AND study_id = :study_id
"""


def build_download_link(local_path: str) -> str:
    if not local_path:
        return ""

    path = Path(local_path).resolve()
    root = STUDY_RESOURCE_RAW_DIR.resolve()

    try:
        relative_path = path.relative_to(root)
    except ValueError:
        return ""

    return f"/study-media/{quote(relative_path.as_posix(), safe='/')}"


def aggregate_rows(connection) -> list[dict]:
    rows = connection.execute(text("""
        SELECT
            ssra.resource_id,
            ssra.study_id,
            ssra.original_filename,
            ssra.local_path,
            ssra.mime_type AS local_mime_type,
            ssra.duration_seconds,
            CASE WHEN EXISTS (
                SELECT 1
                FROM silver_study_resource_transcripts ssrt
                WHERE ssrt.asset_id = ssra.asset_id
            ) THEN 1 ELSE 0 END AS transcript_available
        FROM silver_study_resource_assets ssra
        JOIN gold_study_resources gsr
          ON gsr.resource_id = ssra.resource_id
         AND gsr.study_id = ssra.study_id
        WHERE (
            ssra.source_kind != 'youtube'
            OR NOT EXISTS (
                SELECT 1
                FROM gold_study_resources direct_audio
                WHERE direct_audio.study_id = ssra.study_id
                  AND direct_audio.resource_type = 'audio'
            )
        )
        ORDER BY ssra.study_id, ssra.resource_id, ssra.asset_id
    """)).mappings().all()
    enriched_at = utc_now_iso()
    return [
        {
            **dict(row),
            "download_link": build_download_link(row["local_path"]),
            "resource_enriched_at": enriched_at,
        }
        for row in rows
    ]


def apply_enrichments(connection) -> list[dict]:
    rows = aggregate_rows(connection)
    connection.execute(text("""
        UPDATE gold_study_resources
        SET original_filename = NULL,
            local_path = NULL,
            download_link = NULL,
            local_mime_type = NULL,
            duration_seconds = NULL,
            transcript_available = 0,
            resource_enriched_at = NULL
    """))

    if rows:
        connection.execute(text(UPDATE_GOLD_RESOURCE_SQL), rows)

    return rows


def run() -> dict[str, int]:
    run_id = begin_study_processing_run(
        "study_resource_silver_to_gold",
        "silver_study_resource_assets",
    )

    try:
        with get_engine().begin() as connection:
            ensure_study_schema(connection)
            rows = apply_enrichments(connection)

        result = {"enriched_resources": len(rows)}
        finish_study_processing_run(run_id, "success")
        print(f"Study resource fields published to gold: {result}")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

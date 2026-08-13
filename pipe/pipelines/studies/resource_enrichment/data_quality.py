from __future__ import annotations

import argparse
from pathlib import Path

from shared.db import fetch_all
from shared.study_db import begin_study_processing_run, finish_study_processing_run

from .common import (
    build_study_date_scope,
    fetch_gold_resource_rows,
    is_mp3_asset,
    select_download_candidates,
)


def run(loopback_days=None) -> dict[str, int]:
    run_id = begin_study_processing_run(
        "study_resource_data_quality",
        "study resource enrichment tables",
    )

    try:
        candidates = select_download_candidates(
            fetch_gold_resource_rows(loopback_days)
        )
        scope_sql, params = build_study_date_scope("gs", loopback_days)
        assets = fetch_all(f"""
            SELECT ssra.*
            FROM silver_study_resource_assets ssra
            JOIN gold_studies gs ON gs.study_id = ssra.study_id
            WHERE 1 = 1
            {scope_sql}
        """, params)
        transcripts = fetch_all(f"""
            SELECT DISTINCT ssrt.asset_id
            FROM silver_study_resource_transcripts ssrt
            JOIN silver_study_resource_assets ssra
              ON ssra.asset_id = ssrt.asset_id
            JOIN gold_studies gs ON gs.study_id = ssra.study_id
            WHERE 1 = 1
            {scope_sql}
        """, params)
        candidate_resource_ids = {
            row["resource_id"]
            for row in candidates
        }
        assets = [
            row
            for row in assets
            if row["resource_id"] in candidate_resource_ids
        ]
        assets_by_resource = {row["resource_id"]: row for row in assets}
        transcript_asset_ids = {row["asset_id"] for row in transcripts}
        missing_downloads = 0

        for candidate in candidates:
            asset = assets_by_resource.get(candidate["resource_id"])

            if not asset or not Path(asset.get("local_path") or "").is_file():
                missing_downloads += 1

        mp3_assets = [row for row in assets if is_mp3_asset(row)]
        result = {
            "eligible_resources": len(candidates),
            "downloaded_assets": len(assets),
            "downloads_missing": missing_downloads,
            "durations_missing": sum(
                1 for row in mp3_assets if row.get("duration_seconds") is None
            ),
            "transcripts_missing": sum(
                1 for row in mp3_assets if row["asset_id"] not in transcript_asset_ids
            ),
        }

        print("Study resource data quality summary")
        print(f"loopback_days: {loopback_days if loopback_days is not None else 'all'}")

        for key, value in result.items():
            print(f"{key}: {value}")

        finish_study_processing_run(run_id, "success")
        return result
    except Exception:
        finish_study_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loopback-days", type=int, default=None)
    arguments = parser.parse_args()
    run(arguments.loopback_days)

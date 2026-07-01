from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text

from shared.db import (
    begin_processing_run,
    ensure_schema,
    fetch_all,
    finish_processing_run,
    get_engine,
    utc_now_iso,
)


UPSERT_GOLD_SQL = """
INSERT INTO gold_sermons (
    canonical_sermon_id,
    preaching_date,
    title,
    preacher_name,
    text_reference,
    serie,
    youtube_link,
    wordpress_link,
    media_link,
    duration_seconds,
    summary_short,
    transcript_available,
    last_aggregated_at
)
VALUES (
    :canonical_sermon_id,
    :preaching_date,
    :title,
    :preacher_name,
    :text_reference,
    :serie,
    :youtube_link,
    :wordpress_link,
    :media_link,
    :duration_seconds,
    :summary_short,
    :transcript_available,
    :last_aggregated_at
)
ON CONFLICT(canonical_sermon_id) DO UPDATE SET
    preaching_date = EXCLUDED.preaching_date,
    title = EXCLUDED.title,
    preacher_name = EXCLUDED.preacher_name,
    text_reference = EXCLUDED.text_reference,
    serie = EXCLUDED.serie,
    youtube_link = EXCLUDED.youtube_link,
    wordpress_link = EXCLUDED.wordpress_link,
    media_link = EXCLUDED.media_link,
    duration_seconds = EXCLUDED.duration_seconds,
    summary_short = EXCLUDED.summary_short,
    transcript_available = EXCLUDED.transcript_available,
    last_aggregated_at = EXCLUDED.last_aggregated_at
"""


def metadata_priority(row):

    priorities = {
        "wordpress": 0,
        "youtube": 1,
    }

    return priorities.get(row.get("source_system", ""), 99)


def choose_first_non_empty(rows, field_name):

    for row in sorted(rows, key=metadata_priority):
        value = row.get(field_name)

        if value not in (None, ""):
            return value

    return ""


def aggregate_gold_records():

    metadata_rows = fetch_all("""
        SELECT
            canonical_sermon_id,
            source_system,
            source_item_id,
            preaching_date,
            title,
            preacher_name,
            text_reference,
            serie,
            confidence,
            processed_at
        FROM silver_sermon_metadata
        ORDER BY processed_at DESC
    """)

    if not metadata_rows:
        return []

    media_rows = fetch_all("""
        SELECT
            canonical_sermon_id,
            asset_type,
            source_url,
            local_path,
            duration_seconds,
            mime_type
        FROM silver_media_assets
    """)

    transcript_rows = fetch_all("""
        SELECT
            canonical_sermon_id,
            transcript_version,
            transcript_text,
            created_at
        FROM silver_transcripts
        ORDER BY created_at DESC
    """)

    summary_rows = fetch_all("""
        SELECT
            canonical_sermon_id,
            summary_version,
            summary_text,
            created_at
        FROM silver_summaries
        ORDER BY created_at DESC
    """)

    metadata_by_sermon = defaultdict(list)
    media_by_sermon = defaultdict(dict)
    transcripts_by_sermon = defaultdict(list)
    summaries_by_sermon = defaultdict(list)

    for row in metadata_rows:
        metadata_by_sermon[row["canonical_sermon_id"]].append(row)

    for row in media_rows:
        media_by_sermon[row["canonical_sermon_id"]][row["asset_type"]] = row

    for row in transcript_rows:
        transcripts_by_sermon[row["canonical_sermon_id"]].append(row)

    for row in summary_rows:
        summaries_by_sermon[row["canonical_sermon_id"]].append(row)

    aggregated_at = utc_now_iso()
    gold_records = []

    for canonical_sermon_id, rows in metadata_by_sermon.items():
        preaching_date = choose_first_non_empty(rows, "preaching_date")
        youtube_media = media_by_sermon[canonical_sermon_id].get("youtube_video", {})
        audio_media = media_by_sermon[canonical_sermon_id].get("audio", {})
        wordpress_rows = [
            row for row in rows
            if row.get("source_system") == "wordpress"
        ]
        latest_summary = summaries_by_sermon[canonical_sermon_id][0] if summaries_by_sermon[canonical_sermon_id] else {}

        gold_records.append({
            "canonical_sermon_id": canonical_sermon_id,
            "preaching_date": preaching_date,
            "title": choose_first_non_empty(rows, "title"),
            "preacher_name": choose_first_non_empty(rows, "preacher_name"),
            "text_reference": choose_first_non_empty(rows, "text_reference"),
            "serie": choose_first_non_empty(rows, "serie"),
            "youtube_link": youtube_media.get("source_url", ""),
            "wordpress_link": (
                wordpress_rows[0]["source_item_id"]
                if wordpress_rows else ""
            ),
            "media_link": (
                audio_media.get("source_url")
                or audio_media.get("local_path")
                or ""
            ),
            "duration_seconds": audio_media.get("duration_seconds"),
            "summary_short": latest_summary.get("summary_text", ""),
            "transcript_available": 1 if transcripts_by_sermon[canonical_sermon_id] else 0,
            "last_aggregated_at": aggregated_at,
        })

    return gold_records


def run():

    run_id = begin_processing_run(
        "silver_to_gold_refresh",
        "silver_sermon_metadata",
    )

    try:
        records = aggregate_gold_records()

        with get_engine().begin() as conn:
            ensure_schema(conn)

            if records:
                conn.execute(text(UPSERT_GOLD_SQL), records)

        finish_processing_run(run_id, "success")
        print("Gold sermons refreshed from silver tables")

    except Exception:
        finish_processing_run(run_id, "failed")
        raise


if __name__ == "__main__":
    run()

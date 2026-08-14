from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text

from pipe.pipelines.studies.resource_enrichment.common import (
    candidate_filename,
    normalize_loopback_days,
    select_download_candidates,
    youtube_video_id,
)
from pipe.pipelines.studies.resource_enrichment.silver_to_gold import (
    apply_enrichments,
    aggregate_rows,
)
from shared.settings import STUDY_RESOURCE_RAW_DIR
from shared.study_db import ensure_study_schema


def resource(
    resource_id: str,
    study_id: str,
    resource_type: str,
    source_url: str,
    label: str,
) -> dict:
    return {
        "resource_id": resource_id,
        "study_id": study_id,
        "resource_type": resource_type,
        "source_url": source_url,
        "canonical_url": source_url,
        "label": label,
        "mime_type": "",
    }


class StudyResourceEnrichmentTest(unittest.TestCase):
    def test_youtube_audio_is_skipped_when_study_has_direct_audio(self):
        rows = [
            resource("audio-1", "study-1", "audio", "https://site/aula.mp3", "aula.mp3"),
            resource("youtube-1", "study-1", "youtube", "https://youtube.com/watch?v=one", "Aula"),
            resource("pdf-1", "study-1", "pdf", "https://site/apostila.pdf", "apostila.pdf"),
            resource("youtube-2", "study-2", "youtube", "https://youtu.be/two", "Aula 2"),
            resource(
                "playlist",
                "study-2",
                "youtube",
                "https://youtube.com/playlist?list=PL1",
                "Curso",
            ),
            resource("word-1", "study-2", "word", "https://site/roteiro.docx", "roteiro.docx"),
        ]

        candidates = select_download_candidates(rows)

        self.assertEqual(
            {"audio-1", "pdf-1", "youtube-2", "word-1"},
            {row["resource_id"] for row in candidates},
        )
        youtube = next(row for row in candidates if row["resource_id"] == "youtube-2")
        self.assertEqual("audio", youtube["asset_type"])
        self.assertEqual("youtube", youtube["source_kind"])

    def test_original_direct_filename_and_youtube_mp3_name_are_preserved(self):
        direct = {
            **resource(
                "pdf-1",
                "study-1",
                "pdf",
                "https://site/files/Apostila%20do%20Curso.pdf?download=1",
                "Apostila do Curso.pdf",
            ),
            "source_kind": "direct",
        }
        youtube = {
            **resource(
                "youtube-1",
                "study-1",
                "youtube",
                "https://youtube.com/watch?v=abc123",
                "Aula 1: Introducao",
            ),
            "source_kind": "youtube",
        }

        self.assertEqual("Apostila do Curso.pdf", candidate_filename(direct))
        self.assertEqual("Aula 1_ Introducao.mp3", candidate_filename(youtube))
        self.assertEqual("abc123", youtube_video_id(youtube["source_url"]))
        self.assertEqual("short123", youtube_video_id("https://youtube.com/shorts/short123"))

    def test_loopback_days_rejects_non_positive_values(self):
        self.assertIsNone(normalize_loopback_days(None))
        self.assertEqual(30, normalize_loopback_days("30"))

        with self.assertRaises(ValueError):
            normalize_loopback_days(0)

    def test_silver_enrichment_is_projected_into_gold_resource(self):
        engine = create_engine("sqlite:///:memory:")
        local_path = str(STUDY_RESOURCE_RAW_DIR / "study" / "resource" / "aula.mp3")

        with engine.begin() as connection:
            ensure_study_schema(connection)
            connection.execute(text("""
                INSERT INTO gold_studies (
                    study_id, study_type, title, study_date, study_year,
                    collection_title, source_system, source_url,
                    resource_count, last_aggregated_at
                ) VALUES (
                    'study-1', 'ctb', 'Curso', '2024-01-01', '2024',
                    NULL, 'wordpress', 'https://site/curso', 1, 'now'
                )
            """))
            connection.execute(text("""
                INSERT INTO gold_study_resources (
                    resource_id, study_id, resource_type, label, source_url,
                    canonical_url, mime_type, source_system, position
                ) VALUES (
                    'resource-1', 'study-1', 'audio', 'aula.mp3',
                    'https://site/aula.mp3', 'https://site/aula.mp3',
                    'audio/mpeg', 'wordpress', 1
                )
            """))
            connection.execute(text("""
                INSERT INTO gold_study_resources (
                    resource_id, study_id, resource_type, label, source_url,
                    canonical_url, mime_type, source_system, position
                ) VALUES (
                    'youtube-1', 'study-1', 'youtube', 'Video',
                    'https://youtube.com/watch?v=abc',
                    'https://youtube.com/watch?v=abc',
                    'video/youtube', 'youtube', 2
                )
            """))
            connection.execute(text("""
                INSERT INTO silver_study_resource_assets (
                    asset_id, resource_id, study_id, asset_type, source_kind,
                    source_url, original_filename, local_path, mime_type,
                    duration_seconds, downloaded_at, updated_at
                ) VALUES (
                    'asset-1', 'resource-1', 'study-1', 'audio', 'direct',
                    'https://site/aula.mp3', 'aula.mp3', :local_path, 'audio/mpeg',
                    120.0, 'now', 'now'
                )
            """), {"local_path": local_path})
            connection.execute(text("""
                INSERT INTO silver_study_resource_transcripts (
                    asset_id, transcript_version, language, transcript_text,
                    model_name, created_at
                ) VALUES ('asset-1', 1, 'pt', 'Texto', 'model', 'now')
            """))
            connection.execute(text("""
                INSERT INTO silver_study_resource_assets (
                    asset_id, resource_id, study_id, asset_type, source_kind,
                    source_url, original_filename, local_path, mime_type,
                    duration_seconds, downloaded_at, updated_at
                ) VALUES (
                    'youtube-asset', 'youtube-1', 'study-1', 'audio', 'youtube',
                    'https://youtube.com/watch?v=abc', 'Video.mp3',
                    '/app/data/resource/raw/Video.mp3', 'audio/mpeg',
                    100.0, 'now', 'now'
                )
            """))
            rows = aggregate_rows(connection)
            apply_enrichments(connection)
            gold_audio = dict(connection.execute(text("""
                SELECT * FROM gold_study_resources
                WHERE resource_id = 'resource-1'
            """)).mappings().one())
            gold_youtube = dict(connection.execute(text("""
                SELECT * FROM gold_study_resources
                WHERE resource_id = 'youtube-1'
            """)).mappings().one())

        self.assertEqual(1, len(rows))
        self.assertEqual("aula.mp3", rows[0]["original_filename"])
        self.assertEqual(120.0, rows[0]["duration_seconds"])
        self.assertEqual(1, rows[0]["transcript_available"])
        self.assertEqual("aula.mp3", gold_audio["original_filename"])
        self.assertEqual(local_path, gold_audio["local_path"])
        self.assertEqual(
            "/study-media/study/resource/aula.mp3",
            gold_audio["download_link"],
        )
        self.assertEqual("audio/mpeg", gold_audio["local_mime_type"])
        self.assertEqual(120.0, gold_audio["duration_seconds"])
        self.assertEqual(1, gold_audio["transcript_available"])
        self.assertIsNone(gold_youtube["local_path"])
        self.assertEqual(0, gold_youtube["transcript_available"])

    def test_legacy_enrichment_table_is_migrated_and_removed(self):
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE gold_study_resources (
                    resource_id TEXT PRIMARY KEY,
                    study_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    label TEXT,
                    source_url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    mime_type TEXT,
                    source_system TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    UNIQUE (study_id, canonical_url)
                )
            """))
            connection.execute(text("""
                INSERT INTO gold_study_resources (
                    resource_id, study_id, resource_type, label, source_url,
                    canonical_url, mime_type, source_system, position
                ) VALUES (
                    'resource-1', 'study-1', 'audio', 'aula.mp3',
                    'https://site/aula.mp3', 'https://site/aula.mp3',
                    'audio/mpeg', 'wordpress', 1
                )
            """))
            connection.execute(text("""
                CREATE TABLE gold_study_resource_enrichments (
                    asset_id TEXT PRIMARY KEY,
                    resource_id TEXT NOT NULL,
                    study_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    mime_type TEXT,
                    duration_seconds REAL,
                    transcript_available INTEGER NOT NULL DEFAULT 0,
                    last_aggregated_at TEXT NOT NULL,
                    UNIQUE (resource_id, local_path)
                )
            """))
            connection.execute(text("""
                INSERT INTO gold_study_resource_enrichments (
                    asset_id, resource_id, study_id, asset_type, source_kind,
                    original_filename, local_path, mime_type, duration_seconds,
                    transcript_available, last_aggregated_at
                ) VALUES (
                    'asset-1', 'resource-1', 'study-1', 'audio', 'direct',
                    'aula.mp3', '/data/aula.mp3', 'audio/mpeg', 90.0, 1, 'now'
                )
            """))

            ensure_study_schema(connection)
            migrated = dict(connection.execute(text("""
                SELECT * FROM gold_study_resources
                WHERE resource_id = 'resource-1'
            """)).mappings().one())
            legacy_exists = connection.execute(text("""
                SELECT COUNT(*)
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'gold_study_resource_enrichments'
            """)).scalar_one()

        self.assertEqual("aula.mp3", migrated["original_filename"])
        self.assertEqual("/data/aula.mp3", migrated["local_path"])
        self.assertEqual(90.0, migrated["duration_seconds"])
        self.assertEqual(1, migrated["transcript_available"])
        self.assertEqual(0, legacy_exists)


if __name__ == "__main__":
    unittest.main()

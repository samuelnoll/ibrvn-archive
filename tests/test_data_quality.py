from __future__ import annotations

from datetime import date
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.main import app, templates
from pipe.pipelines.audio.data_quality import calculate_snapshot, is_valid_link


class DataQualityTest(unittest.TestCase):
    def test_quality_route_is_hidden_from_navigation_and_noindexed(self):
        self.assertIn("/qualidade", {route.path for route in app.routes})
        self.assertIn("/qualidade/export.csv", {route.path for route in app.routes})

        request = SimpleNamespace(url=SimpleNamespace(path="/qualidade"))
        rendered = templates.env.get_template("quality.html").render(
            request=request,
            run=None,
            metrics=[],
            history=[],
            issues=[],
            selected_metric=None,
            years=[],
            sources=[],
            preachers=[],
            selected_year="",
            selected_source="",
            selected_preacher="",
            last_pipeline_success="",
            latest_attempt=None,
            last_update="",
        )
        self.assertIn('<meta name="robots" content="noindex, nofollow">', rendered)
        self.assertNotIn('href="/qualidade"', rendered)
        self.assertIn("Ainda não há medições", rendered)

    def test_snapshot_calculates_coverage_and_sunday_exceptions(self):
        sermon = {
            "canonical_sermon_id": "sermon-1",
            "preaching_date": "2026-09-27",
            "title": "Uma pregação",
            "preacher_name": "Pregador",
            "text_reference": "João 1",
            "serie": "Série",
            "youtube_link": "https://youtube.com/watch?v=1",
            "wordpress_link": "https://ibrvn.com/pregacao",
            "media_link": "https://ibrvn.com/audio.mp3",
            "download_link": "/media/audio.mp3",
        }
        metadata = [{
            "canonical_sermon_id": "sermon-1",
            "source_system": "wordpress",
            "source_item_id": "https://ibrvn.com/pregacao",
            "preaching_date": "2026-09-27",
            "title": "Uma pregação",
            "preacher_name": "Pregador",
        }]
        media = [{
            "canonical_sermon_id": "sermon-1",
            "asset_type": "audio",
            "local_path": "/audio/audio.mp3",
            "duration_seconds": 1800,
        }]
        transcripts = [{
            "canonical_sermon_id": "sermon-1",
            "transcript_version": 1,
            "transcript_text": "palavra " * 120,
            "created_at": "2026-09-28T00:00:00+00:00",
        }]

        def fake_fetch(query):
            if "FROM gold_sermons" in query:
                return [sermon]
            if "FROM silver_sermon_metadata" in query:
                return metadata
            if "FROM silver_media_assets" in query:
                return media
            if "FROM silver_transcripts" in query:
                return transcripts
            if "data_quality_sunday_exceptions" in query:
                return [{"preaching_date": "2026-10-04", "reason": "Culto cancelado"}]
            if "FROM silver_processing_runs" in query:
                return []
            raise AssertionError(query)

        with patch(
            "pipe.pipelines.audio.data_quality.fetch_all", side_effect=fake_fetch,
        ), patch("pathlib.Path.is_file", return_value=True), patch(
            "pipe.pipelines.audio.data_quality.check_external_link_health",
            return_value={},
        ):
            snapshot = calculate_snapshot(today=date(2026, 10, 22))

        values = {item["metric_key"]: item["value"] for item in snapshot["metrics"]}
        self.assertEqual(1, values["total_sermons"])
        self.assertEqual(1, values["youtube_link"])
        self.assertEqual(0, values["missing_mp3"])
        self.assertEqual(0, values["mp3_without_transcript"])
        self.assertEqual(1, values["justified_missing_sundays"])
        self.assertEqual(1, values["missing_sundays"])

    def test_link_validation_accepts_web_and_internal_links(self):
        self.assertTrue(is_valid_link("https://youtube.com/watch?v=1"))
        self.assertTrue(is_valid_link("/media/sermon.mp3"))
        self.assertFalse(is_valid_link("youtube.com/watch?v=1"))
        self.assertFalse(is_valid_link("javascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.main import app, templates
from api.study_queries import (
    get_study_detail,
    get_study_resource_transcript,
)


class StudyResourcePagesTest(unittest.TestCase):
    def test_study_detail_groups_local_audio_and_exposes_enrichment(self):
        study_row = {
            "study_id": "historia-da-igreja",
            "study_type": "ctb",
            "title": "Historia da Igreja",
            "study_date": "2014-11-02",
            "study_year": "2014",
            "collection_title": None,
            "source_system": "wordpress",
            "source_url": "https://example.com/estudo",
            "resource_count": 2,
        }
        resources = [
            {
                "resource_id": "youtube-audio",
                "resource_type": "youtube",
                "label": "Aula 1",
                "source_url": "https://youtube.com/watch?v=abc",
                "mime_type": None,
                "source_system": "youtube",
                "position": 1,
                "original_filename": "Aula 1.mp3",
                "local_path": "historia/aula-1.mp3",
                "download_link": "/study-media/historia/aula-1.mp3",
                "local_mime_type": "audio/mpeg",
                "duration_seconds": 2667,
                "transcript_available": 1,
            },
            {
                "resource_id": "apostila",
                "resource_type": "pdf",
                "label": "Apostila",
                "source_url": "https://example.com/apostila.pdf",
                "mime_type": "application/pdf",
                "source_system": "wordpress",
                "position": 2,
                "original_filename": "Apostila Historia.pdf",
                "local_path": "historia/apostila.pdf",
                "download_link": "/study-media/historia/apostila.pdf",
                "local_mime_type": "application/pdf",
                "duration_seconds": None,
                "transcript_available": 0,
            },
        ]

        with (
            patch("api.study_queries.fetch_one", return_value=study_row),
            patch("api.study_queries.fetch_all", side_effect=[[], resources]),
        ):
            study = get_study_detail("historia-da-igreja")

        self.assertIsNotNone(study)
        self.assertEqual(["audio", "documents"], [
            group["resource_type"] for group in study["resource_groups"]
        ])
        audio = study["resource_groups"][0]["resources"][0]
        self.assertEqual("Aula 1.mp3", audio["display_label"])
        self.assertEqual("44 min", audio["duration_display"])
        self.assertTrue(audio["has_local_audio"])

        request = SimpleNamespace(url=SimpleNamespace(path="/studies/historia"))
        rendered = templates.env.get_template("study_detail.html").render(
            request=request,
            study=study,
            last_update="agora",
        )

        self.assertIn('class="study-audio-resource"', rendered)
        self.assertIn('class="sermon-player study-resource-player" data-audio-player', rendered)
        self.assertIn('<audio preload="metadata" src="/study-media/historia/aula-1.mp3">', rendered)
        self.assertIn('class="sermon-player-volume-popover"', rendered)
        self.assertIn('class="sermon-player-speed-menu"', rendered)
        self.assertIn('href="https://youtube.com/watch?v=abc"', rendered)
        self.assertIn('href="/study-media/historia/aula-1.mp3" download', rendered)
        self.assertIn('href="/study-transcripts/youtube-audio"', rendered)
        self.assertIn("Apostila Historia.pdf", rendered)
        self.assertLess(
            rendered.index('class="study-resource-summary"'),
            rendered.index('class="sermon-player study-resource-player"'),
        )

    def test_study_transcript_query_and_page_are_available(self):
        transcript_row = {
            "resource_id": "youtube-audio",
            "study_id": "historia-da-igreja",
            "resource_label": "Aula 1.mp3",
            "study_title": "Historia da Igreja",
            "study_type": "ctb",
            "study_date": "2014-11-02",
            "transcript_version": 1,
            "language": "pt",
            "transcript_text": "Conteudo transcrito.",
            "model_name": "whisper",
            "created_at": "2026-08-13T12:00:00Z",
        }

        with patch("api.study_queries.fetch_one", return_value=transcript_row):
            transcript = get_study_resource_transcript("youtube-audio")

        self.assertEqual("02/11/2014", transcript["study_date_display"])
        self.assertEqual("Centro de Treinamento B\u00edblico", transcript["study_type_label"])
        self.assertIn("/study-transcripts/{resource_id}", {
            route.path for route in app.routes
        })
        self.assertIn("/study-media", {route.path for route in app.routes})

        request = SimpleNamespace(
            url=SimpleNamespace(path="/study-transcripts/youtube-audio")
        )
        rendered = templates.env.get_template(
            "study_resource_transcript.html"
        ).render(
            request=request,
            transcript=transcript,
            last_update="agora",
        )

        self.assertIn('href="/studies/historia-da-igreja"', rendered)
        self.assertIn("Aula 1.mp3", rendered)
        self.assertIn("Historia da Igreja", rendered)
        self.assertIn("Conteudo transcrito.", rendered)


if __name__ == "__main__":
    unittest.main()

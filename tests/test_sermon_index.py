from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.main import app, templates
from api.queries import classify_testament, get_sermon_testament_composition
from api.study_queries import get_study_type_composition


SAMPLE_SERMON = {
    "canonical_sermon_id": "sample",
    "preaching_date": "2026-08-10",
    "title": "Pregacao de teste",
    "text_reference": "Joao 1:1",
    "book_name": "Joao",
    "preacher_name": "Pregador",
    "serie": "Serie",
    "duration_minutes": "30 min",
    "media_link": None,
    "download_link": "/media/sample.mp3",
    "youtube_link": None,
    "wordpress_link": None,
    "transcript_available": 1,
}

class SermonIndexTest(unittest.TestCase):
    def test_sermon_index_route_and_navigation_are_available(self):
        self.assertIn("/sermons", {route.path for route in app.routes})
        request = SimpleNamespace(url=SimpleNamespace(path="/sermons"))
        rendered = templates.env.get_template("sermon_index.html").render(
            request=request,
            sermons=[SAMPLE_SERMON],
            last_update="agora",
        )

        self.assertEqual(1, rendered.count('id="search"'))
        self.assertIn('href="/sermons" aria-current="page"', rendered)
        self.assertIn('<h1 class="archive-index-title">Prega&ccedil;&otilde;es</h1>', rendered)
        self.assertIn(
            '<div class="sermon-player" data-audio-player>',
            rendered,
        )
        self.assertIn('<audio preload="metadata" src="/media/sample.mp3">', rendered)
        self.assertIn('class="sermon-player-progress"', rendered)
        self.assertIn('class="sermon-player-details"', rendered)
        self.assertNotIn("sermon-audio-player", rendered)
        self.assertLess(
            rendered.index('class="sermon-facts"'),
            rendered.index('class="sermon-player"'),
        )
        self.assertLess(
            rendered.index('class="sermon-player"'),
            rendered.index('class="sermon-actions"'),
        )
        self.assertIn("const audioPlayer = sermon.download_link", rendered)
        self.assertIn('<script src="/static/audio-player.js" defer></script>', rendered)
        self.assertEqual(2, rendered.count('class="site-nav-divider"'))
        self.assertNotIn('class="archive-nav-group', rendered)

        for destination in ("/books", "/series", "/preachers", "/years"):
            self.assertIn(f'href="{destination}"', rendered)

    def test_home_presents_only_sermon_and_study_buttons(self):
        request = SimpleNamespace(url=SimpleNamespace(path="/"))
        rendered = templates.env.get_template("home.html").render(
            request=request,
            stats={"sermons": 1, "preachers": 1, "series": 1},
            study_stats={"studies": 1, "resources": 1},
            sermon_composition={
                "old": 1,
                "new": 2,
                "classified": 3,
                "unclassified": 0,
                "old_percentage": 33,
                "new_percentage": 67,
            },
            study_composition=[
                {"label": "CTB", "count": 1, "percentage": 100},
            ],
            last_update="agora",
        )

        self.assertNotIn('id="search"', rendered)
        self.assertIn('class="home-library-grid"', rendered)
        self.assertEqual(2, rendered.count('class="home-library-button"'))
        self.assertIn('class="home-library-button" href="/sermons"', rendered)
        self.assertIn('class="home-library-button" href="/studies"', rendered)
        self.assertNotIn('class="home-stats"', rendered)
        self.assertIn('Prega&ccedil;&otilde;es por testamento', rendered)
        self.assertIn('Novo Testamento', rendered)
        self.assertIn('Antigo Testamento', rendered)
        self.assertIn('--new-testament-share: 67%;', rendered)
        self.assertIn('Estudos por categoria', rendered)

    def test_testament_composition_classifies_portuguese_references(self):
        self.assertEqual("old", classify_testament("Gênesis 1:1"))
        self.assertEqual("old", classify_testament("1 Samuel 3"))
        self.assertEqual("new", classify_testament("João 3:16"))
        self.assertEqual("new", classify_testament("2Tm 3:16"))
        self.assertEqual("", classify_testament("Tema sem referência"))

        with patch("api.queries.fetch_all", return_value=[
            {"text_reference": "Salmo 23"},
            {"text_reference": "Mateus 5"},
            {"text_reference": "Romanos 8"},
            {"text_reference": ""},
        ]):
            composition = get_sermon_testament_composition()

        self.assertEqual(1, composition["old"])
        self.assertEqual(2, composition["new"])
        self.assertEqual(1, composition["unclassified"])
        self.assertEqual(67, composition["new_percentage"])

    def test_study_composition_preserves_catalog_order(self):
        with patch("api.study_queries.fetch_all", return_value=[
            {"study_type": "pfd", "studies": 4},
            {"study_type": "ctb", "studies": 8},
        ]):
            composition = get_study_type_composition()

        self.assertEqual(
            ["ctb", "lecture_or_conference", "weekly", "pfd"],
            [item["study_type"] for item in composition],
        )
        self.assertEqual(100, composition[0]["percentage"])
        self.assertEqual(50, composition[3]["percentage"])

    def test_study_index_has_title_and_active_header_link(self):
        request = SimpleNamespace(url=SimpleNamespace(path="/studies"))
        rendered = templates.env.get_template("studies.html").render(
            request=request,
            catalog=[],
            last_update="agora",
        )

        self.assertIn('<h1 class="archive-index-title">Estudos</h1>', rendered)
        self.assertIn('href="/">Home</a>', rendered)
        self.assertIn(
            'class="site-nav-section-link" href="/studies" aria-current="page"',
            rendered,
        )
        self.assertNotIn('class="archive-nav-group', rendered)


if __name__ == "__main__":
    unittest.main()

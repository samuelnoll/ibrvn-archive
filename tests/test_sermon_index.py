from __future__ import annotations

import unittest
from types import SimpleNamespace

from api.main import app, templates


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
            '<audio class="sermon-audio-player" controls preload="none" '
            'src="/media/sample.mp3">',
            rendered,
        )
        self.assertLess(
            rendered.index('class="sermon-facts"'),
            rendered.index('class="sermon-audio-player"'),
        )
        self.assertLess(
            rendered.index('class="sermon-audio-player"'),
            rendered.index('class="sermon-actions"'),
        )
        self.assertIn("const audioPlayer = sermon.download_link", rendered)

        for destination in ("/books", "/series", "/preachers", "/years"):
            self.assertIn(f'href="{destination}"', rendered)

    def test_home_presents_only_sermon_and_study_buttons(self):
        request = SimpleNamespace(url=SimpleNamespace(path="/"))
        rendered = templates.env.get_template("home.html").render(
            request=request,
            stats={"sermons": 1, "preachers": 1, "series": 1},
            study_stats={"studies": 1, "resources": 1},
            last_update="agora",
        )

        self.assertNotIn('id="search"', rendered)
        self.assertIn('class="home-library-grid"', rendered)
        self.assertEqual(2, rendered.count('class="home-library-button"'))
        self.assertIn('class="home-library-button" href="/sermons"', rendered)
        self.assertIn('class="home-library-button" href="/studies"', rendered)

    def test_study_index_has_title_and_matching_header_group(self):
        request = SimpleNamespace(url=SimpleNamespace(path="/studies"))
        rendered = templates.env.get_template("studies.html").render(
            request=request,
            catalog=[],
            last_update="agora",
        )

        self.assertIn('<h1 class="archive-index-title">Estudos</h1>', rendered)
        self.assertIn('class="archive-nav-group study-nav-group"', rendered)
        self.assertIn(
            'class="archive-nav-label" href="/studies" aria-current="page"',
            rendered,
        )


if __name__ == "__main__":
    unittest.main()

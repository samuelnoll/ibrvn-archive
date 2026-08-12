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
    "download_link": None,
    "youtube_link": None,
    "wordpress_link": None,
    "transcript_available": 0,
}

SAMPLE_STUDY = {
    "study_id": "study-sample",
    "study_type": "ctb",
    "study_type_label": "Centro de Treinamento Biblico",
    "title": "Historia da Igreja",
    "study_date_display": "09/08/2026",
    "resource_count": 3,
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

        for destination in ("/books", "/series", "/preachers", "/years"):
            self.assertIn(f'href="{destination}"', rendered)

    def test_home_presents_recent_sermons_and_studies_without_search(self):
        request = SimpleNamespace(url=SimpleNamespace(path="/"))
        rendered = templates.env.get_template("home.html").render(
            request=request,
            sermons=[SAMPLE_SERMON],
            studies=[SAMPLE_STUDY],
            stats={"sermons": 1, "preachers": 1, "series": 1},
            study_stats={"studies": 1, "resources": 1},
            last_update="agora",
        )

        self.assertNotIn('id="search"', rendered)
        self.assertIn('class="home-library-grid"', rendered)
        self.assertIn('class="home-library-heading" href="/sermons"', rendered)
        self.assertIn('class="home-library-heading" href="/studies"', rendered)
        self.assertIn("Pregacao de teste", rendered)
        self.assertIn("Historia da Igreja", rendered)


if __name__ == "__main__":
    unittest.main()

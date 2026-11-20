from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, text

from api.analytics import record_events
from api.main import app, templates
from shared.db import ensure_schema
from shared.study_db import ensure_study_schema


class AnalyticsTest(unittest.TestCase):
    def test_analytics_route_is_hidden_and_noindexed(self):
        self.assertIn("/analytics", {route.path for route in app.routes})
        self.assertIn("/api/analytics/events", {route.path for route in app.routes})
        request = SimpleNamespace(url=SimpleNamespace(path="/analytics"))
        rendered = templates.env.get_template("analytics.html").render(
            request=request,
            enabled=True,
            start_date="2026-10-01",
            end_date="2026-10-22",
            content_type="",
            retention_days=180,
            kpis={
                "page_views": 0, "visitors": 0, "new_visitors": 0,
                "returning_visitors": 0, "plays": 0, "unique_plays": 0,
                "listening_hours": 0, "completions": 0,
                "completion_rate": 0, "downloads": 0,
                "bytes_display": "0 B", "youtube_clicks": 0,
                "site_clicks": 0, "transcript_clicks": 0,
            },
            series={"day": [], "week": [], "month": []},
            top_pages=[],
            top_content=[],
            top_downloads=[],
            preachers=[],
            series_ranking=[],
            books=[],
            speeds=[],
            last_update="",
        )
        self.assertIn('<meta name="robots" content="noindex, nofollow">', rendered)
        self.assertNotIn('href="/analytics"', rendered)
        self.assertIn("Estatísticas de acesso", rendered)

    def test_event_storage_hashes_visitor_and_session_ids(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        with engine.begin() as conn:
            ensure_schema(conn)
            ensure_study_schema(conn)

        payload = {
            "visitor_id": "visitor-private-value",
            "session_id": "session-private-value",
            "events": [{
                "event_id": "event-1",
                "event_type": "audio_play",
                "content_type": "sermon",
                "content_id": "sermon-1",
                "duration_seconds": 1800,
                "playback_rate": 1.25,
                "page_path": "/sermons",
            }],
        }
        with patch("api.analytics.get_engine", return_value=engine), patch(
            "api.analytics.asset_details", return_value=None,
        ):
            accepted = record_events(payload)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM analytics_events")).mappings().one()
            visitor = conn.execute(text("SELECT * FROM analytics_visitors")).mappings().one()

        self.assertEqual(1, accepted)
        self.assertNotIn("visitor-private-value", row["visitor_id_hash"])
        self.assertNotIn("session-private-value", row["session_id_hash"])
        self.assertEqual(row["visitor_id_hash"], visitor["visitor_id_hash"])
        self.assertEqual("sermon-1", row["content_id"])


if __name__ == "__main__":
    unittest.main()

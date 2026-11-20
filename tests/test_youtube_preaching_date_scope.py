from __future__ import annotations

import os
import json
import unittest
from unittest.mock import MagicMock, mock_open, patch


os.environ.setdefault("YOUTUBE_API_KEY", "test-key")

from pipe.pipelines.bronze import youtube_source_to_bronze
from pipe.pipelines.silver import youtube_bronze_to_silver


class YoutubePreachingDateScopeTest(unittest.TestCase):
    @patch.object(youtube_source_to_bronze, "get_all_playlists", return_value=[])
    @patch.object(youtube_source_to_bronze, "enrich_video_details", return_value={})
    @patch.object(youtube_source_to_bronze, "fetch_playlist_items")
    @patch.object(
        youtube_source_to_bronze,
        "fetch_playlist_items_for_date",
        return_value=[],
    )
    @patch.object(
        youtube_source_to_bronze,
        "get_upload_playlist",
        return_value="uploads",
    )
    @patch.object(youtube_source_to_bronze, "load_channel", return_value="channel")
    @patch("builtins.open", new_callable=mock_open)
    def test_preaching_date_uses_five_day_margin_instead_of_loopback(
        self,
        _open,
        _load_channel,
        _get_upload_playlist,
        fetch_for_date,
        fetch_all,
        _enrich_video_details,
        _get_all_playlists,
    ):
        youtube_source_to_bronze.run(
            "weekly",
            loopback_days=5,
            preaching_date=" 2026-10-18 ",
        )

        fetch_for_date.assert_called_once_with(
            "uploads",
            youtube_source_to_bronze.date(2026, 10, 18),
            margin_days=5,
        )
        fetch_all.assert_not_called()

    @patch.object(youtube_source_to_bronze, "enrich_video_details")
    @patch.object(youtube_source_to_bronze, "youtube_api_get")
    def test_window_checks_both_dates_and_continues_after_older_items(self, api, enrich):
        def item(video_id, published_at):
            return {"snippet": {
                "resourceId": {"videoId": video_id}, "title": video_id,
                "description": "", "publishedAt": published_at,
            }}

        api.side_effect = [
            {"items": [item("old", "2026-01-01T12:00:00Z")], "nextPageToken": "page2"},
            {"items": [
                item("iASEWJ-PNSA", "2026-11-16T03:19:08Z"),
                item("live-only", "2026-12-01T12:00:00Z"),
                item("start-boundary", "2026-11-10T03:00:00Z"),
                item("end-boundary", "2026-11-21T02:59:59Z"),
                item("before", "2026-11-10T02:59:59Z"),
                item("after", "2026-11-21T03:00:00Z"),
            ]},
        ]
        enrich.return_value = {
            "iASEWJ-PNSA": {"live_start_time": "2026-11-15T13:44:09Z"},
            "live-only": {"live_start_time": "2026-11-15T13:00:00Z"},
        }

        videos = youtube_source_to_bronze.fetch_playlist_items_for_date(
            "uploads", "2026-11-15", margin_days=5,
        )

        self.assertEqual(
            {"iASEWJ-PNSA", "live-only", "start-boundary", "end-boundary"},
            {video["video_id"] for video in videos},
        )
        self.assertEqual("page2", api.call_args_list[1].args[1]["pageToken"])
        self.assertEqual(7, len(enrich.call_args.args[0]))

    @patch.object(youtube_source_to_bronze, "youtube_api_get")
    def test_enrichment_uses_video_publication_instead_of_playlist_addition(self, api):
        api.return_value = {"items": [{
            "id": "sermon", "snippet": {"publishedAt": "2026-11-16T03:19:08Z"},
            "liveStreamingDetails": {"actualStartTime": "2026-11-15T13:44:09Z"},
        }]}
        details = youtube_source_to_bronze.enrich_video_details(["sermon"])
        self.assertEqual("2026-11-16T03:19:08Z", details["sermon"]["published_at"])
        self.assertEqual("2026-11-15T13:44:09Z", details["sermon"]["live_start_time"])

    @patch.object(youtube_bronze_to_silver, "finish_processing_run")
    @patch.object(youtube_bronze_to_silver, "begin_processing_run", return_value="run")
    @patch.object(youtube_bronze_to_silver, "ensure_schema")
    @patch.object(youtube_bronze_to_silver, "get_engine")
    def test_silver_persists_only_requested_sermon_date(self, engine, _schema, _begin, _finish):
        videos = [
            {"video_id": "iASEWJ-PNSA", "description": "Culto Dominical - 15/11/2026",
             "published_at": "2026-11-16T03:19:08Z", "live_start_time": "2026-11-15T13:44:09Z"},
            {"video_id": "previous", "description": "Culto - 08/11/2026",
             "published_at": "2026-11-10T12:00:00Z"},
            {"video_id": "next", "description": "Culto - 22/11/2026",
             "published_at": "2026-11-20T12:00:00Z"},
            {"video_id": "live-date", "description": "",
             "published_at": "2026-11-18T12:00:00Z", "live_start_time": "2026-11-15T14:00:00Z"},
        ]
        for video in videos:
            video.update(title="Pregacao | 1 Tessalonicenses 5:19-22 | Valdir Noll", duration="PT42M18S")
        conn = MagicMock()
        engine.return_value.begin.return_value.__enter__.return_value = conn
        with patch("builtins.open", mock_open(read_data=json.dumps(videos))):
            youtube_bronze_to_silver.run("weekly", preaching_date="2026-11-15")
        batches = [call.args[1] for call in conn.execute.call_args_list if len(call.args) == 2]
        # Source provenance is retained for all candidates; sermon/media writes
        # contain only the selected sermon for the requested business date.
        self.assertEqual(4, len(batches[0]))
        self.assertEqual(["2026-11-15"], [row["preaching_date"] for row in batches[1]])
        self.assertEqual(["2026-11-15"], [row["canonical_sermon_id"] for row in batches[2]])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import unittest
from unittest.mock import mock_open, patch


os.environ.setdefault("YOUTUBE_API_KEY", "test-key")

from pipe.pipelines.bronze import youtube_source_to_bronze


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
    def test_preaching_date_uses_exact_local_date_fetch(
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
        )
        fetch_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from pipe.pipelines.silver.youtube_bronze_to_silver import (
    choose_best_sermon_candidate,
)


SERMON_TITLE = "O tesouro e a pérola | Mateus 13:44-46 | Saulo Amaral"


class YoutubeSermonCandidateSelectionTest(unittest.TestCase):
    def test_best_candidate_prefers_positive_duration_over_zero_duration(self):
        zero_duration_candidate = {
            "video": {
                "video_id": "zero",
                "title": SERMON_TITLE,
                "published_at": "2026-08-16T13:11:16Z",
                "duration_seconds": 0,
                "duration_iso": "P0D",
            },
            "metadata": {},
            "media": {},
        }
        full_duration_candidate = {
            "video": {
                "video_id": "full",
                "title": SERMON_TITLE,
                "published_at": "2026-08-16T12:30:00Z",
                "duration_seconds": 3120,
                "duration_iso": "PT52M",
            },
            "metadata": {},
            "media": {},
        }

        selected = choose_best_sermon_candidate([
            zero_duration_candidate,
            full_duration_candidate,
        ])

        self.assertEqual("full", selected["video"]["video_id"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipe.pipelines.audio import download_audio_assets


class AudioDownloadErrorsTest(unittest.TestCase):
    def run_failed_download(self, ignore_download_error: bool):
        engine = MagicMock()
        connection = engine.begin.return_value.__enter__.return_value
        row = {
            "canonical_sermon_id": "sermon-1",
            "preaching_date": "2026-10-18",
            "audio_source_url": "",
            "youtube_source_url": "https://youtube.com/watch?v=video-1",
            "audio_mime_type": "",
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            download_audio_assets,
            "AUDIO_RAW_DIR",
            Path(temp_dir),
        ), patch.object(
            download_audio_assets,
            "begin_processing_run",
            return_value="run-1",
        ), patch.object(
            download_audio_assets,
            "fetch_all",
            return_value=[row],
        ), patch.object(
            download_audio_assets,
            "download_youtube_audio",
            side_effect=RuntimeError("download failed"),
        ), patch.object(
            download_audio_assets,
            "get_engine",
            return_value=engine,
        ), patch.object(
            download_audio_assets,
            "ensure_schema",
        ), patch.object(
            download_audio_assets,
            "finish_processing_run",
        ) as finish_processing_run:
            if ignore_download_error:
                download_audio_assets.run(ignore_download_error=True)
            else:
                with self.assertRaisesRegex(
                    download_audio_assets.AudioDownloadError,
                    "sermon-1",
                ):
                    download_audio_assets.run()

        return connection, finish_processing_run

    def test_download_failure_fails_processing_run_by_default(self):
        connection, finish_processing_run = self.run_failed_download(False)

        connection.execute.assert_not_called()
        finish_processing_run.assert_called_once_with("run-1", "failed")

    def test_download_failure_can_be_ignored(self):
        connection, finish_processing_run = self.run_failed_download(True)

        connection.execute.assert_not_called()
        finish_processing_run.assert_called_once_with("run-1", "success")

    def test_download_must_create_a_non_empty_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "audio.mp3"

            with self.assertRaises(FileNotFoundError):
                download_audio_assets.ensure_downloaded_file(target_path)

            target_path.touch()

            with self.assertRaises(FileNotFoundError):
                download_audio_assets.ensure_downloaded_file(target_path)

            target_path.write_bytes(b"audio")
            download_audio_assets.ensure_downloaded_file(target_path)


if __name__ == "__main__":
    unittest.main()

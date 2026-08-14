from __future__ import annotations

import unittest

from pipe.pipelines.silver.wordpress_historic_bronze_to_silver import (
    choose_preacher,
    is_placeholder_sermon_content,
)
from pipe.pipelines.gold.silver_to_gold_refresh import (
    build_download_link,
    choose_first_non_empty,
)


class WordpressSermonPipelineTest(unittest.TestCase):
    def test_placeholder_sermon_content_is_detected(self):
        self.assertTrue(
            is_placeholder_sermon_content(
                "<strong>Ouça: Pregação 15/09/13 - Livro C:V-V por Nome Sobrenome</strong>"
                '[audio src="http://www.ibrvn.com.br/audio/2013/pregador_DD_MM_AA.mp3"]'
            )
        )

    def test_choose_preacher_normalizes_aliases_and_accents(self):
        self.assertEqual(
            "Jaercio Chagas",
            choose_preacher("", "Jaércio Chagas"),
        )
        self.assertEqual(
            "Jaercio Chagas",
            choose_preacher("", "Jaércio João das Chagas"),
        )

    def test_build_download_link_uses_existing_local_path(self):
        self.assertEqual(
            "/media/2013_09_15.mp3",
            build_download_link({
                "local_path": r"D:\Desenvolvimento\homelab\ibrvn-archive\data\audio\raw\2013_09_15.mp3",
            }),
        )
        self.assertEqual("", build_download_link({}))

    def test_gold_prefers_real_metadata_over_placeholder_wordpress_row(self):
        rows = [
            {
                "source_system": "wordpress",
                "source_item_id": "https://ibrvn.com.br/?p=2808",
                "preacher_name": "Nome Sobrenome",
                "text_reference": "Lucas 3:1-20",
                "title": "",
                "serie": "Série Lucas",
                "processed_at": "2026-08-12T00:00:00+00:00",
            },
            {
                "source_system": "wordpress",
                "source_item_id": "https://ibrvn.com.br/2013/09/15/pregacao-150913-lucas-31-20/",
                "preacher_name": "Fabiano Lima",
                "text_reference": "Lucas 3:1-20",
                "title": "",
                "serie": "Série Lucas",
                "processed_at": "2026-08-12T00:00:00+00:00",
            },
        ]

        self.assertEqual("Fabiano Lima", choose_first_non_empty(rows, "preacher_name"))


if __name__ == "__main__":
    unittest.main()

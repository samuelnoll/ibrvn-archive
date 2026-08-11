from __future__ import annotations

import tempfile
import unittest
import ast
import sqlite3
from collections import Counter
from pathlib import Path

from pipe.pipelines.studies.youtube_rules import (
    infer_study_type,
    is_study_playlist,
)
from pipe.pipelines.studies.wordpress_parser import parse_public_studies


ITEM_TEMPLATE = """
<item>
  <title>{title}</title>
  <link>{link}</link>
  <content:encoded><![CDATA[{content}]]></content:encoded>
  <wp:post_id>{post_id}</wp:post_id>
  <wp:post_date>{post_date}</wp:post_date>
  <wp:post_name>{slug}</wp:post_name>
  <wp:status>{status}</wp:status>
  <wp:post_parent>{parent}</wp:post_parent>
  <wp:post_type>{post_type}</wp:post_type>
  <wp:attachment_url>{attachment_url}</wp:attachment_url>
  <wp:post_mime_type>{mime_type}</wp:post_mime_type>
</item>
"""


def item(
    post_id: int,
    title: str,
    slug: str,
    content: str = "",
    *,
    parent: int = 0,
    status: str = "publish",
    post_type: str = "page",
    post_date: str = "2024-02-03 12:00:00",
) -> str:
    return ITEM_TEMPLATE.format(
        title=title,
        link=f"https://ibrvn.com.br/{slug}/",
        content=content,
        post_id=post_id,
        post_date=post_date,
        slug=slug,
        status=status,
        parent=parent,
        post_type=post_type,
        attachment_url="",
        mime_type="",
    )


def build_export() -> str:
    items = [
        item(
            9,
            "CTB",
            "ctb",
            '<a href="/?page_id=10">CTB 2020</a>'
            '<a href="/?page_id=11">Draft</a>',
        ),
        item(
            10,
            "Doctrine | CTB 2020",
            "ctb-doctrine",
            '<a href="https://ibrvn.com.br/files/class.mp3">Audio</a>'
            '<a href="https://ibrvn.com.br/files/guide.pdf">Guide</a>'
            '<a href="https://ibrvn.com.br/files/guide.pdf">Guide duplicate</a>',
            parent=9,
        ),
        item(11, "Draft", "draft", parent=9, status="draft"),
        item(
            1298,
            "Talks",
            "palestras-conferencias",
            '<a href="/?page_id=20">Conference</a>',
        ),
        item(
            20,
            "Conference",
            "conference",
            '<iframe src="https://youtu.be/abc123"></iframe>',
            parent=1298,
        ),
        item(7, "Weekly", "estudos-semanais"),
        item(
            5091,
            "Study Materials",
            "materiais-de-estudo",
            '<a href="/?page_id=30">Weekly</a>'
            '<a href="https://ibrvn.com.br/wp-content/uploads/2022/05/'
            'PFD-Estudo1-Authority.pdf">Authority</a>',
        ),
        item(
            30,
            "Weekly Study",
            "weekly-study",
            '<a href="https://ibrvn.com.br/files/notes.docx">Notes</a>'
            '<a href="https://example.org/reference">Reference</a>',
            parent=7,
        ),
        item(
            40,
            "Unlinked published page",
            "unlinked-page",
            '<a href="https://ibrvn.com.br/files/hidden.pdf">Hidden</a>',
        ),
    ]
    return """<?xml version="1.0" encoding="UTF-8" ?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:wp="http://wordpress.org/export/1.2/">
<channel>
{items}
</channel>
</rss>
""".format(items="\n".join(items))


class PublicWordpressStudyParserTest(unittest.TestCase):
    def test_youtube_playlist_rules_use_only_estudo_prefix(self):
        self.assertTrue(is_study_playlist("Estudo Romanos"))
        self.assertTrue(is_study_playlist("ESTUDO CTB 2026"))
        self.assertFalse(is_study_playlist("Estudos Semanais"))
        self.assertFalse(is_study_playlist("Serie Estudo Romanos"))
        self.assertEqual("weekly", infer_study_type(["Estudo Romanos"]))
        self.assertEqual("ctb", infer_study_type(["Estudo CTB 2026"]))
        self.assertEqual("pfd", infer_study_type(["Estudo PFD"]))
        self.assertEqual(
            "lecture_or_conference",
            infer_study_type(["Estudo Conferencia da Reforma"]),
        )

    def test_independent_study_schema_is_valid_sqlite(self):
        schema_path = Path("shared/study_db.py")
        module = ast.parse(schema_path.read_text(encoding="utf-8"))
        create_statements = [
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.startswith("CREATE_")
        ]
        expected_tables = {
            "silver_study_processing_runs",
            "silver_study_wordpress",
            "silver_study_wordpress_resources",
            "silver_study_youtube",
            "silver_study_youtube_resources",
            "gold_studies",
            "gold_study_resources",
        }

        with sqlite3.connect(":memory:") as connection:
            for statement in create_statements:
                connection.execute(statement)

            actual_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        self.assertTrue(expected_tables.issubset(actual_tables))

    def test_only_published_pages_reachable_from_public_roots_are_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            xml_path = Path(directory) / "export.xml"
            xml_path.write_text(build_export(), encoding="utf-8")
            studies = parse_public_studies(xml_path)

        self.assertEqual(4, len(studies))
        self.assertEqual({
            "ctb": 1,
            "lecture_or_conference": 1,
            "pfd": 1,
            "weekly": 1,
        }, Counter(study.study_type for study in studies))
        self.assertNotIn("wordpress:11", {study.study_key for study in studies})
        self.assertNotIn("wordpress:40", {study.study_key for study in studies})

    def test_resources_are_classified_and_deduplicated_per_study(self):
        with tempfile.TemporaryDirectory() as directory:
            xml_path = Path(directory) / "export.xml"
            xml_path.write_text(build_export(), encoding="utf-8")
            studies = parse_public_studies(xml_path)

        resources = {
            study.study_key: Counter(
                resource.resource_type
                for resource in study.resources
            )
            for study in studies
        }
        self.assertEqual(Counter({"audio": 1, "pdf": 1}), resources["wordpress:10"])
        self.assertEqual(Counter({"youtube": 1}), resources["wordpress:20"])
        self.assertEqual(
            Counter({"word": 1, "external_link": 1}),
            resources["wordpress:30"],
        )
        self.assertEqual(Counter({"pdf": 1}), resources["wordpress:pfd:1"])


if __name__ == "__main__":
    unittest.main()

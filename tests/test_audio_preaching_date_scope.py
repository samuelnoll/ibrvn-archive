from __future__ import annotations

import unittest

from pipe.pipelines.audio.common import build_preaching_date_scope


class AudioPreachingDateScopeTest(unittest.TestCase):
    def test_exact_preaching_date_takes_precedence_over_loopback(self):
        scope_sql, params = build_preaching_date_scope(
            "sm",
            loopback_days=5,
            preaching_date="2026-10-18",
        )

        self.assertEqual(
            "AND sm.preaching_date = :preaching_date",
            scope_sql,
        )
        self.assertEqual({"preaching_date": "2026-10-18"}, params)

    def test_invalid_preaching_date_is_rejected(self):
        with self.assertRaises(ValueError):
            build_preaching_date_scope(
                "sm",
                preaching_date="18/10/2026",
            )


if __name__ == "__main__":
    unittest.main()

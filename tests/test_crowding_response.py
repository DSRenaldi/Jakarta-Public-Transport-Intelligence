# -*- coding: utf-8 -*-
"""Regresi bahasa pengguna dan peringkasan waktu crowding."""
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pipelines"), str(ROOT / "api")]

import crowding  # noqa: E402
from chatbot import chat  # noqa: E402


def _daily_tool_out() -> dict:
    return {
        "tool": "crowding",
        "result": {
            "estimates": [],
            "daily": [{
                "available": True,
                "scope": {"name": "MRT"},
                "day_type": "weekend",
                "ranges": {
                    "padat": [],
                    "sedang": ["06:00-09:00", "16:00-19:00"],
                    "longgar": [
                        "00:00-06:00", "09:00-16:00", "19:00-23:59",
                    ],
                },
            }],
            "headways": {},
            "rag": {},
        },
    }


class CrowdingRangeTests(unittest.TestCase):
    def test_end_of_day_span_keeps_original_start(self):
        times = [f"{hour:02d}:{minute:02d}"
                 for hour in range(19, 24)
                 for minute in (0, 30)]
        self.assertEqual(crowding._time_spans(times), ["19:00-23:59"])


class CrowdingReplyTests(unittest.TestCase):
    def test_fallback_uses_public_language_and_time_format(self):
        reply = chat.fallback_reply("crowding", {}, _daily_tool_out())
        lowered = reply.lower()
        for internal in ("crowding-v1", "weekend", "weekday", "proksi"):
            self.assertNotIn(internal, lowered)
        self.assertIn("akhir pekan", lowered)
        self.assertIn("19.00–23.59", reply)
        self.assertIn("bukan pengukuran kepadatan langsung", lowered)

    def test_polisher_normalizes_technical_terms_and_malformed_times(self):
        raw = (
            "Berdasarkan model crowding-v1 (label proksi, weekend), "
            "pilih 09 30 atau 19:30."
        )
        reply = chat._polish_reply(raw, "crowding", {}, _daily_tool_out())
        lowered = reply.lower()
        for internal in ("crowding-v1", "weekend", "proksi"):
            self.assertNotIn(internal, lowered)
        self.assertIn("akhir pekan", lowered)
        self.assertIn("09.30", reply)
        self.assertIn("19.30", reply)


if __name__ == "__main__":
    unittest.main()

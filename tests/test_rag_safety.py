# -*- coding: utf-8 -*-
"""Regresi pagar keamanan RAG dan integrasinya dengan chatbot."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pipelines"), str(ROOT / "api")]

import rag_query  # noqa: E402
from chatbot import chat  # noqa: E402


class RagScopeTests(unittest.TestCase):
    def test_lrt_systems_have_distinct_operator_scope(self):
        jakarta = rag_query.infer_query_filters("fasilitas LRT Jakarta")
        jabodebek = rag_query.infer_query_filters("fasilitas LRT Jabodebek")
        self.assertEqual(jakarta["operator"], "LRT_JAKARTA")
        self.assertEqual(jabodebek["operator"], "LRT_JABODEBEK")

    def test_service_document_types_are_inferred_conservatively(self):
        self.assertEqual(
            rag_query.infer_query_filters(
                "kebijakan barang bawaan MRT Jakarta")["doc_type"],
            "policy",
        )
        self.assertEqual(
            rag_query.infer_query_filters(
                "laporan tahunan KAI Commuter 2025")["doc_type"],
            "annual_report",
        )

    def test_kci_alias_maps_to_krl_operator(self):
        filters = rag_query.infer_query_filters(
            "apa isi laporan tahunan KCI 2025")
        self.assertEqual(filters["operator"], "KRL_COMMUTER")
        self.assertEqual(filters["mode"], "KRL")

    def test_weak_candidate_is_rejected(self):
        self.assertFalse(rag_query._candidate_is_relevant(
            vector_score=0.31, coverage=0.0, lexical_hit=False,
            relevance=0.22, year_ok=True,
        ))


class RagChatIntegrationTests(unittest.TestCase):
    def test_rag_cache_key_changes_with_data_version(self):
        keys = []

        def capture(_namespace, key, _ttl, _fn, _cacheable):
            keys.append(key)
            return {"available": False, "results": []}

        with patch.object(chat, "_tool_cached", side_effect=capture):
            chat._rag_cached("laporan KRL", 4, "data-v1")
            chat._rag_cached("laporan KRL", 4, "data-v2")
        self.assertNotEqual(keys[0], keys[1])

    def test_station_ranking_does_not_fall_back_to_rag(self):
        out = chat.run_tool("station_ranking", {}, "stasiun tersibuk", None,
                            [], "test-version")
        self.assertEqual(out["tool"], "unsupported")
        self.assertFalse(out["result"]["available"])

    def test_crowding_does_not_call_rag(self):
        daily = {"available": True, "ranges": {}, "scope": {"name": "MRT"}}
        with patch.object(chat.tools, "crowding_daily", return_value=daily), \
                patch.object(chat.tools, "tool_schedule",
                             return_value={"available": False}), \
                patch.object(chat.tools, "rag") as rag_mock:
            out = chat.run_tool("crowding", {"mode": "MRT"},
                                "kapan mrt longgar test-rag-v2", None, [],
                                "test-rag-v2")
        self.assertNotIn("rag", out["result"])
        rag_mock.assert_not_called()

    def test_invalid_or_missing_rag_citations_are_rejected(self):
        tool_out = {"tool": "rag", "result": {
            "available": True, "results": [{}, {}],
        }}
        self.assertFalse(chat._rag_citations_valid("Jawaban tanpa sumber.",
                                                  tool_out))
        self.assertFalse(chat._rag_citations_valid("Klaim [3].", tool_out))
        self.assertTrue(chat._rag_citations_valid("Klaim [1].", tool_out))


if __name__ == "__main__":
    unittest.main()

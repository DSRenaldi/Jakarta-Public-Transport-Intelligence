# -*- coding: utf-8 -*-
"""Regresi itinerary deterministik dan provenance jawaban rute."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pipelines"), str(ROOT / "api")]

from routing import Edge, Network, RouteResult, Stop  # noqa: E402
from chatbot import chat, tools  # noqa: E402


def _fixture_route() -> tuple[Network, RouteResult]:
    net = Network()
    for stop_id, mode, name in (
        ("KRL_tambun", "KRL", "Tambun"),
        ("KRL_bni", "KRL", "BNI City"),
        ("TJ_sudirman", "BRT", "St. Sudirman 2"),
        ("MRT_dukuh", "MRT", "Dukuh Atas"),
        ("MRT_senayan", "MRT", "Senayan"),
    ):
        net.add_stop(Stop(stop_id, mode, name, -6.2, 106.8))
    net.stops["MRT_dukuh"].display_name = "Dukuh Atas BNI"
    net.stops["MRT_senayan"].display_name = "Senayan Mastercard"
    net.line_name = {
        "KRL_C": "KRL Lin Cikarang",
        "MRT_NS": "MRT Line 1",
    }
    net.line_display = dict(net.line_name)
    net.line_source = {"KRL_C": "SRC-KRL", "MRT_NS": "SRC-MRT"}
    net.source_meta = {
        "SRC-KRL": {"title": "Jaringan KRL", "url": "https://krl.test"},
        "SRC-MRT": {"title": "Jaringan MRT", "url": "https://mrt.test"},
        "SRC-KRL-FARE": {"title": "Tarif KRL", "url": "https://fare.test"},
        "SRC-MRT-FARE": {"title": "Tarif MRT", "url": "https://fare.test"},
    }
    net.mode_fare_source = {
        "KRL": {"source_id": "SRC-KRL-FARE"},
        "MRT": {"source_id": "SRC-MRT-FARE"},
    }
    segments = [
        {"type": "ride", "mode": "KRL", "line": "KRL_C",
         "route": "KRL_C_out", "from": "KRL_tambun", "to": "KRL_bni",
         "travel_sec": 3600, "wait_sec": 300, "fare": 3000,
         "time_method": "distance_speed_dwell_proxy",
         "source_id": "SRC-KRL"},
        {"type": "transfer", "from": "KRL_bni", "to": "TJ_sudirman",
         "walk_sec": 180, "time_method": "transfer_table_walk",
         "source_id": None},
        {"type": "transfer", "from": "TJ_sudirman", "to": "MRT_dukuh",
         "walk_sec": 90, "time_method": "geometry_walk_proxy",
         "source_id": None},
        {"type": "ride", "mode": "MRT", "line": "MRT_NS",
         "route": "MRT_NS_in", "from": "MRT_dukuh", "to": "MRT_senayan",
         "travel_sec": 600, "wait_sec": 150, "fare": 3000,
         "time_method": "distance_speed_dwell_proxy",
         "source_id": "SRC-MRT"},
    ]
    return net, RouteResult(True, 4920, 6000, 3, segments)


def _fixture_priok_network() -> Network:
    net = Network()
    for stop_id, mode, name in (
        ("KRL_tambun", "KRL", "Tambun"),
        ("KRL_priuk", "KRL", "Tanjung Priuk"),
        ("BRT_gkj", "BRT", "GKJ Tj. Priok"),
        ("BRT_pln", "BRT", "PLN Tj. Priok"),
        ("BRT_priok", "BRT", "Tanjung Priok"),
        ("BRT_kel", "BRT", "Kel. Tj. Priok"),
    ):
        net.add_stop(Stop(stop_id, mode, name, -6.1, 106.8))
    net.line_name = {"KRL_TEST": "KRL Lin Tanjung Priuk"}
    net.line_display = dict(net.line_name)
    net.add_edge("KRL_tambun", None, Edge(
        to_stop="KRL_priuk", to_mode="KRL", travel_sec=3600,
        wait_sec=300, fare=3000, mode="KRL", line_id="KRL_TEST",
        route_id="KRL_TEST_out", time_method="distance_speed_dwell_proxy",
    ))
    net.add_edge("KRL_priuk", "KRL", Edge(
        to_stop="BRT_priok", to_mode="BRT", travel_sec=120,
        wait_sec=0, fare=0, mode=None, is_transfer=True,
        time_method="geometry_walk_proxy",
    ))
    return net


class RouteGroundingTests(unittest.TestCase):
    def setUp(self):
        net, result = _fixture_route()
        self.payload = tools.serialize_route_result(
            net, result, "tercepat", "KRL_tambun", "MRT_senayan")
        self.tool_out = {"tool": "route", "result": self.payload}

    def test_itinerary_is_continuous_and_transfer_metrics_are_public(self):
        itinerary = self.payload["itinerary"]
        self.assertEqual(len(itinerary), 3)
        for before, after in zip(itinerary, itinerary[1:]):
            self.assertEqual(before["to"]["stop_id"],
                             after["from"]["stop_id"])
        self.assertEqual(itinerary[1]["type"], "walk")
        self.assertEqual([stop["name"] for stop in itinerary[1]["via"]],
                         ["St. Sudirman 2"])
        metrics = self.payload["route_metrics"]
        self.assertEqual(self.payload["transfers"], 1)
        self.assertEqual(metrics["service_change_count"], 1)
        self.assertEqual(metrics["mode_change_count"], 1)
        self.assertEqual(metrics["routing_transfer_score"], 3)

    def test_route_has_external_and_methodology_provenance(self):
        source_ids = {source["source_id"] for source in self.payload["sources"]}
        self.assertTrue({"SRC-KRL", "SRC-MRT", "SRC-KRL-FARE",
                         "SRC-MRT-FARE", "JPTI-ROUTING"} <= source_ids)
        self.assertTrue(all(leg["source_refs"]
                            for leg in self.payload["itinerary"]))

    def test_deterministic_reply_is_complete_and_user_facing(self):
        reply = chat.fallback_reply("route_planning", {}, self.tool_out)
        self.assertNotIn("tanpa sumber terverifikasi", reply.casefold())
        self.assertNotRegex(reply.casefold(), r"\b\d+\s*detik\b")
        self.assertNotRegex(reply, r"\[\d+\]")
        self.assertIn("estimasi tarif minimum Rp 6.000", reply)
        for name in ("Tambun", "BNI City", "Dukuh Atas BNI",
                     "Senayan Mastercard"):
            self.assertIn(name, reply)
        self.assertIn("St. Sudirman 2", reply)
        self.assertTrue(chat._route_reply_valid(reply, self.tool_out))
        self.assertEqual(chat._collect_sources(self.tool_out), [])

    def test_route_reply_with_visible_reference_is_rejected(self):
        reply = chat.fallback_reply("route_planning", {}, self.tool_out)
        self.assertFalse(chat._route_reply_valid(reply + " [1]", self.tool_out))

    def test_route_llm_context_hides_reference_details(self):
        context = chat._build_context(self.tool_out)
        self.assertNotIn('"sources"', context)
        self.assertNotIn('"source_refs"', context)
        self.assertIn('"provenance_available": true', context)

    def test_incomplete_or_unverified_llm_reply_is_rejected(self):
        bad = ("Tambun ke Senayan sekitar 4920 detik. Data ini berasal dari "
               "hasil pencarian rute tanpa sumber terverifikasi.")
        self.assertFalse(chat._route_reply_valid(bad, self.tool_out))

    def test_route_cache_key_is_versioned(self):
        keys = []

        def capture(_namespace, key, _ttl, _fn, _cacheable):
            keys.append(key)
            return self.payload

        with patch.object(chat, "_tool_cached", side_effect=capture):
            chat.run_tool(
                "route_planning",
                {"origin": "Tambun", "dest": "Senayan",
                 "preference": "tercepat"},
                "dari Tambun ke Senayan", None, [], "data-v1",
            )
        self.assertTrue(keys[0].startswith("route-v2|data-v1|"))

    def test_priok_spelling_includes_krl_and_cross_mode_exact_is_ambiguous(self):
        net = _fixture_priok_network()
        result = tools.plan_route(net, "Tambun", "Tanjung Priok")
        self.assertEqual(result["status"], "ambiguous")
        modes = {candidate["mode"]
                 for candidate in result["candidates"]["dest"]}
        self.assertEqual(modes, {"KRL", "BRT"})

    def test_pending_route_does_not_hijack_a_new_question(self):
        net = _fixture_priok_network()
        result = tools.plan_route(net, "Tambun", "Priok")
        pending = chat._new_pending_route(
            {"origin": "Tambun", "dest": "Priok"}, result)
        action = chat._continue_pending_route("berapa tarif MRT?", pending)
        self.assertEqual(action["kind"], "new_request")

    def test_multiturn_candidate_selection_keeps_origin_and_original_number(self):
        net = _fixture_priok_network()
        sid = "route-context-test"
        chat.STORE.reset(sid)
        try:
            with patch.object(chat.intents, "classify",
                              return_value=("route_planning", 1.0)), \
                    patch.object(chat.llm, "configured", return_value=False):
                first = chat.handle_chat(
                    "saya dari Tambun ingin ke Priok, saya harus naik apa",
                    sid, net, [], "route-context-v1",
                )
                pending = chat.STORE.pending_route(sid)
                brt = next(candidate for candidate in
                           pending["candidates"]["dest"]
                           if candidate["stop_id"] == "BRT_priok")
                original_number = brt["choice_number"]
                second = chat.handle_chat(
                    "Tanjung Priok", sid, net, [], "route-context-v1",
                )
                third = chat.handle_chat(
                    str(original_number), sid, net, [], "route-context-v1",
                )
                fourth = chat.handle_chat(
                    "berapa lama?", sid, net, [], "route-context-v1",
                )

            self.assertEqual(first["intent"], "route_planning")
            self.assertIn("stasiun KRL", first["reply"])
            self.assertIn("halte TransJakarta", first["reply"])
            self.assertIn(f"{original_number}. Tanjung Priok", second["reply"])
            self.assertEqual(third["slots"]["origin_id"], "KRL_tambun")
            self.assertEqual(third["slots"]["dest_id"], "BRT_priok")
            self.assertIn("Langkah perjalanan:", third["reply"])
            self.assertEqual(fourth["slots"]["origin_id"], "KRL_tambun")
            self.assertEqual(fourth["slots"]["dest_id"], "BRT_priok")
            self.assertEqual(fourth["cache_status"], "miss")
            self.assertIsNone(chat.STORE.pending_route(sid))
        finally:
            chat.STORE.reset(sid)


if __name__ == "__main__":
    unittest.main()

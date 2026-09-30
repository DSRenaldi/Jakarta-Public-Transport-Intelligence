# -*- coding: utf-8 -*-
"""
CLI pencarian rute JPTI (Fase 2 MVP).

Contoh:
  python pipelines/route_query.py "Lebak Bulus" "Jakarta Kota"
  python pipelines/route_query.py "Bundaran HI" "Tangerang" --prefer termurah
  python pipelines/route_query.py "Pulomas" "Manggarai" --top 5
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402
from netload import load_network  # noqa: E402
from routing import Network, RouteResult  # noqa: E402


def norm(name: str) -> str:
    name = name.lower()
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"[().]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def match_stops(net: Network, query: str, top: int = 5,
                mode: str | None = None) -> list[tuple[str, int]]:
    """Kembalikan [(stop_id, skor)] terbaik. Skor: 100 eksak, 80 prefix, 60 substring.

    `mode` (opsional) membatasi kandidat ke satu moda — penting utk nama
    stasiun yang sama di banyak moda (mis. "Dukuh Atas": BRT/MRT/LRT).
    """
    q = norm(query)
    scored = []
    for sid, s in net.stops.items():
        if mode is not None and s.mode != mode:
            continue
        n = norm(s.name)
        if n == q:
            score = 100
        elif n.startswith(q):
            score = 80
        elif q in n:
            score = 60
        else:
            # token overlap
            qt, nt = set(q.split()), set(n.split())
            if qt and len(qt & nt) == len(qt):
                score = 40
            else:
                continue
        scored.append((score, len(n), sid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen, out = set(), []
    for score, _, sid in scored:
        n = norm(net.stops[sid].name)
        if n in seen:
            continue
        seen.add(n)
        out.append((sid, score))
        if len(out) >= top:
            break
    return out


def print_result(net: Network, res: RouteResult, origin_name: str, dest_name: str,
                 pref: str):
    if not res.found:
        print(f"\nGAGAL: {res.message}")
        sys.exit(1)
    print(f"\n=== Rute {origin_name} -> {dest_name}  (preferensi: {pref}) ===")
    fare_modes = set()
    for seg in res.segments:
        if seg["type"] == "transfer":
            a, b = net.stops[seg["from"]], net.stops[seg["to"]]
            print(f"  [Jalan kaki] {a.name} -> {b.name}  "
                  f"({Network.fmt_time(seg['walk_sec'])})")
        else:
            line = net.line_name.get(seg["line"], seg["line"] or "?")
            a, b = net.stops[seg["from"]], net.stops[seg["to"]]
            fare_tag = ""
            if seg["fare"] > 0 and seg["mode"] not in fare_modes:
                fare_tag = f"  tarif Rp{seg['fare']:,}"
                fare_modes.add(seg["mode"])
            print(f"  [{seg['mode']}] {line}: {a.name} -> {b.name}  "
                  f"(perjalanan {Network.fmt_time(seg['travel_sec'])}, "
                  f"tunggu ±{Network.fmt_time(seg['wait_sec'])}{fare_tag})")
    print(f"\nTOTAL: waktu ±{Network.fmt_time(res.time_sec)}, "
          f"transfer {res.transfers}x, tarif ±Rp{res.fare:,}")
    print("Catatan: waktu rail = PROKSI (jarak/kecepatan rata2 + dwell); "
          "BRT dari jadwal GTFS. Tarif = flat minimum per moda. "
          "Tanpa gangguan layanan (Fase 2 MVP).")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Pencarian rute JPTI")
    ap.add_argument("origin")
    ap.add_argument("dest")
    ap.add_argument("--prefer", default="tercepat",
                    choices=["tercepat", "termurah", "min_transfers", "longgar"])
    ap.add_argument("--top", type=int, default=5, help="tampilkan N kandidat nama")
    ap.add_argument("--origin-mode", choices=["MRT", "KRL", "LRT", "BRT"],
                    help="paksakan moda utk resolusi origin")
    ap.add_argument("--dest-mode", choices=["MRT", "KRL", "LRT", "BRT"],
                    help="paksakan moda utk resolusi dest")
    args = ap.parse_args()

    t0 = time.time()
    conn = connect()
    net = load_network(conn)
    conn.close()
    print(f"[info] jaringan dimuat dalam {time.time()-t0:.1f} detik", file=sys.stderr)

    o_cand = match_stops(net, args.origin, args.top, mode=args.origin_mode)
    d_cand = match_stops(net, args.dest, args.top, mode=args.dest_mode)
    if not o_cand or not d_cand:
        if not o_cand:
            print(f"Origin tidak ditemukan: '{args.origin}'")
        if not d_cand:
            print(f"Destinasi tidak ditemukan: '{args.dest}'")
        sys.exit(2)
    for tag, cand, q in (("origin", o_cand, args.origin),
                         ("dest", d_cand, args.dest)):
        if len(cand) > 1:
            print(f"[{tag}] kandidat untuk '{q}':", file=sys.stderr)
            for sid, score in cand:
                s = net.stops[sid]
                print(f"   {score:>3}  {s.stop_id:<28} {s.name}  [{s.mode}]",
                      file=sys.stderr)
    origin, dest = o_cand[0][0], d_cand[0][0]
    res = net.route(origin, dest, args.prefer)
    print_result(net, res, net.stops[origin].name, net.stops[dest].name, args.prefer)


if __name__ == "__main__":
    main()

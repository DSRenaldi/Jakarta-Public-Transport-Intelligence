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
    # Ejaan kawasan dan nama stasiun berbeda: penggunaan umum/BRT memakai
    # "Priok", sedangkan nama resmi stasiun KRL adalah "Tanjung Priuk".
    # Samakan hanya untuk pencarian; nama resmi yang ditampilkan tidak diubah.
    name = re.sub(r"\bpriok\b", "priuk", name)
    return re.sub(r"\s+", " ", name).strip()


def match_stops(net: Network, query: str, top: int = 5,
                mode: str | None = None) -> list[tuple[str, int]]:
    """Kembalikan [(stop_id, skor)] terbaik. Skor: 100 eksak, 80 prefix, 60 substring.

    `mode` (opsional) membatasi kandidat ke satu moda — penting utk nama
    stasiun yang sama di banyak moda (mis. "Dukuh Atas": BRT/MRT/LRT).

    Pencocokan dilakukan terhadap `canonical_name`, `display_name` (nama
    hak penamaan, mis. "Senayan Mastercard" = "Senayan"), dan `aliases`
    (nama lama/populer dari stop_name_history, mis. "Sisingamangaraja" =
    ASEAN Headquarter). Alias diberi skor satu tingkat di bawah nama resmi
    agar nama resmi selalu menang bila keduanya cocok. Dedup per (moda,
    nama) — stasiun bernama sama di moda berbeda tetap tampil sebagai
    kandidat terpisah.
    """
    q = norm(query)

    def _score(n: str) -> int:
        if n == q:
            return 100
        if n.startswith(q):
            return 80
        if q in n:
            return 60
        qt, nt = set(q.split()), set(n.split())
        if qt and len(qt & nt) == len(qt):
            return 40
        return 0

    scored = []
    for sid, s in net.stops.items():
        if mode is not None and s.mode != mode:
            continue
        names = {norm(s.name)}
        if s.display_name:
            names.add(norm(s.display_name))
        best = max((_score(n) for n in names if n), default=0)
        if best < 90:
            # alias: eksak=90, prefix=70, substring=50, token=30
            best = max(best, max((_score(a) - 10 for a in
                                  (norm(x) for x in s.aliases) if a),
                                 default=0))
        if best:
            scored.append((best, len(norm(s.name)), sid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen, out = set(), []
    for score, _, sid in scored:
        s = net.stops[sid]
        key = (s.mode, norm(s.name))
        if key in seen:
            continue
        seen.add(key)
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

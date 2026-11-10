# -*- coding: utf-8 -*-
"""
Validasi Fase 2: serangkaian query rute (unimoda + multimoda).

Setiap kasus: (label, origin, dest, preferensi, ekspektasi minimum).
Hasil dicetak; gagal total = exit 1 (untuk CI sederhana).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402
from netload import load_network  # noqa: E402
from route_query import match_stops  # noqa: E402

CASES = [
    # (label, origin, moda_origin, dest, moda_dest, preferensi)
    # moda=None -> resolusi nama bebas (untuk nama yang unik)
    ("BRT koridor", "Blok M", "BRT", "Kampung Melayu", "BRT", "tercepat"),
    ("BRT utara-selatan", "Kota", "BRT", "Pulo Gadung", "BRT", "tercepat"),
    ("MRT Line 1 penuh", "Lebak Bulus", "MRT", "Bundaran HI", "MRT", "tercepat"),
    ("MRT Line 1 bagian", "Blok M", "MRT", "Dukuh Atas", "MRT", "tercepat"),
    ("LRTJ penuh", "Kelapa Gading", "LRT", "Manggarai", "LRT", "tercepat"),
    ("LRTB ke Cibubur", "Dukuh Atas", "LRT", "Harjamukti", "LRT", "tercepat"),
    ("LRTB ke Bekasi", "Dukuh Atas", "LRT", "Jatimulya", "LRT", "tercepat"),
    ("KRL Bogor penuh", "Bogor", "KRL", "Jakarta Kota", "KRL", "tercepat"),
    ("KRL Bogor-Nambo", "Bogor", "KRL", "Nambo", "KRL", "tercepat"),
    ("KRL Cikarang", "Cikarang", "KRL", "Kampung Bandan", "KRL", "tercepat"),
    ("KRL Tangerang", "Tangerang", "KRL", "Duri", "KRL", "tercepat"),
    ("KRL Rangkasbitung", "Rangkasbitung", "KRL", "Tanah Abang", "KRL", "tercepat"),
    ("Multi: MRT->KRL", "Bundaran HI", "MRT", "Bogor", "KRL", "tercepat"),
    ("Multi: KRL->LRTB", "Jakarta Kota", "KRL", "Jatimulya", "LRT", "tercepat"),
    ("Multi: KRL->BRT", "Bogor", "KRL", "Pulo Gadung", "BRT", "tercepat"),
    ("Multi: BRT->MRT", "Lebak Bulus", "BRT", "Dukuh Atas", "MRT", "termurah"),
    ("Multi: min transfer", "Bogor", "KRL", "Tangerang", "KRL", "min_transfers"),
]

# Pasangan ini sengaja tersebar di beberapa sistem dan koridor. Setiap kasus
# harus dapat dirutekan pada kedua arah; tidak ada pengecualian OD di engine.
BIDIRECTIONAL_RAIL_CASES = [
    ("MRT dua arah", "Lebak Bulus", "Bundaran HI", "MRT"),
    ("LRT Jakarta dua arah", "Kelapa Gading", "Manggarai", "LRT"),
    ("LRT Jabodebek Cibubur", "Dukuh Atas", "Harjamukti", "LRT"),
    ("LRT Jabodebek Bekasi", "Dukuh Atas", "Jatimulya", "LRT"),
    ("KRL Tangerang dua arah", "Duri", "Tangerang", "KRL"),
    ("KRL Rangkas dua arah", "Tanah Abang", "Rangkasbitung", "KRL"),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    conn = connect()
    t0 = time.time()
    net = load_network(conn)
    conn.close()
    print(f"\njaringan: {len(net.stops)} stops, "
          f"{time.time()-t0:.1f}s load\n", file=sys.stderr)

    n_ok = 0
    for label, oq, om, dq, dm, pref in CASES:
        oc = match_stops(net, oq, 1, mode=om)
        dc = match_stops(net, dq, 1, mode=dm)
        if not oc or not dc:
            print(f"[SKIP ] {label}: origin/dest tidak ditemukan "
                  f"({oq!r}/{om} / {dq!r}/{dm})")
            continue
        res = net.route(oc[0][0], dc[0][0], pref)
        if not res.found:
            print(f"[FAIL ] {label}: {res.message}")
            continue
        modes = []
        for seg in res.segments:
            if seg["type"] == "ride" and seg["mode"] not in modes:
                modes.append(seg["mode"])
        n_ok += 1
        print(f"[ OK ] {label:<22} {oq} -> {dq} | {pref:<13} | "
              f"±{net.fmt_time(res.time_sec):>8} | {res.transfers}x transfer | "
              f"Rp{res.fare:>6,} | moda: {'+'.join(modes)}")

    for label, aq, bq, mode in BIDIRECTIONAL_RAIL_CASES:
        ac = match_stops(net, aq, 1, mode=mode)
        bc = match_stops(net, bq, 1, mode=mode)
        if not ac or not bc:
            print(f"[FAIL ] {label}: titik tidak ditemukan ({aq}/{bq})")
            continue
        forward = net.route(ac[0][0], bc[0][0], "min_transfers")
        reverse = net.route(bc[0][0], ac[0][0], "min_transfers")
        if forward.found and reverse.found:
            n_ok += 1
            print(f"[ OK ] {label:<22} {aq} <-> {bq}")
        else:
            print(f"[FAIL ] {label}: forward={forward.found}, "
                  f"reverse={reverse.found}")
    # Regresi arah barat full-racket Cikarang: tanpa reverse proxy yang benar,
    # Sudirman -> Duri memutar lewat Manggarai/Pasar Senen/Kampung Bandan.
    west_o = match_stops(net, "Sudirman", 1, mode="KRL")
    west_d = match_stops(net, "Duri", 1, mode="KRL")
    west = (net.route(west_o[0][0], west_d[0][0], "tercepat")
            if west_o and west_d else None)
    west_names = []
    if west and west.found:
        west_names = [net.stops[west.segments[0]["from"]].name]
        west_names.extend(net.stops[seg["to"]].name
                          for seg in west.segments if seg["type"] == "ride")
    expected_west = ["Sudirman", "BNI City", "Tanah Abang", "Duri"]
    if west_names == expected_west:
        n_ok += 1
        print("[ OK ] KRL Cikarang barat    Sudirman -> Duri | "
              "Sudirman > BNI City > Tanah Abang > Duri")
    else:
        print(f"[FAIL ] KRL Cikarang barat: urutan={west_names}")

    total = len(CASES) + len(BIDIRECTIONAL_RAIL_CASES) + 1
    print(f"\n{n_ok}/{total} kasus menghasilkan rute yang diharapkan")


if __name__ == "__main__":
    main()

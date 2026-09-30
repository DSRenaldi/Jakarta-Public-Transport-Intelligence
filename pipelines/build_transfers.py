# -*- coding: utf-8 -*-
"""
Bangun tabel `transfers` untuk hub antarmoda (rail <-> BRT).

Strategi: tiap stop rail (MRT/LRT/KRL), cari stop non-rail terdekat
< 600 m; buat row transfer dengan walking_time_sec = ceil(jarak/1.3 m/s).
Hasil dicetak utk review; row lama dihapus dulu (idempoten).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

MAX_M = 600.0
WALK_MPS = 1.3


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.stop_id_internal, a.canonical_name, a.mode_id,
               b.stop_id_internal, b.canonical_name, b.mode_id,
               b.d AS m
        FROM stops a
        JOIN LATERAL (
            SELECT stop_id_internal, canonical_name, mode_id,
                   ST_Distance(a.geometry::geography, geometry::geography) AS d
            FROM stops
            WHERE stop_id_internal <> a.stop_id_internal
              AND mode_id <> a.mode_id
              AND geometry IS NOT NULL
              AND ST_Distance(a.geometry::geography, geometry::geography) <= %s
            ORDER BY d
            LIMIT 1
        ) b ON true
        WHERE a.mode_id IN ('MRT','LRT','KRL')
          AND a.geometry IS NOT NULL
        ORDER BY a.stop_id_internal
    """, (MAX_M,))
    rows = cur.fetchall()
    print(f"pasang kandidat hub antarmoda: {len(rows)}\n")

    # hapus transfer auto lama (type intermodal + notes mulai 'auto:'),
    # pertahankan row kurasi manual bila ada
    cur.execute("DELETE FROM transfers WHERE type='intermodal' AND notes LIKE 'auto:%'")
    n = 0
    best_per_pair: dict[tuple, tuple] = {}  # (a_id, b_mode) -> (m, row)
    for r in rows:
        a_id, a_mode, b_mode = r[0], r[2], r[5]
        key = (a_id, b_mode)
        if key not in best_per_pair or r[6] < best_per_pair[key][0]:
            best_per_pair[key] = (float(r[6]), r)
    for (a_id, b_mode), (m, r) in best_per_pair.items():
        a_id_, a_name, a_mode_, b_id, b_name, _b_mode, _m = r
        w = max(60, int(math.ceil(m / WALK_MPS)))
        cur.execute("""
            INSERT INTO transfers(from_stop_id, to_stop_id, walking_time_sec,
                type, notes)
            VALUES (%s,%s,%s,'intermodal',%s)
            ON CONFLICT (from_stop_id, to_stop_id) DO UPDATE SET
                walking_time_sec=EXCLUDED.walking_time_sec
        """, (a_id_, b_id, w, f"auto: {a_name} <-> {b_name} ({m:.0f} m)"))
        n += 1
        print(f"  {a_id_:<16} [{a_mode_}] <-> {b_id:<16} [{b_mode}]  {m:6.0f} m  ~{w // 60} mnt")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM transfers")
    total = cur.fetchone()[0]
    conn.close()
    print(f"\nselesai: {n} baris baru, total transfers = {total}")


if __name__ == "__main__":
    main()

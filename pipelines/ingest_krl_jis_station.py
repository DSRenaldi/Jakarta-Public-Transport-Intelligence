# -*- coding: utf-8 -*-
"""JPTI — KRL: tambah stasiun JIS ke Lin Tanjung Priok + rute inbound.

Konteks (1 Okt 2026):
- Gap A1 ("JIS tidak ada di OSM — koordinat tak traceable") TERSELESAI:
  node OSM 5726702622 (lat -6.1228211, lon 106.8613596) sudah ada sejak
  2018-06-28 (nama lama "Sungai Tirem"; versi terakhir 2026-06-27), tag
  lengkap (railway=station, name="Jakarta International Stadium",
  abbr_name=JIS, railway:ref=JIS, wikidata=Q135684142). Terverifikasi
  silang 4 sumber (akses 2026-10-01):
    * OSM API: https://www.openstreetmap.org/api/0.6/node/5726702622
    * Wikidata stasiun Q135684142 (-6.123017, 106.860396; ~109 m)
    * Wikidata stadion  Q6124453      (-6.124444, 106.860278; ~217 m)
    * track way 164113396 (member relasi 17193008): jarak node->track = 2 m
- Relasi 17193008 BELUM memasukkan JIS (last update 2024-08-26) —
  ini INGEST MANUAL berbasis node terverifikasi, sementara menunggu
  sinkronisasi relasi OSM; bila relasi ter-update, ingest otomatis
  (fetch_osm_nodes) akan menangkap stasiun ini secara natural.
- TEMUAN TAMBAHAN: rute inbound HILANG pada 2 line KRL (Lin Tanjung
  Priok & Lin Rangkasbitung) — edge netload satu arah, sehingga arah
  balik tidak bisa di-rute. Inbound = urutan outbound dibalik
  (keduanya line point-to-point).
- valid_from stasiun dibiarkan NULL: tanggal mulai layanan JIS belum
  terverifikasi dari sumber (jangan menebak).

Idempoten: ON CONFLICT utk stop/alias; rute inbound hanya dibuat bila
belum ada; route_stops ditulis ulang (delete + insert) per rute yang
terpengaruh.
Jalankan: .venv\\Scripts\\python pipelines\\ingest_krl_jis_station.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipelines"))
from db import connect  # noqa: E402
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

JIS_ID = "KRL_jakarta_international_stadium"
JIS_LAT, JIS_LON = -6.1228211, 106.8613596
JIS_OSM_NODE = 5726702622
SRC = "SRC-COM-01"

# urutan stop (stop_id_internal) per rute SETELAH perbaikan
TANPRIK_OUT = ["KRL_jakarta_kota", "KRL_kampung_bandan", "KRL_ancol",
               JIS_ID, "KRL_tanjung_priuk"]
TANPRIK_IN = list(reversed(TANPRIK_OUT))

# line yang rutenya diperbaiki: (line_id, route_id_out, route_id_in,
#                                 pattern_in, sequence_in)
# sequence_in utk Rangkasbitung diisi dinamis (balikan urutan outbound).
LINES = [
    ("KRL_TANJUNGPRIOK_LINE", "KRL_TANJUNGPRIOK_LINE_out",
     "KRL_TANJUNGPRIOK_LINE_in", "Tanjung Priuk – Jakarta Kota",
     TANPRIK_IN),
    ("KRL_RANGKASBITUNG_LINE", "KRL_RANGKASBITUNG_LINE_out",
     "KRL_RANGKASBITUNG_LINE_in", None, None),
]


def _rewrite_route_stops(cur, route_id: str, seqs: list[str]) -> int:
    cur.execute("DELETE FROM route_stops WHERE route_id = %s", (route_id,))
    n = 0
    for i, sid in enumerate(seqs, start=1):
        cur.execute("""INSERT INTO route_stops
                       (route_id, stop_id_internal, seq)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (route_id, seq) DO UPDATE
                       SET stop_id_internal = EXCLUDED.stop_id_internal""",
                    (route_id, sid, i))
        n += 1
    return n


def main() -> None:
    conn = connect()
    conn.row_factory = dict_row
    cur = conn.cursor()

    # ---------- stop JIS ----------
    cur.execute("""INSERT INTO stops
                   (stop_id_internal, operator_id, mode_id, canonical_name,
                    display_name, geometry, osm_node_id, source_id)
                   VALUES (%s, 'KRL_COMMUTER', 'KRL',
                           'Jakarta International Stadium',
                           'Jakarta International Stadium (JIS)',
                           ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                           %s, %s)
                   ON CONFLICT (stop_id_internal) DO UPDATE
                   SET geometry = EXCLUDED.geometry,
                       osm_node_id = EXCLUDED.osm_node_id,
                       canonical_name = EXCLUDED.canonical_name""",
                (JIS_ID, JIS_LON, JIS_LAT, JIS_OSM_NODE, SRC))

    # alias utk matcher: nama lama + singkatan (stop_name_history adalah
    # saluran alias netload; nama = canonical/display dikecualikan).
    # valid_from = tanggal terverifikasi penggunaan (konvensi proyek);
    # kolom NOT NULL — alias baru memakai tanggal akses riset.
    aliases = [("Sungai Tirem", "2018-06-28"),   # old_name OSM sejak v1
               ("JIS", "2026-10-01"),
               ("Stasiun JIS", "2026-10-01")]
    for name, vf in aliases:
        cur.execute("""INSERT INTO stop_name_history
                       (stop_id_internal, name, valid_from, source_id)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (stop_id_internal, name, valid_from)
                       DO NOTHING""", (JIS_ID, name, vf, SRC))

    # ---------- rute & urutan ----------
    for line_id, rid_out, rid_in, pattern_in, seqs_in in LINES:
        cur.execute("""SELECT r.route_id FROM routes r
                       WHERE r.route_id = %s""", (rid_out,))
        assert cur.fetchone(), f"rute outbound {rid_out} tidak ada"
        cur.execute("""SELECT l.osm_relation_id
                       FROM lines l WHERE l.line_id = %s""", (line_id,))
        rel = cur.fetchone()["osm_relation_id"]
        if isinstance(rel, list):          # lines: array; routes: bigint
            rel = rel[0] if rel else None

        if seqs_in is None:
            # Rangkasbitung: balikan urutan outbound yang ada
            cur.execute("""SELECT stop_id_internal FROM route_stops
                           WHERE route_id = %s ORDER BY seq""", (rid_out,))
            seqs_in = [r["stop_id_internal"] for r in cur.fetchall()]
            pattern_in = None

        # inbound dibuat bila belum ada
        cur.execute("""SELECT pattern_name FROM routes
                       WHERE route_id = %s""", (rid_in,))
        row = cur.fetchone()
        if not row:
            if pattern_in is None:
                # turunkan dari pola outbound "A – B" -> "B – A"
                cur.execute("""SELECT pattern_name FROM routes
                               WHERE route_id = %s""", (rid_out,))
                p = cur.fetchone()["pattern_name"]
                parts = [x.strip() for x in p.split("–")]
                pattern_in = " – ".join(reversed(parts)) if len(parts) == 2 \
                    else p
            cur.execute("""INSERT INTO routes
                           (route_id, line_id, pattern_name, direction,
                            osm_relation_id, source_id)
                           VALUES (%s, %s, %s, 'inbound', %s, %s)""",
                        (rid_in, line_id, pattern_in, rel, SRC))
            print(f"[rute] inbound baru: {rid_in} ({pattern_in})")

        # tulis ulang urutan (JIS masuk utk Tanpri)
        cur.execute("""SELECT stop_id_internal FROM route_stops
                       WHERE route_id = %s ORDER BY seq""", (rid_out,))
        seqs_out = [r["stop_id_internal"] for r in cur.fetchall()]
        n1 = _rewrite_route_stops(cur, rid_out, seqs_out)
        n2 = _rewrite_route_stops(cur, rid_in, seqs_in)
        print(f"[urutan] {rid_out}: {n1} stop; {rid_in}: {n2} stop")

    conn.commit()
    conn.close()
    print(f"[selesai] stop {JIS_ID} (+alias {len(aliases)}), inbound "
          "Lin Tanpri & Lin Rangkasbitung, JIS disisipkan di antara "
          "Ancol dan Tanjung Priuk (kedua arah)")


if __name__ == "__main__":
    main()

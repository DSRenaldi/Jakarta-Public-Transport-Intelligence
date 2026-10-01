# -*- coding: utf-8 -*-
"""JPTI — MRT Jakarta: koreksi min/max + matriks tarif antarstasiun 13x13.

Koreksi data (1 Okt 2026) — hasil riset (akses 2026-10-01):
- Baris lama (fare_type min/max, SRC-MRT-03) menyimpan max Rp5.000
  per 2023-05 — SALAH. Matriks resmi operator = Rp3.000-14.000,
  berlaku sejak 1 April 2019 (Pergub DKI Jakarta No. 34 Tahun 2019);
  tidak ada penyesuaian tarif reguler 2025-2026 (hanya promo
  insidental, mis. Kepgub Dishub DKI 102/2026 Rp1 s.d. 28/6/2026).
- Sumber matriks (verbatim, snapshot arsip halaman tarif resmi operator):
  http://web.archive.org/web/20260614131457/https://landingpage-dev.jakartamrt.co.id/id/tarif-mrt-jakarta
  (snapshot 2026-06-14; URL live kini 404 — situs SPA baru tak punya
  halaman tarif; copy verbatim tersimpan .work/tarif/
  page_tarif_archived_20260614_matriks.txt)
- Korob: Wikipedia id (matriks identik "per 1 April 2019", sitasi
  Kompas 27/3/2019); detik 24/2/2025; dasar hukum terkonfirmasi 2
  sumber (rilis pers resmi LRT Jakarta + CNBC Indonesia 18/11/2025).
  CATATAN: teks penuh Pergub 34/2019 belum dibaca langsung (JDIH 404)
  — nomor terkonfirmasi, isi disimpulkan dari matriks resmi + media.
- Matriks TIDAK simetris di beberapa sel (mis. Istora->Bendungan Hilir
  4.000 vs sebaliknya 3.000) -> simpan 156 baris TERARAH; transkripsi
  persis dari sumber, tanpa "perbaikan".

Idempoten: perbaiki baris min/max (fare_id 77/78), hapus + (re)insert
baris fare_type='matrix' mode MRT.
Jalankan: .venv\\Scripts\\python pipelines\\ingest_mrt_fares_matrix.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipelines"))
from db import connect  # noqa: E402
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

# Urutan stasiun Line 1 selatan->utara (M01-M13, kode per SRC-MRT-08)
ORDER = ["MRT_NS_01", "MRT_NS_02", "MRT_NS_03", "MRT_NS_04", "MRT_NS_05",
         "MRT_NS_06", "MRT_NS_07", "MRT_NS_08", "MRT_NS_09", "MRT_NS_10",
         "MRT_NS_11", "MRT_NS_12", "MRT_NS_13"]
NAMES = ["Lebak Bulus", "Fatmawati", "Cipete Raya", "Haji Nawi", "Blok A",
         "Blok M", "ASEAN", "Senayan", "Istora", "Bendungan Hilir",
         "Setiabudi", "Dukuh Atas", "Bundaran HI"]

# Baris i = stasiun asal ORDER[i]; kolom j = tujuan ORDER[j]; 0 = diagonal
# Transkripsi VERBATIM snapshot resmi 2026-06-14 (lihat docstring).
MATRIX = [
    [0,     4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 13000, 14000, 14000],
    [4000,  0,    4000, 5000, 6000, 7000, 7000, 9000,  9000,  10000, 11000, 12000, 13000],
    [5000,  4000, 0,    3000, 4000, 5000, 6000, 7000,  8000,  9000,  9000,  10000, 11000],
    [6000,  5000, 3000, 0,    3000, 4000, 5000, 6000,  7000,  8000,  8000,  9000,  10000],
    [7000,  6000, 4000, 3000, 0,    3000, 4000, 5000,  6000,  7000,  7000,  8000,  9000],
    [8000,  7000, 5000, 4000, 3000, 0,    3000, 4000,  5000,  6000,  6000,  7000,  8000],
    [9000,  7000, 6000, 5000, 4000, 3000, 0,    3000,  4000,  5000,  6000,  7000,  7000],
    [10000, 9000, 7000, 6000, 5000, 4000, 3000, 0,    3000,  4000,  4000,  5000,  6000],
    [11000, 9000, 8000, 7000, 6000, 5000, 4000, 3000, 0,    4000,  4000,  5000,  6000],
    [12000, 10000, 9000, 8000, 7000, 6000, 5000, 4000, 3000, 0,    3000,  3000,  4000],
    [13000, 11000, 9000, 8000, 7000, 6000, 6000, 4000, 3000, 3000, 0,    3000,  4000],
    [14000, 12000, 10000, 9000, 8000, 7000, 7000, 5000, 4000, 3000, 3000, 0,    3000],
    [14000, 13000, 11000, 10000, 9000, 8000, 7000, 6000, 5000, 4000, 4000, 3000, 0],
]

VALID_FROM = "2019-04-01"
LEGAL = ("Pergub DKI Jakarta No. 34 Tahun 2019 (tarif MRT & LRT); "
         "berlaku 1 April 2019; tidak diubah s.d. 2026-10-01 "
         "(teks penuh belum dibaca — nomor terkonfirmasi 2 sumber)")
SRC_MATRIX = "SRC-MRT-03"
SRC_LEGAL = "SRC-MRT-11"


def _validate() -> None:
    assert len(MATRIX) == 13 and all(len(r) == 13 for r in MATRIX), \
        "matriks bukan 13x13"
    vals = []
    for i, row in enumerate(MATRIX):
        assert row[i] == 0, f"diagonal bukan 0 di baris {i}"
        for j, v in enumerate(row):
            if i != j:
                assert v in range(3000, 15000, 1000), \
                    f"nilai tak wajar {v} di ({i},{j})"
                vals.append(v)
    assert min(vals) == 3000 and max(vals) == 14000
    assert len(vals) == 156
    # cek spot transkripsi vs sumber (sela asimetris khas)
    assert MATRIX[8][9] == 4000, "Istora->Bendungan Hilir harus 4000"
    assert MATRIX[9][8] == 3000, "Bendungan Hilir->Istora harus 3000"
    assert MATRIX[0][12] == 14000, "Lebak Bulus->Bundaran HI harus 14000"
    assert MATRIX[0][1] == 4000, "Lebak Bulus->Fatmawati harus 4000"
    print(f"[validasi] matriks 13x13 OK — min {min(vals)}, max {max(vals)}, "
          f"156 sel terarah")


def main() -> None:
    _validate()
    conn = connect()
    conn.row_factory = dict_row
    cur = conn.cursor()

    # ---------- data_sources ----------
    cur.execute("""UPDATE data_sources
                   SET url = %s,
                       notes = %s,
                       verified_at = %s
                   WHERE source_id = %s""",
                ("http://web.archive.org/web/20260614131457/"
                 "https://landingpage-dev.jakartamrt.co.id/id/tarif-mrt-jakarta",
                 "Matriks resmi Rp3.000-14.000 (snapshot 2026-06-14); "
                 "berlaku 1 Apr 2019 (Pergub DKI 34/2019). KOREKSI 1 Okt "
                 "2026: catatan lama 'Rp3.000-5.000' SALAH; URL live 404 "
                 "(SPA) — pakai snapshot arsip. Akses 2026-10-01.",
                 "2026-10-01", SRC_MATRIX))
    cur.execute("""INSERT INTO data_sources
                   (source_id, name, url, access_method, license,
                    update_frequency, status, verified_at, notes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (source_id) DO UPDATE
                   SET name = EXCLUDED.name, url = EXCLUDED.url,
                       notes = EXCLUDED.notes,
                       verified_at = EXCLUDED.verified_at""",
                (SRC_LEGAL,
                 "Pergub DKI Jakarta No. 34/2019 (dasar hukum tarif MRT & LRT)",
                 "https://mail.lrtjakarta.co.id/tarif_dan_kesiapan_operasi_"
                 "lrt_jakarta_pers341.html",
                 "manual", "publik", "jarang", "live", "2026-10-01",
                 "Nomor terkonfirmasi 2 sumber independen (rilis pers "
                 "resmi LRT Jakarta + CNBC Indonesia 18/11/2025); teks "
                 "penuh belum dibaca (JDIH 404). Berlaku 1 Apr 2019. "
                 "Akses 2026-10-01."))

    # ---------- baris min/max (koreksi) ----------
    cur.execute("""SELECT operator_id, fare_id FROM fares
                   WHERE mode_id = 'MRT' AND fare_type = 'min'""")
    mn = cur.fetchone()
    cur.execute("""SELECT fare_id FROM fares
                   WHERE mode_id = 'MRT' AND fare_type = 'max'""")
    mx = cur.fetchone()
    assert mn and mx, "baris fares min/max MRT tidak ditemukan"
    cur.execute("""UPDATE fares SET
                       valid_from = %s, legal_basis = %s, source_id = %s,
                       notes = %s
                   WHERE fare_id = %s""",
                (VALID_FROM, LEGAL, SRC_LEGAL,
                 "Koreksi 1 Okt 2026: min Rp3.000; matriks lengkap per "
                 "pasangan = fare_type='matrix' (sumber SRC-MRT-03).",
                 mn["fare_id"]))
    cur.execute("""UPDATE fares SET price_idr = 14000,
                       valid_from = %s, legal_basis = %s, source_id = %s,
                       notes = %s
                   WHERE fare_id = %s""",
                (VALID_FROM, LEGAL, SRC_LEGAL,
                 "Koreksi 1 Okt 2026: max Rp5.000 -> Rp14.000 "
                 "(Lebak Bulus<->Bundaran HI); matriks lengkap per "
                 "pasangan = fare_type='matrix' (sumber SRC-MRT-03).",
                 mx["fare_id"]))

    # ---------- matriks terarah ----------
    cur.execute("""DELETE FROM fares
                   WHERE mode_id = 'MRT' AND fare_type = 'matrix'""")
    n_del = cur.rowcount
    pairs = 0
    for i, a in enumerate(ORDER):
        for j, b in enumerate(ORDER):
            if i == j:
                continue
            cur.execute("""INSERT INTO fares
                           (operator_id, mode_id, fare_type,
                            from_stop_id, to_stop_id, price_idr,
                            valid_from, legal_basis, source_id, notes)
                           VALUES (%s, 'MRT', 'matrix', %s, %s, %s,
                                   %s, %s, %s, %s)""",
                        (mn["operator_id"], a, b, MATRIX[i][j],
                         VALID_FROM, LEGAL, SRC_MATRIX,
                         "Matriks verbatim snapshot resmi 2026-06-14; "
                         "asimetris di beberapa sel"))
            pairs += 1
    conn.commit()
    conn.close()
    print(f"[selesai] matrix MRT: {n_del} baris lama dihapus, {pairs} "
          f"baris terarah disimpan; min/max dikoreksi "
          f"(max 5000 -> 14000, valid_from {VALID_FROM})")


if __name__ == "__main__":
    main()

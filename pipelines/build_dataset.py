# -*- coding: utf-8 -*-
"""
Standarkan data penumpang publik dari semua moda ke satu tabel panjang.

Output: data/processed/ridership_monthly.csv
Skema mengikuti docs/data-dictionary.md (ridership_daily, disadaptasi untuk
periode bulanan/kuartalan/semesteran/tahunan yang tersedia di sumber publik).

Sumber (source_id merujuk docs/source-registry.md):
- BPS 2026 bulanan: SRC-BPS-02 (MRT, LRT Jakarta, TransJakarta) — definisi tap-in BPS.
- SDI MRT (Jan 2023–Jun 2026): SRC-MRT-01 — definisi Dishub/SDI.
- KRL kci.id: SRC-KRL-01 (+ Antara SRC-SEC-05 untuk FY2025).
- LRT Jabodebek KAI: SRC-LRTB-05 (+ MetroTV SRC-SEC-07).
- LRT Jakarta tahunan: SRC-SEC (Wikipedia, ref BPK/BPS) — sekunder.
- TransJakarta tambahan: operator/BPS tahunan (sekunder), Des 2025 & Jul 2026.
"""
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

RETRIEVED_AT = "2026-09-29"

rows = []


def add(mode, operator, series, ptype, pstart, pend, count, unit="orang",
        definition="", source_id="", source_name="", provenance="primer",
        label="historis", approx=False, notes="", published=""):
    rows.append({
        "record_id": "",  # diisi setelah semua baris terkumpul
        "mode_id": mode,
        "operator_id": operator,
        "series_id": series,
        "period_type": ptype,
        "period_start": pstart,
        "period_end": pend,
        "passenger_count": int(count),
        "unit": unit,
        "definition_ref": definition,
        "source_id": source_id,
        "source_name": source_name,
        "provenance": provenance,  # primer | sekunder
        "data_label": label,       # aktual | historis | prediksi | proksi
        "is_approx": "true" if approx else "false",
        "notes": notes,
        "published_at": published,
        "retrieved_at": RETRIEVED_AT,
        "data_version": "2026-09-29",
    })


# ---------- 1. BPS 2026 bulanan (MRT, LRT Jakarta, TJ) ----------
BPS_DEF = "BPS: total penumpang yang diangkut moda massal via tap-in pintu masuk halte/stasiun keberangkatan (atau NFC)"
for mode, operator, series, fname in [
    ("MRT", "MRT_JAKARTA", "mrt_bps_tapin", "mrt_jakarta"),
    ("LRT", "LRT_JAKARTA", "lrtj_bps", "lrt_jakarta"),
    ("BRT", "TRANSJAKARTA", "tj_bps_tapin", "transjakarta"),
]:
    p = RAW / "bps" / f"{fname}_monthly_passengers.csv"
    if not p.exists():
        print(f"!! tidak ada {p}")
        continue
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["is_annual"] == "true":
                continue
            year, month = int(r["year"]), int(r["month"])
            last_day = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[month]
            add(mode, operator, series, "month",
                f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}",
                r["passenger_count"], definition=BPS_DEF,
                source_id="SRC-BPS-02", source_name="BPS DKI Jakarta — tabel statistik transportasi",
                published=r["last_update"][:10],
                notes=f"var={r['unit']}")

# ---------- 2. SDI MRT (Jan 2023 – Jun 2026) ----------
SDI_DEF = "Dishub DKI/SDI: jumlah penumpang MRT (definisi portal Satu Data Jakarta; sedikit berbeda dari tap-in BPS)"
p = RAW / "mrt" / "data_jumlah_penumpang_mrt.csv"
sdi_anomalies = {
    (2023, 1): "anomali: nilai jauh di bawah tren (cek ulang ke sumber)",
    (2023, 2): "anomali: nilai jauh di bawah tren (cek ulang ke sumber)",
    (2023, 3): "anomali: nilai jauh di bawah tren (cek ulang ke sumber)",
    (2025, 7): "dugaan duplikat: sama dengan Jun 2025 (4.419.821) — tandai perlu verifikasi",
}
with open(p, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        year = int(r["periode_data"][:4])
        month = int(r["bulan"])
        last_day = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[month]
        add("MRT", "MRT_JAKARTA", "mrt_sdi_dishub", "month",
            f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}",
            r["jumlah_penumpang"], definition=SDI_DEF,
            source_id="SRC-MRT-01", source_name="Satu Data Indonesia — Data Jumlah Penumpang MRT",
            notes=sdi_anomalies.get((year, month), ""),
            published="2026-09-03")

# ---------- 3. KRL (kci.id) ----------
KCI_DEF = "KCI: 'volume pengguna' Commuter Line Jabodetabek (orang, naik+berangkat per sistem; beda definisi BPS/Dishub)"
add("KRL", "KRL_COMMUTER", "krl_kci", "month", "2024-01-01", "2024-01-31", 26_848_194,
    definition=KCI_DEF, source_id="SRC-KRL-01", source_name="kci.id — rilis resmi KAI Commuter",
    published="2024-02")
add("KRL", "KRL_COMMUTER", "krl_kci", "custom", "2024-01-01", "2024-09-30", 241_791_750,
    definition=KCI_DEF, source_id="SRC-KRL-01", source_name="kci.id — rilis resmi KAI Commuter",
    notes="Q3 rilis: 1 Jan–30 Sep 2024, +15% YoY", published="2024-10")
add("KRL", "KRL_COMMUTER", "krl_kci", "custom", "2025-01-01", "2025-05-31", 179_154_727,
    definition=KCI_DEF, source_id="SRC-KRL-01", source_name="kci.id — rilis resmi KAI Commuter",
    notes="Jan–Mei 2025, +34,98% YoY", published="2025-06")
add("KRL", "KRL_COMMUTER", "krl_kci", "month", "2025-05-01", "2025-05-31", 29_122_224,
    definition=KCI_DEF, source_id="SRC-KRL-01", source_name="kci.id — rilis resmi KAI Commuter",
    notes="+5,46% YoY", published="2025-06")
add("KRL", "KRL_COMMUTER", "krl_kci", "year", "2025-01-01", "2025-12-31", 349_311_251,
    definition=KCI_DEF, source_id="SRC-SEC-05",
    source_name="ANTARA (kutip VP Corporate Communication KAI) — FY2025 Jabodetabek",
    provenance="sekunder", published="2026-02-08",
    notes="KAI Commuter total 400.737.915; Jabodetabek 349.311.251")
add("KRL", "KRL_COMMUTER", "krl_kci", "month", "2026-01-01", "2026-01-31", 30_226_365,
    definition=KCI_DEF, source_id="SRC-KRL-01", source_name="kci.id — rilis resmi KAI Commuter",
    notes="+8% YoY", published="2026-02")
add("KRL", "KRL_COMMUTER", "krl_kci", "quarter", "2026-01-01", "2026-03-31", 87_979_371,
    definition=KCI_DEF, source_id="SRC-KRL-01", source_name="kci.id — rilis resmi KAI Commuter",
    notes="+7% YoY (Q1 2025: 82.114.334)", published="2026-04")
add("KRL", "KRL_COMMUTER", "krl_kci", "semester", "2026-01-01", "2026-06-30", 181_612_400,
    definition=KCI_DEF, source_id="SRC-KRL-01", source_name="kci.id — rilis resmi KAI Commuter",
    notes="+7,02% YoY (S1 2025: 169.701.778)", published="2026-07-09")

# ---------- 4. LRT Jabodebek (KAI) ----------
KAI_DEF = "KAI: 'pengguna' LRT Jabodebek (orang, total sistem; beda definisi antar-sumber KAI/BPS)"
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "month", "2025-06-01", "2025-06-30", 2_310_000,
    definition=KAI_DEF, source_id="SRC-LRTB-05", source_name="lrtjabodebek.kai.id — siaran pers KAI",
    published="2025-07-03")
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "semester", "2025-01-01", "2025-06-30", 13_000_000,
    definition=KAI_DEF, source_id="SRC-LRTB-05", source_name="lrtjabodebek.kai.id — siaran pers KAI",
    approx=True, published="2025-07-07", notes='"Lebih dari 13 juta", +50% YoY — angka pembulatan')
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "month", "2026-01-01", "2026-01-31", 2_714_594,
    definition=KAI_DEF, source_id="SRC-SEC-07", source_name="MetroTVNews (kutip KAI)",
    provenance="sekunder", published="2026-04-08", notes="rincian Q1 2026 oleh Manager PR LRT Jabodebek")
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "month", "2026-02-01", "2026-02-28", 2_530_000,
    definition=KAI_DEF, source_id="SRC-SEC-07", source_name="MetroTVNews (kutip KAI)",
    provenance="sekunder", published="2026-04-08")
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "month", "2026-03-01", "2026-03-31", 2_510_352,
    definition=KAI_DEF, source_id="SRC-SEC-07", source_name="MetroTVNews (kutip KAI)",
    provenance="sekunder", published="2026-04-08")
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "quarter", "2026-01-01", "2026-03-31", 7_754_946,
    definition=KAI_DEF, source_id="SRC-SEC-07", source_name="MetroTVNews (kutip KAI)",
    provenance="sekunder", published="2026-04-08", notes="+22% YoY")
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "custom", "2026-01-01", "2026-07-31", 19_079_347,
    definition=KAI_DEF, source_id="SRC-LRTB-05", source_name="sosmed resmi KAI/@lrtjabodebek",
    published="2026-08", notes="+21% YoY")
add("LRT", "LRT_JABODEBEK", "lrtb_kai", "custom", "2026-01-01", "2026-08-31", 21_809_797,
    definition=KAI_DEF, source_id="SRC-LRTB-05", source_name="kai.id — siaran pers KAI",
    published="2026-09-22", notes="+19,05% YoY (Jan–Agu 2025: 18.320.610)")

# ---------- 5. LRT Jakarta tahunan (sekunder: Wikipedia ref BPK/BPS) ----------
WIKI_DEF = "BPS/BPK DKI (via Wikipedia): jumlah penumpang LRT Jakarta per tahun"
for year, val in [(2020, 480_690), (2021, 315_366), (2022, 685_249),
                  (2023, 1_037_162), (2024, 1_213_470), (2025, 1_313_520)]:
    add("LRT", "LRT_JAKARTA", "lrtj_annual", "year", f"{year}-01-01", f"{year}-12-31", val,
        definition=WIKI_DEF, source_id="SRC-SEC-WIKI",
        source_name="Wikipedia LRT Jakarta (ref: BPK DKI & BPS)",
        provenance="sekunder",
        notes="verifikasi silang dengan publikasi BPS saat situs pulih")

# ---------- 6. TransJakarta tambahan ----------
add("BRT", "TRANSJAKARTA", "tj_operator", "year", "2024-01-01", "2024-12-31", 371_400_000,
    definition="Operator: jumlah pelanggan TransJakarta (orang, definisi internal operator)",
    source_id="SRC-TJ-06", source_name="transjakarta.co.id — siaran pers operator",
    published="2025-01", notes="±1,02 juta/hari")
add("BRT", "TRANSJAKARTA", "tj_bps_annual", "year", "2025-01-01", "2025-12-31", 414_350_000,
    definition=BPS_DEF, source_id="SRC-TJ-06", source_name="BPS (dikutip operator/PPID)",
    provenance="sekunder", published="2026-01",
    notes="beda definisi vs operator 413 jt — simpan terpisah")
add("BRT", "TRANSJAKARTA", "tj_operator", "month", "2025-12-01", "2025-12-31", 37_463_134,
    definition=BPS_DEF, source_id="SRC-SEC-01",
    source_name="GoodStats (data Dishub) — Des 2025",
    provenance="sekunder", published="2026-01",
    notes="pengganti sementara PDF BRS Des 2025")
add("BRT", "TRANSJAKARTA", "tj_bps_tapin", "month", "2026-07-01", "2026-07-31", 40_320_000,
    definition=BPS_DEF, source_id="SRC-SEC-06",
    source_name="Viva.co.id (kutip rilis BPS 1 Sep 2026) — Jul 2026",
    provenance="sekunder", approx=True, published="2026-09-01",
    notes="+7,19% YoY; '40,32 juta' dibulatkan")
add("BRT", "TRANSJAKARTA", "tj_operator", "month", "2026-07-01", "2026-07-31", 40_320_000,
    definition=BPS_DEF, source_id="SRC-SEC-06",
    source_name="Viva.co.id (kutip rilis BPS 1 Sep 2026) — Jul 2026",
    provenance="sekunder", approx=True, published="2026-09-01",
    notes="duplikat baris untuk series operator? HAPUS jika tidak diperlukan")

# ---------- 7. MRT tahunan (resmi operator) ----------
add("MRT", "MRT_JAKARTA", "mrt_operator", "year", "2025-01-01", "2025-12-31", 46_449_629,
    definition="Operator: jumlah pelanggan MRT (orang)",
    source_id="SRC-MRT-05", source_name="PT MRT Jakarta — rilis resmi (arsip berita + media)",
    published="2026-01", notes="127.259/hari; target 2026: 50 jt (137.000/hari)")

# ---------- tulis output ----------
PROC.mkdir(parents=True, exist_ok=True)
# buang baris duplikat yang disengaja salah (item terakhir TJ) — cleanup
rows = [r for r in rows if "HAPUS jika tidak diperlukan" not in r["notes"]]
# urutkan
rows.sort(key=lambda r: (r["mode_id"], r["series_id"], r["period_start"], r["period_type"]))
# record_id = hash pendek
for i, r in enumerate(rows):
    h = hashlib.sha1(f"{r['series_id']}|{r['period_start']}|{r['passenger_count']}".encode()).hexdigest()[:12]
    r["record_id"] = f"RDS-{h}"

out = PROC / "ridership_monthly.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# ringkasan
from collections import Counter
c = Counter((r["mode_id"], r["series_id"]) for r in rows)
print(f"OK: {len(rows)} baris -> {out.relative_to(ROOT)}")
for k, v in sorted(c.items()):
    print(f"  {k[0]:4s} {k[1]:18s} {v}")

# -*- coding: utf-8 -*-
"""
Ingest jaringan rail (MRT, LRT Jakarta, LRT Jabodebek, KRL) ke Postgres.

Sumber:
- OSM (SRC-COM-01): relasi rute + node stasiun (koordinat, urutan)
- MRT datum API (SRC-MRT-04): nama resmi + hak penamaan Line 1
- LRT Jakarta /schedule (SRC-LRTJ-03): 11 stasiun resmi (2026-09-18)
- LRT Jabodebek (SRC-LRTB-02): 18 stasiun resmi (Y-shape)
- GAPEKA Feb 2026 (SRC-KRL-03): kode stasiun KRL (header per halaman)

Logika matching: nama kanonik -> node OSM (fuzzy + keanggotaan relasi +
proksimitas). Hasil matching dicatat di data_quality_results.
"""
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402
from routing import haversine_m  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
TODAY = "2026-09-29"

# =====================================================================
# KONFIGURASI JARINGAN
# =====================================================================

# Pemetaan nama stasiun (norm) -> kode stasiun KRL.
# Rekonsiliasi penuh 30/09/2026 (A3), metodologi berlapis:
#   1) KODE OTORITATIF = header kolom GAPEKA per relasi (dokumen KAI;
#      ekstrak 13 hal: Bogor, Bekasi, Rangkasbitung, Tangerang,
#      Tanjung Priok — .work/gapeka_text.txt).
#   2) Nama kode direferensikan dari comuline API (SRC-KRL-05, pihak ketiga)
#      + cross-check 20 jangkar lama (20/22 cocok; 2 koreksi di bawah).
#   3) Posisi urutan header GAPEKA disejajarkan dgn urutan stasiun OSM di DB
#      (LCS per relasi) untuk memverifikasi tiap pasangan nama-kode.
# KOREKSI vs anchor lama:
#   - "sudirman" dahulu dipetakan ke SW — SALAH. SW = SAWAH BESAR
#     (posisi GAPEKA Bogor antara Juanda-Mangga Besar; comuline SW=SAWAH BESAR).
#     Sudirman (stasiun lama, bundaran HI) = SUD (header GAPEKA Bekasi).
#   - "bni city" (OSM) = stasiun SUDIRMAN BARU = SUDB (header GAPEKA Bekasi;
#     nama resmi per naming-right BNI sejak 2018; Wikipedia/Stasiun_BNI_City).
# KONFLIK KODE (GAPEKA menang atas comuline):
#   - Grogol = GRG (comuline: GGL); Tanah Tinggi = THI (comuline: TTI).
# BELUM TERPETAKAN (disengaja NULL):
#   - "Bandara Soekarno 2" — stop orfane (tidak pada 5 lin ter-ingest);
#     kode GAPEKA utk lin bandara tak ada di ekstrak 13 hal ini.
# GAPEKA memuat 3 stasiun TIDAK ada di OSM/DB (stasiun nonaktif/tidak
# dimodelkan): Karet (KAT, lin Bekasi — nonaktif, digantikan integrasi
# dgn BNI City), Gambir (GMR, lin Bogor), Cikoya (CKY, lin Rangkasbitung).
KRL_CODE_BY_NAME = {
    "ancol": "AC",
    "angke": "AK",
    "bni city": "SUDB",
    "batu ceper": "BPR",
    "bekasi": "BKS",
    "bekasi timur": "BKST",
    "bogor": "BOO",
    "bojong indah": "BOI",
    "bojonggede": "BJD",
    "buaran": "BUA",
    "cakung": "CUK",
    "cawang": "CW",
    "cibinong": "CBN",
    "cibitung": "CIT",
    "cicayur": "CC",
    "cikarang": "CKR",
    "cikini": "CKI",
    "cilebut": "CLT",
    "cilejit": "CJT",
    "cisauk": "CSK",
    "citayam": "CTA",
    "citeras": "CTR",
    "daru": "DAR",
    "depok": "DP",
    "depok baru": "DPB",
    "duren kalibata": "DRN",
    "duri": "DU",
    "gang sentiong": "GST",
    "gondangdia": "GDD",
    "grogol": "GRG",
    "jakarta kota": "JAKK",
    "jatake": "JTK",
    "jatinegara": "JNG",
    "jayakarta": "JAY",
    "juanda": "JUA",
    "jurangmangu": "JMU",
    "kalideres": "KDS",
    "kampung bandan": "KPB",
    "kebayoran": "KBY",
    "kemayoran": "KMO",
    "klender": "KLD",
    "klender baru": "KLDB",
    "kramat": "KMT",
    "kranji": "KRI",
    "lenteng agung": "LNA",
    "maja": "MJ",
    "mangga besar": "MGB",
    "manggarai": "MRI",
    "matraman": "MTR",
    "metland telagamurni": "TLM",
    "nambo": "NMO",
    "palmerah": "PLM",
    "parungpanjang": "PRP",
    "pasar minggu": "PSM",
    "pasar minggu baru": "PSMB",
    "pasar senen": "PSE",
    "pesing": "PSG",
    "pondok cina": "POC",
    "pondok jati": "POK",
    "pondok ranji": "PDJ",
    "poris": "PI",
    "rajawali": "RJW",
    "rangkasbitung": "RK",
    "rawa buaya": "RW",
    "rawa buntu": "RU",
    "sawah besar": "SW",
    "serpong": "SRP",
    "sudimara": "SDM",
    "sudirman": "SUD",
    "taman kota": "TKO",
    "tambun": "TB",
    "tanah abang": "THB",
    "tanah tinggi": "THI",
    "tangerang": "TNG",
    "tanjung barat": "TNT",
    "tanjung priuk": "TPK",
    "tebet": "TEB",
    "tenjo": "TEJ",
    "tigaraksa": "TGS",
    "universitas indonesia": "UI",
    "universitas pancasila": "UP",
}

OPERATORS = [
    ("MRT_JAKARTA", "PT MRT Jakarta (Perseroda)", "MRT Jakarta",
     "https://www.jakartamrt.co.id/"),
    ("LRT_JAKARTA", "PT LRT Jakarta", "LRT Jakarta",
     "https://www.lrtjakarta.co.id/"),
    ("LRT_JABODEBEK", "PT LRT Jabodebek", "LRT Jabodebek",
     "https://lrtjabodebek.kai.id/"),
    ("KRL_COMMUTER", "PT KAI Commuter (KRL Jabodetabek)", "KRL Commuterline",
     "https://kci.id/"),
]

MODES = [
    ("MRT", "MRT_JAKARTA", "MRT Jakarta"),
    ("LRT", "LRT_JAKARTA", "LRT Jakarta"),
    ("LRT", "LRT_JABODEBEK", "LRT Jabodebek"),
    ("KRL", "KRL_COMMUTER", "KRL Commuter Line"),
]

# ---- MRT Line 1 (11 stasiun, SRC-MRT-04 datum API 2026-09-29) ----
MRT_NS_STOPS = [
    ("Lebak Bulus", "Lebak Bulus Bank Syariah Indonesia"),
    ("Cipete Raya", "Cipete Raya TUKU"),
    ("Haji Nawi", None),
    ("Blok A", None),
    ("Fatmawati", "Fatmawati Indomaret"),
    ("Blok M", "Blok M BCA"),
    ("Senayan", "Senayan Mastercard"),
    ("Istora Mandiri", None),
    ("Bendungan Hilir", None),
    ("Dukuh Atas", "Dukuh Atas BNI"),
    ("Bundaran HI", "Bundaran HI Bank Jakarta"),
]

# ---- LRT Jakarta (11 stasiun, SRC-LRTJ-03 /schedule 2026-09-18) ----
LRTJ_STOPS = [
    ("Kelapa Gading", None),
    ("Boulevard Utara", "Boulevard Utara Summarecon Mall"),
    ("Boulevard Selatan", None),
    ("Pulomas", None),
    ("Equestrian", None),
    ("Velodrome", None),
    ("Rawamangun", None),
    ("Pramuka", None),
    ("Matraman", None),
    ("Proklamasi", None),
    ("Manggarai", None),
]

# ---- LRT Jabodebek (18 stasiun, SRC-LRTB-02, urutan situs resmi) ----
LRTB_STOPS = [
    ("Dukuh Atas", "Dukuh Atas BNI"),
    ("Setiabudi", None),
    ("Rasuna Said", None),
    ("Kuningan", None),
    ("Pancoran", "Pancoran bank bjb"),
    ("Cikoko", None),
    ("Ciliwung", None),
    ("Cawang", None, None),
    ("TMII", None, "Taman Mini Indonesia Indah"),
    ("Kampung Rambutan", "Kp. Rambutan", "Kp. Rambutan"),
    ("Ciracas", None),
    ("Harjamukti", None),
    ("Halim", None),
    ("Jatibening Baru", None),
    ("Cikunir 1", None),
    ("Cikunir 2", None),
    ("Bekasi Barat", None),
    ("Jatimulya", None),
]

# ---- KRL ----

KRL_LINES = [
    # line_id, nama, daftar segmen: (label segmen, relasi OSM out, relasi OSM in)
    ("KRL_BOGOR_LINE", "KRL Lin Bogor", [
        ("Jakarta Kota – Bogor", 16877210, 16877212),
        ("Jakarta Kota – Nambo", 16877211, 16877213),
    ]),
    ("KRL_BEKASI_LINE", "KRL Lin Cikarang", [
        ("Cikarang – Kampung Bandan", 2922163, 15097506),
    ]),
    ("KRL_RANGKASBITUNG_LINE", "KRL Lin Rangkasbitung", [
        ("Rangkasbitung – Tanah Abang", 2922215, None),
    ]),
    ("KRL_TANGERANG_LINE", "KRL Lin Tangerang", [
        ("Tangerang – Duri", 2922235, 17193463),
    ]),
    ("KRL_TANJUNGPRIOK_LINE", "KRL Lin Tanjung Priok", [
        ("Jakarta Kota – Tanjung Priok", 17193008, None),
    ]),
]

LINE_HEADWAYS = [
    # line_id, direction, period_type, headway_min, peak_windows, notes
    ("MRT_NS", "outbound", "peak", 5, "06:00-09:00;16:00-19:00",
     "PROKSI — headway resmi belum terverifikasi"),
    ("MRT_NS", "inbound", "peak", 5, "06:00-09:00;16:00-19:00",
     "PROKSI — headway resmi belum terverifikasi"),
    ("KRL_BOGOR_LINE", "outbound", "peak", 5, "06:00-09:00;16:00-19:00",
     "Rilis KCI Jan 2026: ±5 mnt"),
    ("KRL_BOGOR_LINE", "outbound", "offpeak", 15, None, "PROKSI"),
    ("KRL_BEKASI_LINE", "outbound", "peak", 7, "06:00-09:00;16:00-19:00",
     "Rilis KCI Jan 2026: 7-9 mnt"),
    ("KRL_BEKASI_LINE", "outbound", "offpeak", 15, None, "PROKSI"),
    ("KRL_RANGKASBITUNG_LINE", "outbound", "peak", 10, "06:00-09:00;16:00-19:00",
     "Rilis KCI Jan 2026: 10-15 mnt"),
    ("KRL_RANGKASBITUNG_LINE", "outbound", "offpeak", 15, None, "Rilis KCI Jan 2026: 10-15 mnt"),
    ("KRL_TANGERANG_LINE", "outbound", "peak", 18, "06:00-09:00;16:00-19:00",
     "Rilis KCI Jan 2026: 18 mnt"),
    ("KRL_TANGERANG_LINE", "outbound", "offpeak", 18, None, "Rilis KCI Jan 2026: 18 mnt"),
    ("KRL_TANJUNGPRIOK_LINE", "outbound", "peak", 5, "06:00-09:00;16:00-19:00",
     "PROKSI — perlu verifikasi"),
    ("KRL_TANJUNGPRIOK_LINE", "outbound", "offpeak", 10, None, "PROKSI"),
    ("LRTJ_KG_MRI", "outbound", "all", 10, None, "PROKSI"),
    ("LRTJ_KG_MRI", "inbound", "all", 10, None, "PROKSI"),
    ("LRTB_CB", "outbound", "peak", 10, "06:00-09:00;16:00-20:00",
     "PROKSI; jendela puncak LRTB 06:00-08:59 & 16:00-19:59"),
    ("LRTB_BK", "outbound", "peak", 10, "06:00-09:00;16:00-20:00",
     "PROKSI; jendela puncak LRTB 06:00-08:59 & 16:00-19:59"),
]

FARES = [
    # operator, mode, fare_type, price, valid_from, basis, source, notes
    ("MRT_JAKARTA", "MRT", "min", 3000, "2023-05-01", "Tarif MRT Jakarta Rp3.000-5.000",
     "SRC-MRT-03", "Terverifikasi registry Fase 0; dasar hukum perlu konfirmasi"),
    ("MRT_JAKARTA", "MRT", "max", 5000, "2023-05-01", "Tarif MRT Jakarta Rp3.000-5.000",
     "SRC-MRT-03", ""),
    ("KRL_COMMUTER", "KRL", "min", 3000, "2020-04-01", "Tarif Commuter Line Rp3.000-20.000",
     "SRC-KRL-04", "Kepmenhub 354/2020 dkk."),
    ("KRL_COMMUTER", "KRL", "max", 20000, "2020-04-01", "Tarif Commuter Line Rp3.000-20.000",
     "SRC-KRL-04", ""),
    ("LRT_JAKARTA", "LRT", "flat", 5000, "2026-09-16", "Tarif LRT Jakarta Rp5.000",
     "SRC-LRTJ-05", "Termasuk koridor baru CG-Manggarai (resmi 16 Sep 2026)"),
    ("LRT_JABODEBEK", "LRT", "min", 5000, "2023-08-29", "Tarif LRT Jabodebek Rp5.000-20.000",
     "SRC-LRTB-03", "Matriks penuh tersedia (registry)"),
    ("LRT_JABODEBEK", "LRT", "max", 20000, "2023-08-29", "Tarif LRT Jabodebek Rp5.000-20.000",
     "SRC-LRTB-03", ""),
]

# =====================================================================
# UTIL
# =====================================================================


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def load_osm_nodes() -> dict:
    f = WORK / "osm_member_nodes.json"
    if not f.exists():
        return {}
    data = json.loads(f.read_text(encoding="utf-8"))
    return {n["id"]: n for n in data}


def load_rel(rel_id: int) -> dict | None:
    f = WORK / f"osm_rel_{rel_id}.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    for e in data.get("elements", []):
        if e["type"] == "relation":
            return e
    return None


def rel_nodes(rel: dict, nodes: dict) -> list:
    """Anggota node relasi (berurutan) dengan data tag."""
    out = []
    for m in rel.get("members", []):
        if m["type"] != "node":
            continue
        n = nodes.get(m["ref"], {})
        out.append(n)
    return out


def match_stop(canonical: str, alias: str | None, candidates: list,
               all_nodes: dict, max_dist_m: float = 350.0) -> dict | None:
    """Cocokkan nama kanonik (atau alias) ke node OSM.

    Urutan prioritas: eksak (di dalam relasi) > substring timbal-balik (relasi)
    > token overlap (relasi) > fuzzy (relasi) > proksimitas (semua node).
    Return (node, metode).
    """
    names = [x for x in (canonical, alias) if x]
    cns = [norm(x) for x in names]
    cns = [c for c in cns if c]
    if not cns:
        return None
    best = None
    for n in candidates:
        tags = n.get("tags", {})
        name = tags.get("name") or tags.get("name:en") or ""
        nn = norm(name)
        if not nn:
            continue
        for cn in cns:
            if nn == cn:
                return (n, "exact")
        score = max(norm_score(nn, cn) for cn in cns)
        if best is None or score > best[2]:
            best = (n, nn, score)
    for n in candidates:
        nn = norm(n.get("tags", {}).get("name", ""))
        if nn and any(cn in nn or nn in cn for cn in cns):
            return (n, "substring")
    ct = set(cns[0].split())
    for n in candidates:
        nn = norm(n.get("tags", {}).get("name", ""))
        if nn:
            nt = set(nn.split())
            if ct and len(ct & nt) == len(ct):
                return (n, "tokens")
    if best:
        node, nn, score = best
        if score >= 0.5:
            return (node, "fuzzy")
    # fallback: node terdekat dgn nama mengandung token panjang
    if all_nodes:
        cands = []
        for n in all_nodes.values():
            nn = norm(n.get("tags", {}).get("name", ""))
            if nn and any(t in nn for cn in cns for t in cn.split() if len(t) > 3):
                cands.append(n)
        if cands:
            ref_n = best[0] if best else None
            rl = (ref_n["lat"], ref_n["lon"]) if ref_n else (ref_lat, ref_lon)
            cands.sort(key=lambda n: haversine_m(rl[0], rl[1], n["lat"], n["lon"]))
            if haversine_m(rl[0], rl[1], cands[0]["lat"], cands[0]["lon"]) <= max_dist_m:
                return (cands[0], "proximity")
    return None


ref_lat, ref_lon = -6.2, 106.85  # pusat Jakarta (untuk fallback proximity)


def norm_score(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(s)).strip("_")


# =====================================================================
# MAIN
# =====================================================================


def main():
    t0 = time.time()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    nodes = load_osm_nodes()
    if not nodes:
        print("osm_member_nodes.json belum ada — jalankan fetch_osm_nodes.py dulu")
        sys.exit(1)
    print(f"node OSM tersedia: {len(nodes)}")

    conn = connect()
    cur = conn.cursor()
    qlog = []  # (dataset, check_type, result, details)

    # ---------- sumber data ----------
    sources = [
        ("SRC-COM-01", "OpenStreetMap (relasi rute + node stasiun)",
         "https://www.openstreetmap.org", "auto (Overpass)", "ODbL",
         "kontinu", "live", TODAY,
         f"{len(nodes)} node stasiun diambil 2026-09-29 (relasi MRT/LRT/KRL)"),
        ("SRC-MRT-04", "Jadwal & daftar stasiun MRT Jakarta (situs resmi)",
         "https://jakartamrt.co.id/jadwal-keberangkatan", "auto (API CMS)",
         "proprietary (publik)", "kontinu", "live", TODAY,
         "Situs kini SPA (Vite); data via API beweb-dev.jakartamrt.co.id/middleware/api/datum "
         "(12 entitas stasiun: 11 Line 1 + Setiabudi Astra)"),
        ("SRC-LRTJ-03", "Jadwal LRT Jakarta (situs resmi)",
         "https://www.lrtjakarta.co.id/schedule", "auto (embed JSON)",
         "proprietary (publik)", "kontinu", "live", TODAY,
         "JSON stasiun ter-embed di halaman /schedule (dibuat 2026-09-18; 11 stasiun)"),
        ("SRC-LRTB-02", "Daftar stasiun LRT Jabodebek (18)",
         "https://lrtjabodebek.kai.id/", "manual_scrape",
         "proprietary (publik)", "kontinu", "live", TODAY,
         "Y-shape: Dukuh Atas BNI - Cawang - Harjamukti / Jatimulya"),
        ("SRC-KRL-03", "GAPEKA KRL Jabodetabek (PDF)",
         "https://kci.id/ (unduh lokal)", "manual", "proprietary (publik)",
         "insidentil", "live", "2026-02-01",
         "PDF update Feb 2026 (13 hlm); kode stasiun per header tabel"),
        ("SRC-MRT-03", "Tarif antarstasiun MRT Jakarta",
         "https://jakartamrt.co.id/tarif-mrt-jakarta", "manual", "proprietary",
         "jarang", "live", TODAY, "Rp3.000-5.000"),
        ("SRC-KRL-04", "Tarif Commuter Line", "https://kci.id/", "manual",
         "proprietary", "jarang", "live", TODAY, "Rp3.000-20.000"),
        ("SRC-LRTJ-05", "Tarif LRT Jakarta", "https://www.lrtjakarta.co.id/",
         "manual", "proprietary", "jarang", "live", TODAY, "Rp5.000 flat"),
        ("SRC-LRTB-03", "Tarif LRT Jabodebek (matriks)",
         "https://lrtjabodebek.kai.id/", "manual", "proprietary", "jarang",
         "live", TODAY, "Rp5.000-20.000"),
    ]
    for s in sources:
        cur.execute("""
            INSERT INTO data_sources(source_id, name, url, access_method, license,
                update_frequency, status, verified_at, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source_id) DO UPDATE SET
                access_method=EXCLUDED.access_method, status=EXCLUDED.status,
                verified_at=EXCLUDED.verified_at, notes=EXCLUDED.notes
        """, s)
    conn.commit()

    # ---------- operators & modes ----------
    for op in OPERATORS:
        cur.execute("""
            INSERT INTO operators(operator_id, canonical_name, display_name, website)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (operator_id) DO UPDATE SET
                display_name=EXCLUDED.display_name
        """, op)
    for m in MODES:
        cur.execute("""
            INSERT INTO modes(mode_id, operator_id, display_name)
            VALUES (%s,%s,%s)
            ON CONFLICT (mode_id, operator_id) DO UPDATE SET
                display_name=EXCLUDED.display_name
        """, m)
    conn.commit()

    insert_stop = """
        INSERT INTO stops(stop_id_internal, operator_id, mode_id, canonical_name,
            display_name, geometry, osm_node_id, source_id, valid_from)
        VALUES (%s,%s,%s,%s,%s,
                CASE WHEN %s::text IS NULL THEN NULL ELSE ST_GeomFromEWKT(%s) END,
                %s,%s,%s)
        ON CONFLICT (stop_id_internal) DO UPDATE SET
            display_name=EXCLUDED.display_name, geometry=EXCLUDED.geometry,
            osm_node_id=EXCLUDED.osm_node_id
    """
    insert_name_hist = """
        INSERT INTO stop_name_history(stop_id_internal, name, valid_from, source_id)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
    """

    def add_stop(stop_id, operator, mode, canonical, display, node, src):
        geom = None
        osm_id = None
        if node:
            geom = f"SRID=4326;POINT({node['lon']} {node['lat']})"
            osm_id = node.get("id")
        cur.execute(insert_stop, (stop_id, operator, mode, canonical, display,
                                  geom, geom, osm_id, src, TODAY))
        if display and display != canonical:
            cur.execute(insert_name_hist, (stop_id, display, TODAY, src))
        if node is None:
            qlog.append(("rail_stops", "coordinate_missing", "warn",
                         f"{stop_id} ({canonical}) tanpa koordinat OSM"))

    def add_line(line_id, operator, mode, name, color, rel_ids, valid_from=None):
        cur.execute("""
            INSERT INTO lines(line_id, operator_id, mode_id, canonical_name,
                display_name, color, valid_from, valid_to, source_id, osm_relation_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s)
            ON CONFLICT (line_id) DO UPDATE SET
                osm_relation_id=EXCLUDED.osm_relation_id
        """, (line_id, operator, mode, name, name, color, valid_from,
              "SRC-COM-01", rel_ids))

    def add_route(route_id, line_id, pattern, direction, rel_id):
        cur.execute("""
            INSERT INTO routes(route_id, line_id, pattern_name, direction,
                valid_from, valid_to, source_id, osm_relation_id)
            VALUES (%s,%s,%s,%s,%s,NULL,'SRC-COM-01',%s)
            ON CONFLICT (route_id) DO UPDATE SET osm_relation_id=EXCLUDED.osm_relation_id
        """, (route_id, line_id, pattern, direction, TODAY, rel_id))

    def add_route_stops(route_id, stop_ids):
        rows = [(route_id, s, i + 1) for i, s in enumerate(stop_ids)]
        cur.executemany("""
            INSERT INTO route_stops(route_id, stop_id_internal, seq)
            VALUES (%s,%s,%s)
            ON CONFLICT (route_id, seq) DO NOTHING
        """, rows)

    # =================================================================
    # MRT Line 1 (MRT_NS)
    # =================================================================
    rel_lb = load_rel(9677669)  # Lebak Bulus -> Bundaran HI
    rel_bh = load_rel(9677670)  # Bundaran HI -> Lebak Bulus
    if rel_lb:
        add_line("MRT_NS", "MRT_JAKARTA", "MRT",
                 "MRT Line 1 (Lebak Bulus - Bundaran HI)", "1F77B4",
                 [9677669, 9677670], "2019-03-28")
        cand = rel_nodes(rel_lb, nodes)
        stop_ids = []
        for i, (canonical, display) in enumerate(MRT_NS_STOPS, 1):
            match = match_stop(canonical, None, cand, nodes)
            node = match[0] if match else None
            metode = match[1] if match else "GAGAL"
            stop_id = f"MRT_NS_{i:02d}"
            add_stop(stop_id, "MRT_JAKARTA", "MRT", canonical, display,
                     node, "SRC-COM-01" if node else "SRC-MRT-04")
            stop_ids.append(stop_id)
            qlog.append(("mrt_ns", "name_match",
                         "pass" if node else "warn",
                         f"{stop_id} {canonical} -> {metode}"
                         + (f" ({node['tags'].get('name')})" if node else "")))
        add_route("MRT_NS_out", "MRT_NS", "Lebak Bulus - Bundaran HI",
                  "outbound", 9677669)
        add_route("MRT_NS_in", "MRT_NS", "Bundaran HI - Lebak Bulus",
                  "inbound", 9677670)
        add_route_stops("MRT_NS_out", stop_ids)
        add_route_stops("MRT_NS_in", list(reversed(stop_ids)))

    # =================================================================
    # LRT Jakarta (LRTJ_KG_MRI)
    # =================================================================
    rel_lrtj = load_rel(10693119)  # Manggarai -> Kelapa Gading
    if rel_lrtj:
        cand = rel_nodes(rel_lrtj, nodes)
        cand_rev = list(reversed(cand))
        add_line("LRTJ_KG_MRI", "LRT_JAKARTA", "LRT",
                 "LRT Jakarta (Kelapa Gading - Manggarai)", "F5A623",
                 [10693119, 10693160], "2019-03-26")
        stop_ids = []
        for i, (canonical, display) in enumerate(LRTJ_STOPS, 1):
            match = match_stop(canonical, None, cand_rev, nodes) or \
                match_stop(canonical, None, cand, nodes)
            node = match[0] if match else None
            stop_id = f"LRTJ_KG_{i:02d}"
            add_stop(stop_id, "LRT_JAKARTA", "LRT", canonical, display,
                     node, "SRC-COM-01" if node else "SRC-LRTJ-03")
            stop_ids.append(stop_id)
            qlog.append(("lrtj", "name_match", "pass" if node else "warn",
                         f"{stop_id} {canonical} -> "
                         + (f"{match[1]} ({node['tags'].get('name')})" if node
                            else "GAGAL")))
        add_route("LRTJ_out", "LRTJ_KG_MRI", "Kelapa Gading - Manggarai",
                  "outbound", 10693119)
        add_route("LRTJ_in", "LRTJ_KG_MRI", "Manggarai - Kelapa Gading",
                  "inbound", 10693119)
        add_route_stops("LRTJ_out", stop_ids)
        add_route_stops("LRTJ_in", list(reversed(stop_ids)))

    # =================================================================
    # LRT Jabodebek (LRTB_CB + LRTB_BK)
    # =================================================================
    rel_cb = load_rel(16036440)  # Dukuh Atas -> Harjamukti
    rel_bk = load_rel(16079479)  # Dukuh Atas -> Jatimulya
    lrtb_ids = {}
    if rel_cb or rel_bk:
        cand_all = rel_nodes(rel_cb or {"members": []}, nodes) + \
            rel_nodes(rel_bk or {"members": []}, nodes)
        add_line("LRTB_CB", "LRT_JABODEBEK", "LRT",
                 "LRT Jabodebek Cibubur Line (Dukuh Atas BNI - Harjamukti)",
                 "E4007F", [16036440, 16036441], "2023-08-29")
        add_line("LRTB_BK", "LRT_JABODEBEK", "LRT",
                 "LRT Jabodebek Bekasi Line (Dukuh Atas BNI - Jatimulya)",
                 "12B886", [16079478, 16079479], "2023-08-29")
        for i, stop in enumerate(LRTB_STOPS, 1):
            canonical, display = stop[0], stop[1]
            alias = stop[2] if len(stop) > 2 else None
            match = match_stop(canonical, alias, cand_all, nodes)
            node = match[0] if match else None
            stop_id = f"LRTB_{i:02d}"
            lrtb_ids[canonical] = stop_id
            add_stop(stop_id, "LRT_JABODEBEK", "LRT", canonical, display,
                     node, "SRC-COM-01" if node else "SRC-LRTB-02")
            qlog.append(("lrtb", "name_match", "pass" if node else "warn",
                         f"{stop_id} {canonical} -> "
                         + (f"{match[1]} ({node['tags'].get('name')})" if node
                            else "GAGAL")))
        cb_ids = [lrtb_ids[x[0]] for x in LRTB_STOPS[:12]]
        bk_ids = [lrtb_ids[x[0]] for x in LRTB_STOPS[:8]] + \
                 [lrtb_ids[x[0]] for x in LRTB_STOPS[12:]]
        add_route("LRTB_CB_out", "LRTB_CB", "Dukuh Atas BNI - Harjamukti",
                  "outbound", 16036440)
        add_route("LRTB_CB_in", "LRTB_CB", "Harjamukti - Dukuh Atas BNI",
                  "inbound", 16036441)
        add_route_stops("LRTB_CB_out", cb_ids)
        add_route_stops("LRTB_CB_in", list(reversed(cb_ids)))
        add_route("LRTB_BK_out", "LRTB_BK", "Dukuh Atas BNI - Jatimulya",
                  "outbound", 16079479)
        add_route("LRTB_BK_in", "LRTB_BK", "Jatimulya - Dukuh Atas BNI",
                  "inbound", 16079478)
        add_route_stops("LRTB_BK_out", bk_ids)
        add_route_stops("LRTB_BK_in", list(reversed(bk_ids)))

    # =================================================================
    # KRL (5 koridor utama; full racket)
    # =================================================================
    krl_code_by_name = KRL_CODE_BY_NAME

    # bersihkan data KRL lama (idempoten; route_id bisa berubah antar versi)
    cur.execute("""
        DELETE FROM route_stops WHERE route_id IN (
            SELECT route_id FROM routes WHERE line_id LIKE 'KRL%')
    """)
    cur.execute("""
        DELETE FROM transfers
        WHERE from_stop_id IN (SELECT stop_id_internal FROM stops WHERE mode_id='KRL')
           OR to_stop_id IN (SELECT stop_id_internal FROM stops WHERE mode_id='KRL')
    """)
    cur.execute("DELETE FROM routes WHERE line_id LIKE 'KRL%'")
    cur.execute("DELETE FROM stops WHERE mode_id='KRL'")
    cur.execute("DELETE FROM line_geometries WHERE line_id LIKE 'KRL%'")

    def krl_stop_ids(rel: dict) -> list:
        """Urutan stop dari relasi; relasi loop (full racket) dipertahankan
        sebagai siklus (stop pertama muncul lagi di akhir)."""
        cand = rel_nodes(rel, nodes)
        names = [((n.get("tags") or {}).get("name") or "").strip() for n in cand]
        is_loop = len(names) >= 4 and names[0] and names[0] == names[-1]
        stop_ids = []
        seen = set()
        for idx, (n, nm) in enumerate(zip(cand, names)):
            if not nm:
                continue
            last = idx == len(cand) - 1
            if nm in seen and not (is_loop and last):
                continue
            seen.add(nm)
            stop_id = f"KRL_{slug(nm)}"
            add_stop(stop_id, "KRL_COMMUTER", "KRL", nm, None, n, "SRC-COM-01")
            code = krl_code_by_name.get(norm(nm))
            if code:
                cur.execute("""
                    UPDATE stops SET operator_stop_id=%s
                    WHERE stop_id_internal=%s
                """, (code, stop_id))
            stop_ids.append(stop_id)
        return stop_ids

    for line_id, name, segments in KRL_LINES:
        rel_ids = [rid for (_lbl, ro, ri) in segments for rid in (ro, ri) if rid]
        add_line(line_id, "KRL_COMMUTER", "KRL", name, "F26522", rel_ids, None)
        for si, (seg_label, rel_out, rel_in) in enumerate(segments, 1):
            tag = "" if len(segments) == 1 else f"_{si}"
            rel = load_rel(rel_out)
            if not rel:
                qlog.append(("krl", "relation_missing", "warn",
                             f"{line_id}: relasi OSM {rel_out} belum tersedia"))
                continue
            stop_ids = krl_stop_ids(rel)
            qlog.append(("krl", "line_ingest", "pass",
                         f"{line_id} [{seg_label}]: {len(stop_ids)} stop "
                         f"({'siklus' if stop_ids and stop_ids[0] == stop_ids[-1] else 'linear'})"))
            if len(stop_ids) < 5:
                qlog.append(("krl", "line_sparse", "warn",
                             f"{line_id} [{seg_label}]: hanya {len(stop_ids)} stasiun dari relasi OSM"))
            add_route(f"{line_id}{tag}_out", line_id, seg_label,
                      "outbound", rel_out)
            add_route_stops(f"{line_id}{tag}_out", stop_ids)
            if rel_in:
                rel_r = load_rel(rel_in)
                if rel_r:
                    stop_ids_r = krl_stop_ids(rel_r)
                    if stop_ids_r:
                        add_route(f"{line_id}{tag}_in", line_id, seg_label,
                                  "inbound", rel_in)
                        add_route_stops(f"{line_id}{tag}_in", stop_ids_r)

    # =================================================================
    # KRL rencana: Lin Soekarno-Hatta (OSM ada, TIDAK di GAPEKA Feb 2026)
    # -> line + stops saja, TANPA route (tidak bisa di-routing)
    # =================================================================
    rel_sth = load_rel(17675694)
    if rel_sth:
        cur.execute("""
            INSERT INTO lines(line_id, operator_id, mode_id, canonical_name,
                display_name, color, valid_from, valid_to, source_id, osm_relation_id)
            VALUES ('KRL_STH_LINE','KRL_COMMUTER','KRL',
                'KRL Lin Soekarno-Hatta (RENCANA)',
                'KRL Lin Soekarno-Hatta (Bandara STH - Manggarai; belum di GAPEKA Feb 2026)',
                '999999', NULL, NULL, 'SRC-COM-01', %s)
            ON CONFLICT (line_id) DO NOTHING
        """, ([17675694, 17675695],))
        seen_sth = set()
        n_sth = 0
        for n in rel_nodes(rel_sth, nodes):
            nm = (n.get("tags", {}).get("name") or "").strip()
            if not nm or nm in seen_sth:
                continue
            seen_sth.add(nm)
            add_stop(f"KRL_{slug(nm)}", "KRL_COMMUTER", "KRL", nm, None, n,
                     "SRC-COM-01")
            n_sth += 1
        qlog.append(("krl_sth", "planned_line", "warn",
                     f"{n_sth} stasiun diingest TANPA route (belum operasional per GAPEKA Feb 2026)"))

    # =================================================================
    # headways + fares
    # =================================================================
    for (line_id, d, pt, hw, pw, notes) in LINE_HEADWAYS:
        cur.execute("""
            INSERT INTO line_headways(line_id, direction, period_type, headway_min,
                peak_windows, source_id, notes)
            VALUES (%s,%s,%s,%s,%s,'SRC-KRL-03',%s)
            ON CONFLICT (line_id, direction, period_type) DO UPDATE SET
                headway_min=EXCLUDED.headway_min, notes=EXCLUDED.notes
        """, (line_id, d, pt, hw, pw, notes))
    for (op, mode, ftype, price, vf, basis, src, notes) in FARES:
        cur.execute("""
            DELETE FROM fares
            WHERE operator_id=%s AND mode_id=%s AND fare_type=%s
              AND source_id=%s
        """, (op, mode, ftype, src))
        cur.execute("""
            INSERT INTO fares(operator_id, mode_id, fare_type, price_idr,
                valid_from, legal_basis, source_id, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (op, mode, ftype, price, vf, basis, src, notes))
    # =================================================================
    # Geometri line rail: dari urutan route_stops (rail tidak punya
    # shapefile -> garis lewat koordinat stasiun; bentuk PROKSI)
    # =================================================================
    cur.execute("""
        DELETE FROM line_geometries
        WHERE line_id IN (SELECT line_id FROM lines
                          WHERE mode_id IN ('MRT','LRT','KRL'))
    """)
    cur.execute("""
        SELECT r.route_id, r.line_id, rs.stop_id_internal,
               ST_Y(s.geometry), ST_X(s.geometry)
        FROM route_stops rs
        JOIN routes r USING (route_id)
        JOIN stops s ON s.stop_id_internal = rs.stop_id_internal
        WHERE s.geometry IS NOT NULL
          AND (r.direction = 'outbound'
               OR NOT EXISTS (SELECT 1 FROM routes r2
                              WHERE r2.line_id = r.line_id
                                AND r2.direction = 'outbound'))
        ORDER BY r.line_id, r.route_id, rs.seq
    """)
    geom_routes: dict[str, list[list[tuple[float, float]]]] = {}
    cur_rid, cur_lid = None, None
    for rid, lid, _sid, lat, lon in cur.fetchall():
        if rid != cur_rid or lid != cur_lid:
            cur_rid, cur_lid = rid, lid
            geom_routes.setdefault(lid, []).append([])
        pts = geom_routes[lid][-1]
        if not pts or pts[-1] != (lat, lon):
            pts.append((lat, lon))
    n_geom = 0
    for lid, segs in geom_routes.items():
        segs = [s for s in segs if len(s) >= 2]
        if not segs:
            continue
        if len(segs) == 1:
            wkt = "LINESTRING(" + ", ".join(f"{lo} {la}" for la, lo in segs[0]) + ")"
        else:
            parts = []
            for s in segs:
                parts.append("(" + ", ".join(f"{lo} {la}" for la, lo in s) + ")")
            wkt = "MULTILINESTRING(" + ", ".join(parts) + ")"
        cur.execute("""
            INSERT INTO line_geometries(line_id, geometry)
            VALUES (%s, ST_GeomFromText(%s, 4326))
            ON CONFLICT (line_id) DO UPDATE SET geometry=EXCLUDED.geometry
        """, (lid, wkt))
        n_geom += 1
    qlog.append(("line_geom", "build", "pass",
                 f"{n_geom} geometri line rail (urutan koordinat stasiun; PROKSI)"))
    conn.commit()
    for ds, ct, res, det in qlog:
        cur.execute("""
            INSERT INTO data_quality_results(dataset, check_type, result, details)
            VALUES (%s,%s,%s,%s)
        """, (ds, ct, res, det))
    cur.execute("""
        INSERT INTO ingest_runs(pipeline, finished_at, rows_affected, notes)
        VALUES ('ingest_rail.py', now(), %s, %s)
    """, (len(qlog), "MRT NS + LRTJ + LRTB + KRL 5 koridor; OSM + datum API + GAPEKA"))
    conn.commit()
    conn.close()
    n_pass = sum(1 for q in qlog if q[2] == "pass")
    n_warn = sum(1 for q in qlog if q[2] == "warn")
    print(f"SELESAI dalam {time.time()-t0:.1f}s — quality: {n_pass} pass, {n_warn} warn")
    for q in qlog:
        if q[2] != "pass":
            print("  !", q)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Tool chatbot JPTI — pembungkus engine yang sudah ada (tanpa mengubah
logika): routing (netload), ridership (CSV /api/ridership), RAG (rag_query).

LLM tidak menyentuh angka: tool mengembalikan data terstruktur + sumber,
LLM hanya menyusun bahasanya (prinsip §9 context.md).
"""
import re

from db import connect
from route_query import match_stops
from routing import Network
from rag_query import rag_search


# ---------- helper serialisasi (mirror api/app.py) ----------

def stop_brief(net: Network, sid: str) -> dict:
    s = net.stops[sid]
    disp = (s.display_name
            if s.display_name and s.display_name != s.name else None)
    return {"stop_id": s.stop_id, "name": s.name, "display": disp,
            "aliases": s.aliases, "mode": s.mode,
            "lat": s.lat, "lon": s.lon}


def _line_info(net: Network, line_id):
    name = net.line_name.get(line_id, line_id or "?")
    disp = net.line_display.get(line_id)
    corridor = None
    if disp and disp != name:
        prefix, sep, _rest = disp.partition(" — ")
        if sep and prefix.strip():
            corridor = prefix.strip()
    return name, corridor


def _serialize_segment(net: Network, seg: dict) -> dict:
    if seg["type"] == "transfer":
        return {"type": "walk", "from": stop_brief(net, seg["from"]),
                "to": stop_brief(net, seg["to"]), "walk_sec": seg["walk_sec"]}
    line_id = seg.get("line")
    line, corridor = _line_info(net, line_id)
    return {"type": "ride", "mode": seg["mode"], "line_id": line_id,
            "line": line, "corridor": corridor,
            "from": stop_brief(net, seg["from"]),
            "to": stop_brief(net, seg["to"]),
            "travel_sec": seg["travel_sec"], "wait_sec": seg["wait_sec"],
            "fare": seg.get("fare", 0)}


# ---------- tool rute ----------

def plan_route(net: Network, origin: str, dest: str,
               prefer: str = "tercepat", top: int = 5) -> dict:
    """Pencarian rute; bentuk respons identik POST /api/route."""
    o_cands = match_stops(net, origin, top=top)
    d_cands = match_stops(net, dest, top=top)
    if not o_cands:
        return {"status": "not_found", "where": "origin", "text": origin}
    if not d_cands:
        return {"status": "not_found", "where": "dest", "text": dest}

    ambiguous = {}
    for tag, cands in (("origin", o_cands), ("dest", d_cands)):
        if cands[0][1] < 100 and len(cands) > 1:
            ambiguous[tag] = [
                {**stop_brief(net, sid), "score": score}
                for sid, score in cands
            ]
    if ambiguous:
        return {"status": "ambiguous", "candidates": ambiguous}

    origin_id, dest_id = o_cands[0][0], d_cands[0][0]
    res = net.route(origin_id, dest_id, prefer)
    if not res.found:
        return {"status": "no_route", "message": res.message,
                "origin": stop_brief(net, origin_id),
                "dest": stop_brief(net, dest_id)}
    return {
        "status": "ok",
        "preference": prefer,
        "origin": stop_brief(net, origin_id),
        "dest": stop_brief(net, dest_id),
        "time_sec": res.time_sec,
        "time_fmt": Network.fmt_time(res.time_sec),
        "fare": res.fare,
        "transfers": res.transfers,
        "segments": [_serialize_segment(net, s) for s in res.segments],
    }


# ---------- tool ridership ----------

YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _period_label(row: dict) -> str:
    if row["period_type"] == "year":
        return row["period_start"][:4]
    y, m = row["period_start"][:4], row["period_start"][5:7]
    return f"{y}-{m}"


def _pick_rows(rows: list[dict], mode: str | None,
               period: str | None) -> list[dict]:
    out = [r for r in rows if not mode or r["mode_id"] == mode.upper()]
    years = sorted(set(YEAR_RE.findall(period or "")))
    if years:
        keep = []
        for r in out:
            y = r["period_start"][:4]
            if y not in years:
                continue
            keep.append(r)
        # utamakan baris tahunan; bila tidak ada, pakai bulanan
        annual = [r for r in keep if r["period_type"] == "year"]
        if annual:
            return annual[:24]
        return sorted(keep, key=lambda r: r["period_start"])[:24]
    # tanpa tahun: tahun baris tahunan terakhir + 12 bulan terakhir
    annual = sorted((r for r in out if r["period_type"] == "year"),
                    key=lambda r: r["period_start"], reverse=True)[:2]
    monthly = sorted((r for r in out if r["period_type"] == "month"),
                     key=lambda r: r["period_start"], reverse=True)[:12]
    return sorted(annual + monthly, key=lambda r: r["period_start"],
                  reverse=True)


def ridership_summary(rows: list[dict], mode: str | None = None,
                      period: str | None = None) -> dict:
    sel = _pick_rows(rows, mode, period)
    total_by_period: dict[str, int] = {}
    for r in sel:
        lbl = _period_label(r)
        total_by_period[lbl] = total_by_period.get(lbl, 0) + r["passenger_count"]
    if not sel:
        return {"available": False,
                "note": f"tidak ada baris ridership untuk mode={mode} "
                        f"period={period}"}
    return {
        "available": True,
        "mode": (mode or "SEMUA").upper(),
        "period": period or "terbaru",
        "rows": [{
            "period": _period_label(r),
            "period_type": r["period_type"],
            "passenger_count": r["passenger_count"],
            "source_id": r["source_id"],
            "source_name": r["source_name"],
            "data_label": r["data_label"],
            "is_approx": r["is_approx"],
            "notes": r.get("notes") or None,
        } for r in sel],
        "total_by_period": total_by_period,
        "definition": sel[0]["definition_ref"],
    }


def compare_modes(rows: list[dict], period: str | None = None) -> dict:
    years = sorted(set(YEAR_RE.findall(period or "")))
    if not years:
        years = sorted({r["period_start"][:4] for r in rows if
                        r["period_type"] == "year"})[-2:]
    out = []
    modes = sorted({r["mode_id"] for r in rows})
    for m in modes:
        for y in years:
            yr = [r for r in rows if r["mode_id"] == m
                  and r["period_start"][:4] == y]
            annual = [r for r in yr if r["period_type"] == "year"]
            monthly = [r for r in yr if r["period_type"] == "month"]
            if annual:
                total = annual[0]["passenger_count"]
                n_months = 12
            elif monthly:
                total = sum(r["passenger_count"] for r in monthly)
                n_months = len(monthly)
            else:
                continue
            out.append({
                "mode": m, "year": y, "total": total,
                "n_months": n_months,
                "partial": (not annual and n_months < 12),
                "source_id": (annual or monthly)[0]["source_id"],
                "data_label": (annual or monthly)[0]["data_label"],
            })
    # pertumbuhan YoY bila dua tahun ada per mode
    for o in out:
        prev = next((p for p in out if p["mode"] == o["mode"]
                     and p["year"] == str(int(o["year"]) - 1)), None)
        if prev and prev["total"]:
            o["growth_pct_yoy"] = round(
                (o["total"] - prev["total"]) / prev["total"] * 100, 1)
    return {"rows": out, "years": years}


# ---------- tool RAG ----------

def rag(query: str, top_k: int = 4, mode: str | None = None) -> dict:
    try:
        results = rag_search(query, top_k=top_k, mode=mode)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"retrieval gagal: {e}",
                "results": []}
    return {
        "available": bool(results),
        "query": query,
        "results": [{
            "document_id": r["document_id"],
            "text": r["text"],
            "citation": r["citation"],
        } for r in results],
    }


def rag_sources(rag_result: dict) -> list[dict]:
    """Susun daftar sumber bernomor untuk prompt LLM + respons API."""
    srcs = []
    for i, r in enumerate(rag_result.get("results", []), start=1):
        c = r["citation"]
        pages = c.get("pages") or [None, None]
        srcs.append({
            "n": i,
            "title": c.get("title"),
            "section": c.get("section"),
            "pages": [p for p in pages if p],
            "source_id": c.get("source_id"),
            "url": c.get("source_url"),
            "published_at": c.get("published_at"),
            "fresh_label": c.get("fresh_label"),
        })
    return srcs


# ---------- tool terstruktur: tarif & jadwal (dari Postgres) ----------
# Data ini sudah ada di DB (tabel fares / line_headways / stop_times) tapi
# sebelumnya tidak dipakai chatbot — hanya RAG dokumen, yang korpusnya
# terbatas. LLM tetap tidak menyentuh angka: tool mengembalikan data
# terstruktur + sumber (prinsip §9 context.md).

def tool_fare(mode: str | None = None) -> dict:
    """Tarif per moda dari tabel fares (min/max/flat + dasar hukum + sumber).

    Baris di-group per (moda, operator, tipe, harga); n_routes = jumlah
    baris asal (GTFS TransJakarta punya banyak baris per harga).
    """
    conn = connect()
    try:
        cur = conn.cursor()
        sql = """SELECT mode_id, operator_id, fare_type, price_idr,
                        valid_from, legal_basis, source_id, notes
                 FROM fares"""
        args: tuple = ()
        if mode:
            sql += " WHERE mode_id = %s"
            args = (mode.upper(),)
        sql += " ORDER BY mode_id, operator_id, fare_type"
        cur.execute(sql, args)
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return {"available": False,
                "note": f"tabel fares tidak punya baris untuk mode={mode}"}
    agg: dict[tuple, dict] = {}
    for r in rows:
        k = (r[0], r[1], r[2], r[3])
        e = agg.setdefault(k, {
            "mode_id": r[0], "operator_id": r[1], "fare_type": r[2],
            "price_idr": r[3],
            "valid_from": r[4].isoformat() if r[4] else None,
            "legal_basis": r[5] or None, "source_id": r[6] or None,
            "notes": [] if not r[7] else [r[7]],
            "n_entries": 0,
        })
        e["n_entries"] += 1
        if r[5] and e["legal_basis"] != r[5]:
            e["legal_basis"] = None  # beragam per baris
        if r[7] and r[7] not in e["notes"]:
            e["notes"].append(r[7])
    entries = list(agg.values())
    for e in entries:
        if len(e["notes"]) > 1:
            e["notes"] = e["notes"][:3]
    zero = [e for e in entries if e["price_idr"] == 0]
    note = ("Estimasi tarif pada perhitungan rute memakai flat minimum per "
            "moda (label proksi); angka di atas dari tabel fares JPTI "
            "sesuai sumber & periode berlaku.")
    if zero:
        note += (" Baris Rp0 (TransJakarta/GTFS) = rute tanpa aturan tarif "
                 "di file GTFS — bukan layanan gratis.")
    return {"available": True, "mode": (mode or "SEMUA").upper(),
            "entries": entries, "note": note}


def _line_mode(line_id: str) -> str | None:
    if line_id.startswith("KRL_"):
        return "KRL"
    if line_id.startswith(("LRTJ_", "LRTB_")):
        return "LRT"
    if line_id.startswith("MRT_"):
        return "MRT"
    return None


def tool_schedule(mode: str | None = None, net: Network | None = None) -> dict:
    """Headway & jendela sibuk per jalur (line_headways) + jam pelayanan
    TransJakarta dari GTFS (stop_times).

    Moda rail TIDAK punya tabel perjalanan lengkap di DB; headway + jendela
    sibuk adalah proksi jadwal/kapasitas (label proksi), bukan data
    penumpang.
    """
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT line_id, direction, period_type, headway_min,
                              peak_windows, source_id, notes
                       FROM line_headways
                       ORDER BY line_id, period_type, direction""")
        hw = cur.fetchall()
        cur.execute("""SELECT MIN(st.departure_time), MAX(st.departure_time)
                       FROM stop_times st JOIN trips t USING (trip_id)""")
        brt_range = cur.fetchone()
    finally:
        conn.close()

    def display(line_id: str) -> str:
        if net is not None:
            d = net.line_display.get(line_id)
            if d:
                return d
            n = net.line_name.get(line_id)
            if n:
                return n
        return line_id

    mu = (mode or "").upper()

    def pick(line_id: str) -> bool:
        if not mu:
            return True
        if mu == "LRT":
            return line_id.startswith(("LRTJ_", "LRTB_"))
        return _line_mode(line_id) == mu

    lines: dict[str, dict] = {}
    for line_id, direction, period, headway, windows, src, notes in hw:
        if not pick(line_id):
            continue
        e = lines.setdefault(line_id, {
            "line_id": line_id, "line": display(line_id),
            "mode": _line_mode(line_id), "periods": {},
            "sources": [], "notes": [],
        })
        e["periods"][period] = {"headway_min": headway,
                                "peak_windows": windows,
                                "direction": direction}
        if src and src not in e["sources"]:
            e["sources"].append(src)
        if notes and notes not in e["notes"]:
            e["notes"].append(notes)

    out = {
        "available": bool(lines) or mu in ("", "BRT"),
        "mode": (mode or "SEMUA").upper(),
        "lines": list(lines.values()),
        "note": ("headway = jarak antar kedatangan (proksi kapasitas/jadwal, "
                 "bukan data penumpang). Moda rail: jadwal perjalanan "
                 "lengkap belum ada di DB — hanya headway + jendela sibuk "
                 "dari rilis resmi. Jendela sibuk = periode yang cenderung "
                 "lebih padat (proksi)."),
    }
    if mu in ("", "BRT") and brt_range and brt_range[0]:
        out["brt"] = {
            "earliest_departure": brt_range[0].strftime("%H:%M"),
            "latest_departure": brt_range[1].strftime("%H:%M"),
            "source_id": "SRC-TJ-02",
            "note": ("Jadwal GTFS TransJakarta terkini; jam per koridor "
                     "berbeda (sebagian koridor beroperasi nyaris 24 jam)."),
        }
    return out

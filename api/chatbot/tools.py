# -*- coding: utf-8 -*-
"""Tool chatbot JPTI — pembungkus engine yang sudah ada (tanpa mengubah
logika): routing (netload), ridership (CSV /api/ridership), RAG (rag_query).

LLM tidak menyentuh angka: tool mengembalikan data terstruktur + sumber,
LLM hanya menyusun bahasanya (prinsip §9 context.md).
"""
import re

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

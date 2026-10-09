# -*- coding: utf-8 -*-
"""Tool chatbot JPTI — pembungkus engine yang sudah ada (tanpa mengubah
logika): routing (netload), ridership (CSV /api/ridership), RAG (rag_query).

LLM tidak menyentuh angka: tool mengembalikan data terstruktur + sumber,
LLM hanya menyusun bahasanya (prinsip §9 context.md).
"""
import re

from db import connect
import crowding as _crowding
from route_query import match_stops
from routing import Network
from rag_query import rag_retrieve


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
                "to": stop_brief(net, seg["to"]), "walk_sec": seg["walk_sec"],
                "time_method": seg.get("time_method") or "walking_time_proxy",
                "source_id": seg.get("source_id")}
    line_id = seg.get("line")
    line, corridor = _line_info(net, line_id)
    return {"type": "ride", "mode": seg["mode"], "line_id": line_id,
            "route_id": seg.get("route"), "line": line,
            "corridor": corridor,
            "from": stop_brief(net, seg["from"]),
            "to": stop_brief(net, seg["to"]),
            "travel_sec": seg["travel_sec"], "wait_sec": seg["wait_sec"],
            "fare": seg.get("fare", 0),
            "time_method": (seg.get("time_method")
                            or ("gtfs_schedule_average"
                                if seg["mode"] == "BRT"
                                else "distance_speed_dwell_proxy")),
            "source_id": (seg.get("source_id")
                          or net.line_source.get(line_id))}


def _duration_fmt(seconds: float) -> str:
    minutes = max(1, int(round(float(seconds) / 60)))
    if minutes < 60:
        return f"{minutes} menit"
    return f"{minutes // 60} jam {minutes % 60:02d} menit"


def _stop_label(stop: dict) -> str:
    return stop.get("display") or stop.get("name") or stop.get("stop_id") or "?"


def _collapse_route_segments(segments: list[dict]) -> list[dict]:
    """Gabungkan edge berurutan menjadi leg yang tetap kontinu.

    Routing menyimpan satu edge per pasangan stop. Chatbot membutuhkan satu
    langkah per layanan/jalan kaki, tetapi tidak boleh melompati edge transfer.
    """
    legs: list[dict] = []
    for raw in segments:
        seg = {**raw, "edge_count": 1, "via": []}
        previous = legs[-1] if legs else None
        continuous = bool(
            previous
            and previous["to"]["stop_id"] == seg["from"]["stop_id"]
        )
        same_ride = bool(
            continuous and previous["type"] == seg["type"] == "ride"
            and previous.get("mode") == seg.get("mode")
            and previous.get("line_id") == seg.get("line_id")
            and previous.get("route_id") == seg.get("route_id")
        )
        same_walk = bool(
            continuous and previous["type"] == seg["type"] == "walk"
        )
        if same_ride:
            previous["to"] = seg["to"]
            previous["travel_sec"] += seg.get("travel_sec", 0)
            previous["wait_sec"] += seg.get("wait_sec", 0)
            previous["fare"] += seg.get("fare", 0)
            previous["edge_count"] += 1
            continue
        if same_walk:
            previous["via"].append(previous["to"])
            previous["via"].extend(seg.get("via") or [])
            previous["to"] = seg["to"]
            previous["walk_sec"] += seg.get("walk_sec", 0)
            previous["edge_count"] += 1
            if not previous.get("source_id"):
                previous["source_id"] = seg.get("source_id")
            continue
        legs.append(seg)
    return legs


def _route_metrics(legs: list[dict], routing_transfer_score: int) -> dict:
    rides = [leg for leg in legs if leg["type"] == "ride"]
    mode_change_count = sum(
        1 for before, after in zip(rides, rides[1:])
        if before.get("mode") != after.get("mode")
    )
    return {
        "boarding_count": len(rides),
        "service_change_count": max(0, len(rides) - 1),
        "mode_change_count": mode_change_count,
        "walking_transfer_count": sum(1 for leg in legs
                                      if leg["type"] == "walk"),
        # Nilai internal Dijkstra menghitung edge transfer dan boarding untuk
        # penalti optimasi; jangan ditampilkan sebagai "pindah moda".
        "routing_transfer_score": routing_transfer_score,
    }


def _route_sources(net: Network, legs: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}

    def add(source_id: str | None, claim: str, label: str = "historis"):
        if not source_id:
            return
        source = by_id.setdefault(source_id, {
            **net.source_meta.get(source_id, {}),
            "source_id": source_id,
            "title": (net.source_meta.get(source_id, {}).get("title")
                      or source_id),
            "url": net.source_meta.get(source_id, {}).get("url"),
            "fresh_label": label,
            "claims": [],
        })
        if claim not in source["claims"]:
            source["claims"].append(claim)

    for leg in legs:
        if leg["type"] == "ride":
            add(leg.get("source_id"),
                f"jaringan {leg.get('mode') or 'angkutan'}")
            if leg.get("time_method") == "gtfs_schedule_average":
                add(leg.get("source_id"), "waktu berdasarkan jadwal GTFS")
            fare_meta = net.mode_fare_source.get(leg.get("mode")) or {}
            add(fare_meta.get("source_id"),
                f"tarif minimum {leg.get('mode') or 'moda'}")
        elif leg.get("source_id"):
            add(leg.get("source_id"), "koneksi transfer berjalan kaki")

    # Metodologi merupakan provenance perhitungan, bukan sumber eksternal.
    by_id["JPTI-ROUTING"] = {
        "source_id": "JPTI-ROUTING",
        "title": "Metodologi perhitungan rute JPTI",
        "url": None,
        "verified_at": None,
        "status": "internal",
        "fresh_label": "proksi",
        "claims": [
            "pencarian rute pada graf",
            "waktu rail dari jarak, kecepatan rata-rata, dwell, dan waktu tunggu",
            "waktu berjalan kaki dari jarak atau tabel transfer",
        ],
    }
    sources = list(by_id.values())
    for number, source in enumerate(sources, start=1):
        source["n"] = number
    return sources


def _build_itinerary(legs: list[dict], sources: list[dict]) -> list[dict]:
    source_numbers = {source["source_id"]: source["n"] for source in sources}
    itinerary = []
    for index, leg in enumerate(legs, start=1):
        origin = _stop_label(leg["from"])
        destination = _stop_label(leg["to"])
        source_ids = ["JPTI-ROUTING"]
        if leg.get("source_id"):
            source_ids.insert(0, leg["source_id"])
        if leg["type"] == "ride":
            service = leg.get("corridor") or leg.get("line") or leg.get("mode")
            duration = leg.get("travel_sec", 0) + leg.get("wait_sec", 0)
            mode = leg.get("mode") or ""
            service_label = (str(service) if str(service).casefold().startswith(
                mode.casefold()) else f"{mode} {service}")
            instruction = (f"Naik {service_label} dari {origin} "
                           f"ke {destination} sekitar {_duration_fmt(duration)}.")
        else:
            duration = leg.get("walk_sec", 0)
            via = ", ".join(_stop_label(stop) for stop in leg.get("via") or [])
            via_text = f" melalui {via}" if via else ""
            instruction = (f"Jalan kaki dari {origin} ke {destination} "
                           f"sekitar {_duration_fmt(duration)}{via_text}.")
        itinerary.append({
            **leg,
            "step": index,
            "duration_sec": duration,
            "duration_fmt": _duration_fmt(duration),
            "instruction": instruction,
            "source_ids": list(dict.fromkeys(source_ids)),
            "source_refs": [source_numbers[sid] for sid in source_ids
                            if sid in source_numbers],
        })
    return itinerary


def serialize_route_result(net: Network, result, preference: str,
                           origin_id: str, dest_id: str) -> dict:
    """Bentuk kanonik hasil rute untuk API dan chatbot."""
    segments = [_serialize_segment(net, segment)
                for segment in result.segments]
    legs = _collapse_route_segments(segments)
    metrics = _route_metrics(legs, result.transfers)
    sources = _route_sources(net, legs)
    itinerary = _build_itinerary(legs, sources)
    return {
        "status": "ok",
        "preference": preference,
        "origin": stop_brief(net, origin_id),
        "dest": stop_brief(net, dest_id),
        "time_sec": result.time_sec,
        "time_fmt": Network.fmt_time(result.time_sec),
        "time_display": _duration_fmt(result.time_sec),
        "fare": result.fare,
        # Kompatibilitas API: transfers kini berarti pergantian layanan yang
        # benar-benar dapat dijelaskan kepada pengguna.
        "transfers": metrics["service_change_count"],
        "route_metrics": metrics,
        "segments": segments,
        "itinerary": itinerary,
        "sources": sources,
        "data_label": "proksi",
        "fare_basis": "tarif minimum per moda yang dinaiki",
        "time_basis": (
            "BRT memakai rata-rata jadwal GTFS bila tersedia; rail memakai "
            "jarak, kecepatan rata-rata, dwell, dan waktu tunggu."
        ),
        "limitations": (
            "Belum memperhitungkan gangguan dan kondisi operasional langsung."
        ),
    }


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

    # Bila skor teks sama, kandidat dengan moda yang sama seperti titik asal
    # ditempatkan lebih dahulu. Ini membuat stasiun KRL lebih relevan untuk
    # perjalanan yang dimulai dari stasiun KRL, tanpa menghapus opsi BRT.
    origin_best_count = sum(1 for _sid, score in o_cands
                            if score == o_cands[0][1])
    origin_mode = (net.stops[o_cands[0][0]].mode
                   if origin_best_count == 1 else None)
    if origin_mode:
        d_cands.sort(key=lambda item: (
            -item[1],
            0 if net.stops[item[0]].mode == origin_mode else 1,
            len(net.stops[item[0]].name),
        ))

    ambiguous = {}
    resolved = {}
    for tag, cands in (("origin", o_cands), ("dest", d_cands)):
        best_score = cands[0][1]
        best_count = sum(1 for _sid, score in cands
                         if score == best_score)
        # Lebih dari satu kecocokan eksak lintas moda tetap ambigu. Untuk
        # pencarian fuzzy, tampilkan kandidat terbaik agar pengguna memilih.
        if len(cands) > 1 and (best_score < 100 or best_count > 1):
            shown = ([item for item in cands if item[1] == best_score]
                     if best_score == 100 else cands)
            ambiguous[tag] = [
                {**stop_brief(net, sid), "score": score}
                for sid, score in shown
            ]
        else:
            resolved[tag] = stop_brief(net, cands[0][0])
    if ambiguous:
        return {"status": "ambiguous", "candidates": ambiguous,
                "resolved": resolved}

    origin_id, dest_id = o_cands[0][0], d_cands[0][0]
    return plan_route_ids(net, origin_id, dest_id, prefer)


def plan_route_ids(net: Network, origin_id: str, dest_id: str,
                   prefer: str = "tercepat") -> dict:
    """Jalankan routing dari stop_id yang sudah dipilih pengguna.

    Jalur ini mencegah pilihan kandidat bernomor dicocokkan ulang sebagai
    teks dan kembali menjadi ambigu.
    """
    if origin_id not in net.stops:
        return {"status": "not_found", "where": "origin",
                "text": origin_id}
    if dest_id not in net.stops:
        return {"status": "not_found", "where": "dest", "text": dest_id}
    res = net.route(origin_id, dest_id, prefer)
    if not res.found:
        return {"status": "no_route", "message": res.message,
                "origin": stop_brief(net, origin_id),
                "dest": stop_brief(net, dest_id)}
    return serialize_route_result(net, res, prefer, origin_id, dest_id)


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

def rag(query: str, top_k: int = 4, mode: str | None = None,
        operator: str | None = None, doc_type: str | None = None,
        fresh_label: str | None = None) -> dict:
    try:
        payload = rag_retrieve(
            query, top_k=top_k, mode=mode, operator=operator,
            doc_type=doc_type, fresh_label=fresh_label,
        )
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"retrieval gagal: {e}",
                "status": "error", "results": []}
    return {
        "available": payload["status"] == "ok",
        "status": payload["status"],
        "note": payload.get("note"),
        "query": query,
        "filters": payload.get("filters", {}),
        "retriever_version": payload.get("retriever_version"),
        "results": [{
            "document_id": r["document_id"],
            "chunk_id": r["chunk_id"],
            "score": r["score"],
            "text": r["text"],
            "citation": r["citation"],
        } for r in payload["results"]],
    }


def crowding_estimate(line: str | None = None, mode: str | None = None,
                      t: str | None = None,
                      day_type: str = "weekday") -> dict:
    """Estimasi kepadatan model crowding-v1 (proksi berlabel)."""
    if not line and not mode:
        return {"available": False,
                "note": "butuh mode atau jalur (estimasi tanpa scope tidak "
                        "bermakna — jendela sibuk terdokumentasi per moda)"}
    try:
        out = _crowding.estimate(line_id=line, mode=mode, t=t,
                                 day_type=day_type)
        out["available"] = True
        return out
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"estimasi gagal: {e}"}


def crowding_daily(line: str | None = None, mode: str | None = None,
                   day_type: str = "weekday") -> dict:
    """Ringkasan harian (rentang jam per kategori) — dipakai ketika
    pengguna tidak menyebut jam spesifik."""
    if not line and not mode:
        return {"available": False,
                "note": "butuh mode atau jalur untuk ringkasan harian"}
    try:
        out = _crowding.daily_summary(line_id=line, mode=mode,
                                      day_type=day_type)
        out["available"] = True
        return out
    except Exception as e:  # noqa: BLE001
        return {"available": False, "note": f"ringkasan harian gagal: {e}"}


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
            "chunk_id": r.get("chunk_id"),
            "relevance": r.get("score"),
        })
    return srcs


# ---------- tool terstruktur: tarif & jadwal (dari Postgres) ----------
# Data ini sudah ada di DB (tabel fares / line_headways / stop_times) tapi
# sebelumnya tidak dipakai chatbot — hanya RAG dokumen, yang korpusnya
# terbatas. LLM tetap tidak menyentuh angka: tool mengembalikan data
# terstruktur + sumber (prinsip §9 context.md).

def _mrt_stop_matches(cur, name: str) -> list[str]:
    """Cocokkan nama bebas -> stop_id MRT (canonical, display, alias
    stop_name_history). Persis = prioritas; substring hanya utk query
    >= 3 karakter. Mengembalikan 0/1/banyak (banyak = ambigu)."""
    q = (name or "").strip().lower()
    if not q:
        return []
    cur.execute("""SELECT stop_id_internal, canonical_name, display_name
                   FROM stops WHERE mode_id = 'MRT'""")
    stops = cur.fetchall()
    cur.execute("""SELECT h.stop_id_internal, h.name
                   FROM stop_name_history h
                   JOIN stops s USING (stop_id_internal)
                   WHERE s.mode_id = 'MRT'""")
    aliases = cur.fetchall()
    matches: set[str] = set()
    for sid, canon, disp in stops:
        for nm in (canon, disp):
            if not nm:
                continue
            n = nm.lower()
            if n == q or (len(q) >= 3 and (q in n or n in q)):
                matches.add(sid)
    for sid, nm in aliases:
        n = nm.lower()
        if n == q or (len(q) >= 3 and (q in n or n in q)):
            matches.add(sid)
    return sorted(matches)


def _mrt_pair_fare(cur, origin: str, dest: str) -> dict | None:
    """Tarif per pasangan dari matriks resmi MRT (fare_type='matrix').

    Matriks terarah & asimetris di beberapa sel; arah langsung
    diprioritaskan, arah balik sebagai fallback. None bila nama tidak
    cocok / ambigu / pasangan tak ada.
    """
    o_ids = _mrt_stop_matches(cur, origin)
    d_ids = _mrt_stop_matches(cur, dest)
    if not o_ids or not d_ids or len(o_ids) > 1 or len(d_ids) > 1:
        return None
    o, d = o_ids[0], d_ids[0]
    if o == d:
        return None
    cur.execute("""SELECT price_idr, valid_from, legal_basis, source_id
                   FROM fares
                   WHERE mode_id = 'MRT' AND fare_type = 'matrix'
                     AND ((from_stop_id = %s AND to_stop_id = %s)
                          OR (from_stop_id = %s AND to_stop_id = %s))
                   ORDER BY (from_stop_id = %s) DESC""",
                (o, d, d, o, o))
    r = cur.fetchone()
    if not r:
        return None
    names = {}
    for sid in (o, d):
        cur.execute("""SELECT canonical_name FROM stops
                       WHERE stop_id_internal = %s""", (sid,))
        names[sid] = cur.fetchone()[0]
    return {"origin": names[o], "dest": names[d], "price_idr": r[0],
            "valid_from": r[1].isoformat() if r[1] else None,
            "legal_basis": r[2] or None, "source_id": r[3] or None,
            "note": ("Tarif per pasangan dari matriks resmi MRT Jakarta "
                     "(Pergub DKI 34/2019, snapshot halaman resmi "
                     "2026-06-14). Arah ditelusuri sesuai matriks — "
                     "beberapa sel asimetris.")}


def tool_fare(mode: str | None = None, origin: str | None = None,
              dest: str | None = None) -> dict:
    """Tarif per moda dari tabel fares (min/max/flat + dasar hukum + sumber).

    Baris di-group per (moda, operator, tipe, harga); n_entries = jumlah
    baris asal (GTFS TransJakarta punya banyak baris per harga).
    Baris fare_type='matrix' (matriks per-pasangan MRT) TIDAK masuk
    agregat — ditangani oleh lookup per-pasangan (origin/dest) dan
    diringkas di `matrix_summary`.
    """
    conn = connect()
    try:
        cur = conn.cursor()
        pair = None
        if (mode and mode.upper() == "MRT" and origin and dest):
            pair = _mrt_pair_fare(cur, origin, dest)
        sql = """SELECT mode_id, operator_id, fare_type, price_idr,
                        valid_from, legal_basis, source_id, notes
                 FROM fares
                 WHERE fare_type <> 'matrix'"""
        args: tuple = ()
        if mode:
            sql += " AND mode_id = %s"
            args = (mode.upper(),)
        sql += " ORDER BY mode_id, operator_id, fare_type"
        cur.execute(sql, args)
        rows = cur.fetchall()
        cur.execute("""SELECT COUNT(*), MIN(price_idr), MAX(price_idr)
                       FROM fares WHERE fare_type = 'matrix'"""
                    + (" AND mode_id = %s" if mode else ""),
                    (mode.upper(),) if mode else ())
        mrow = cur.fetchone()
    finally:
        conn.close()
    if not rows and not (mrow and mrow[0]):
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
    res: dict = {"available": True, "mode": (mode or "SEMUA").upper(),
                 "entries": entries, "note": note}
    if mrow and mrow[0]:
        res["matrix_summary"] = {
            "pairs_directed": mrow[0],
            "min_idr": mrow[1], "max_idr": mrow[2],
            "note": ("Matriks tarif per-pasangan MRT Jakarta (13x13, "
                     "156 arah). Untuk pertanyaan 'dari X ke Y', lihat "
                     "blok `pair`; bila tak ada, tarifnya ada di antara "
                     "min dan max di atas (label historis — snapshot "
                     "resmi 2026-06-14, berlaku 1 Apr 2019).")}
    if pair:
        res["pair"] = pair
    return res


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

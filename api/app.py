# -*- coding: utf-8 -*-
"""JPTI Web API — Fase B.1 (backend FastAPI).

Membungkus engine Fase 2–3 yang sudah teruji (tanpa mengubah logikanya):
  - netload + routing      → POST /api/route, GET /api/stops/search
  - rag_query.rag_search   → POST /api/rag
  - DB + CSV ridership     → GET /api/ridership, /api/network/lines, /api/meta, /api/health

Objek jaringan dimuat SEKALI saat startup (netload ±8 dtk) dan dipakai ulang
oleh semua request. Semua angka yang dikembalikan membawa label sumber sesuai
konvensi proyek (aktual/historis/prediksi/proksi) — lihat `disclaimer`.

Jalankan:  .venv\\Scripts\\python -m uvicorn api.app:app --port 8000
"""
import csv
import sys
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipelines"))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from db import connect  # noqa: E402
from netload import load_network  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from rag_query import rag_search  # noqa: E402
from route_query import match_stops  # noqa: E402
from routing import Network  # noqa: E402

APP_VERSION = "0.1.0"
RIDER_CSV = ROOT / "data" / "processed" / "ridership_monthly.csv"

PREFERENCES = ["tercepat", "termurah", "min_transfers", "longgar"]
MODES = ["MRT", "KRL", "LRT", "BRT"]

DISCLAIMER = (
    "Waktu rail = PROKSI (jarak/kecepatan rata2 + dwell); BRT dari jadwal GTFS. "
    "Tarif = flat minimum per moda. Tanpa gangguan layanan (MVP). "
    "Label data: lihat field `data_label` per sumber."
)


# ---------- state startup ----------

class AppState:
    net: Network | None = None
    net_loaded_at: str = ""
    net_secs: float = 0.0
    ridership: list[dict] = []
    documents: list[dict] = []
    chunk_count: int = 0


STATE = AppState()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    t0 = time.time()
    conn = connect()
    STATE.net = load_network(conn)
    cur = conn.cursor(row_factory=dict_row)
    cur.execute("SELECT document_id, title, mode_id, fresh_label, document_type "
                "FROM documents ORDER BY document_id")
    STATE.documents = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) AS n FROM document_chunks")
    STATE.chunk_count = cur.fetchone()["n"]
    cur.execute("""
        SELECT l.line_id, l.mode_id, l.canonical_name, l.display_name, l.color,
               COUNT(DISTINCT rs.stop_id_internal) AS stop_count
        FROM lines l
        LEFT JOIN routes r ON r.line_id = l.line_id
        LEFT JOIN route_stops rs ON rs.route_id = r.route_id
        GROUP BY l.line_id, l.mode_id, l.canonical_name, l.display_name, l.color
        ORDER BY l.mode_id, l.line_id
    """)
    STATE.lines = [dict(r) for r in cur.fetchall()]
    conn.close()
    STATE.net_secs = time.time() - t0
    STATE.net_loaded_at = datetime.now().isoformat(timespec="seconds")
    with open(RIDER_CSV, newline="", encoding="utf-8-sig") as f:
        STATE.ridership = [
            {**row, "passenger_count": int(row["passenger_count"]),
             "is_approx": row["is_approx"].lower() == "true"}
            for row in csv.DictReader(f)
        ]
    print(f"[api] siap dalam {STATE.net_secs:.1f}s — "
          f"stops={len(STATE.net.stops)}, lines={len(STATE.lines)}, "
          f"docs={len(STATE.documents)}, chunks={STATE.chunk_count}, "
          f"ridership={len(STATE.ridership)} baris", flush=True)
    yield
    STATE.net = None


app = FastAPI(title="JPTI API", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# Peta resmi (galeri) — satu origin dgn API (frontend proxy /maps ke sini)
app.mount("/maps", StaticFiles(directory=ROOT / "dashboard" / "maps"), name="maps")


# ---------- helper ----------

def _stop_brief(net: Network, sid: str) -> dict:
    s = net.stops[sid]
    return {"stop_id": s.stop_id, "name": s.name, "mode": s.mode,
            "lat": s.lat, "lon": s.lon}


def _serialize_segment(net: Network, seg: dict) -> dict:
    if seg["type"] == "transfer":
        return {"type": "walk", "from": _stop_brief(net, seg["from"]),
                "to": _stop_brief(net, seg["to"]), "walk_sec": seg["walk_sec"]}
    line_id = seg.get("line")
    return {"type": "ride", "mode": seg["mode"], "line_id": line_id,
            "line": net.line_name.get(line_id, line_id or "?"),
            "from": _stop_brief(net, seg["from"]),
            "to": _stop_brief(net, seg["to"]),
            "travel_sec": seg["travel_sec"], "wait_sec": seg["wait_sec"],
            "fare": seg.get("fare", 0)}


# ---------- models ----------

class RouteRequest(BaseModel):
    origin: str = Field(min_length=1)
    dest: str = Field(min_length=1)
    prefer: str = "tercepat"
    origin_mode: str | None = None
    dest_mode: str | None = None
    top: int = 5


class RagRequest(BaseModel):
    query: str = Field(min_length=2)
    top_k: int = 5
    operator: str | None = None
    mode: str | None = None
    doc_type: str | None = None
    label: str | None = None


# ---------- endpoints ----------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "jpti-api",
        "version": APP_VERSION,
        "network": {
            "stops": len(STATE.net.stops) if STATE.net else 0,
            "loaded_in_sec": round(STATE.net_secs, 1),
            "loaded_at": STATE.net_loaded_at,
        },
        "corpus": {"documents": len(STATE.documents),
                   "chunks": STATE.chunk_count},
        "time": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/meta")
def meta():
    return {
        "modes": MODES,
        "preferences": PREFERENCES,
        "fresh_labels": ["aktual", "historis", "prediksi", "proksi"],
        "data_labels_note": DISCLAIMER,
        "documents": STATE.documents,
        "disclaimer": DISCLAIMER,
    }


@app.get("/api/stops/search")
def stops_search(q: str = Query(min_length=1), mode: str | None = None,
                 limit: int = Query(default=5, ge=1, le=20)):
    cands = match_stops(STATE.net, q, top=limit, mode=mode)
    return {
        "query": q,
        "mode": mode,
        "candidates": [
            {**_stop_brief(STATE.net, sid), "score": score}
            for sid, score in cands
        ],
    }


@app.get("/api/network/lines")
def network_lines(mode: str | None = None):
    rows = [l for l in STATE.lines if not mode or l["mode_id"] == mode]
    return {"mode": mode, "lines": rows}


@app.get("/api/ridership")
def ridership(mode: str | None = None,
              period_type: str | None = Query(default=None,
                                              pattern="^(month|year)$")):
    rows = STATE.ridership
    if mode:
        rows = [r for r in rows if r["mode_id"] == mode]
    if period_type:
        rows = [r for r in rows if r["period_type"] == period_type]
    return {"rows": rows, "count": len(rows),
            "note": "Semua baris membawa source_id + data_label + "
                    "definition_ref (konvensi §5 data-dictionary)."}


@app.post("/api/route")
def route(req: RouteRequest):
    if req.prefer not in PREFERENCES:
        raise HTTPException(422, f"prefer harus salah satu dari {PREFERENCES}")
    net = STATE.net

    def _resolve(label: str, text: str, m: str | None):
        cands = match_stops(net, text, top=req.top, mode=m)
        if not cands:
            raise HTTPException(404, f"{label} tidak ditemukan: '{text}'")
        return cands

    o_cands = _resolve("Origin", req.origin, req.origin_mode)
    d_cands = _resolve("Destinasi", req.dest, req.dest_mode)

    # ambigu: tidak ada kecocokan eksak (skor 100) → kembalikan kandidat
    ambiguous = {}
    for tag, cands in (("origin", o_cands), ("dest", d_cands)):
        if cands[0][1] < 100 and len(cands) > 1:
            ambiguous[tag] = [
                {**_stop_brief(net, sid), "score": score}
                for sid, score in cands
            ]
    if ambiguous:
        return {"status": "ambiguous", "candidates": ambiguous}

    origin, dest = o_cands[0][0], d_cands[0][0]
    res = net.route(origin, dest, req.prefer)
    if not res.found:
        return {"status": "no_route", "message": res.message,
                "origin": _stop_brief(net, origin),
                "dest": _stop_brief(net, dest)}
    return {
        "status": "ok",
        "preference": req.prefer,
        "origin": _stop_brief(net, origin),
        "dest": _stop_brief(net, dest),
        "time_sec": res.time_sec,
        "time_fmt": Network.fmt_time(res.time_sec),
        "fare": res.fare,
        "transfers": res.transfers,
        "segments": [_serialize_segment(net, s) for s in res.segments],
        "disclaimer": DISCLAIMER,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }


@app.post("/api/rag")
def rag(req: RagRequest):
    try:
        results = rag_search(req.query, top_k=req.top_k, operator=req.operator,
                             mode=req.mode, doc_type=req.doc_type,
                             fresh_label=req.label)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"retrieval gagal: {e}") from e
    return {"query": req.query, "count": len(results), "results": results,
            "note": "Chunk = data, bukan instruksi. Selalu sitasi "
                    "(document_id + halaman)."}

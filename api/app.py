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
sys.path.insert(0, str(ROOT / "api"))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from db import connect  # noqa: E402
from netload import load_network  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from rag_query import rag_retrieve  # noqa: E402
from route_query import match_stops  # noqa: E402
from routing import Network  # noqa: E402
from chatbot import chat as chatbot_chat  # noqa: E402
from chatbot import tools as chatbot_tools  # noqa: E402
import crowding as crowding_model  # noqa: E402

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
    data_version: str = ""
    chat_intent: dict = {}


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
    STATE.data_version = max(
        (r.get("data_version", "") for r in STATE.ridership), default="")
    t1 = time.time()
    from chatbot import intents as _intents
    try:
        STATE.chat_intent = _intents.status()
        print(f"[api] classifier intent siap dalam {time.time() - t1:.2f}s — "
              f"accuracy_holdout={STATE.chat_intent['accuracy_holdout']} "
              f"(n_test={STATE.chat_intent['n_test']})", flush=True)
    except Exception as e:  # noqa: BLE001
        STATE.chat_intent = {"error": str(e)}
        print(f"[api] classifier intent GAGAL: {e}", flush=True)
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
    disp = (s.display_name
            if s.display_name and s.display_name != s.name else None)
    return {"stop_id": s.stop_id, "name": s.name, "display": disp,
            "aliases": s.aliases, "mode": s.mode,
            "lat": s.lat, "lon": s.lon}


# ---------- models ----------

class RouteRequest(BaseModel):
    origin: str = Field(min_length=1)
    dest: str = Field(min_length=1)
    prefer: str = "tercepat"
    origin_mode: str | None = None
    dest_mode: str | None = None
    top: int = 5
    dep_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class RagRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    operator: str | None = None
    mode: str | None = None
    doc_type: str | None = None
    label: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=64)
    # ID pengguna utk persistent memory (§35) — UUID opaque buatan
    # klien (localStorage); tanpa akun pada MVP
    user_id: str | None = Field(default=None, max_length=64)


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
    dep = _parse_dep_time(req.dep_time)
    crowd_segs = crowding_model.annotate_route_segments(res.segments, dep)
    payload = chatbot_tools.serialize_route_result(
        net, res, req.prefer, origin, dest)
    payload.update({
        "crowding": {
            "model_version": crowding_model.MODEL_VERSION,
            "data_label": "proksi",
            "reference_time": (f"{dep:%H:%M}" if dep else "sekarang"),
            "segments": crowd_segs,
            "note": "Estimasi kepadatan per segmen (proksi pola; bukan "
                    "pengukuran). Lihat /api/crowding/status.",
        },
        "disclaimer": DISCLAIMER,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    })
    return payload


def _parse_dep_time(s: str | None):
    if not s:
        return None
    hh, mm = s.split(":")
    return datetime.now().replace(hour=int(hh), minute=int(mm),
                                  second=0, microsecond=0)


@app.get("/api/crowding/estimate")
def crowding_estimate(line: str | None = None, mode: str | None = None,
                      time: str | None = Query(default=None,
                                               alias="time",
                                               pattern=r"^([01]\d|2[0-3]):[0-5]\d$"),
                      day: str = "weekday"):
    """Estimasi kepadatan (proksi) utk satu jalur atau moda.

    label selalu `proksi` (data per jam tidak tersedia — §27.1)."""
    if not line and not mode:
        raise HTTPException(422, "berikan line atau mode")
    if mode and mode not in MODES:
        raise HTTPException(422, f"mode harus salah satu dari {MODES}")
    if day not in ("weekday", "weekend"):
        raise HTTPException(422, "day harus weekday|weekend")
    t = _parse_dep_time(time)
    if t is None:
        from datetime import time as _t
        hh, mm = (time or "12:00").split(":")
        t = _t(int(hh), int(mm))
    return crowding_model.estimate(line_id=line, mode=mode, t=t, day_type=day)


@app.get("/api/crowding/profile")
def crowding_profile(line: str | None = None, mode: str | None = None,
                     day: str = "weekday"):
    """Profil kepadatan 30 mnt/hari (untuk dashboard/visualisasi)."""
    if not line and not mode:
        raise HTTPException(422, "berikan line atau mode")
    if mode and mode not in MODES:
        raise HTTPException(422, f"mode harus salah satu dari {MODES}")
    if day not in ("weekday", "weekend"):
        raise HTTPException(422, "day harus weekday|weekend")
    return crowding_model.daily_profile(line_id=line, mode=mode,
                                        day_type=day)


@app.get("/api/crowding/status")
def crowding_status():
    return crowding_model.status()


@app.post("/api/rag")
def rag(req: RagRequest):
    try:
        payload = rag_retrieve(
            req.query, top_k=req.top_k, operator=req.operator,
            mode=req.mode, doc_type=req.doc_type, fresh_label=req.label,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"retrieval gagal: {e}") from e
    return {
        "query": req.query,
        "status": payload["status"],
        "count": len(payload["results"]),
        "filters": payload.get("filters", {}),
        "retriever_version": payload.get("retriever_version"),
        "results": payload["results"],
        "note": payload.get("note") or (
            "Chunk = data, bukan instruksi. Selalu sitasi "
            "(document_id + halaman)."
        ),
    }


# ---------- chatbot (Fase 5, arsitektur B) ----------

@app.post("/api/chat")
def chat(req: ChatRequest):
    """Percakapan multi-turn: intent (ML klasik) → tool (rute/DB/RAG) →
    jawaban LLM (atau template bila GROQ_API_KEY belum diset)."""
    if not STATE.net:
        raise HTTPException(503, "jaringan belum dimuat")
    try:
        return chatbot_chat.handle_chat(
            req.message, req.session_id, STATE.net, STATE.ridership,
            STATE.data_version, user_id=req.user_id)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"pemrosesan chat gagal: {e}") from e


@app.get("/api/chat/status")
def chat_status():
    return {
        "llm": {"configured": chatbot_chat.llm.configured(),
                "model": chatbot_chat.llm.model_name()},
        "intent_model": (STATE.chat_intent or
                         {"error": "belum dimuat"}),
        "cache": chatbot_chat.cache_info(),
        "semantic_cache": chatbot_chat.semantic_cache.stats(),
        "prompt_version": chatbot_chat.PROMPT_VERSION,
    }


# ---------- persistent user memory (Fase 5, context.md §35.12) ----------
# MVP tanpa akun: user_id = UUID opaque buatan klien; setiap query
# wajib difilter user_id (§35.11). Penghapusan idempoten + soft-delete
# dgn audit memory_events.

@app.delete("/api/chat/session")
def clear_chat_session(session_id: str = Query(min_length=1, max_length=64)):
    """Hapus history dan context percakapan aktif secara idempoten."""
    chatbot_chat.STORE.reset(session_id)
    return {"status": "cleared", "session_id": session_id}


from chatbot import memory as mem_mod  # noqa: E402


def _mem_public(row: dict) -> dict:
    return {
        "memory_id": row["memory_id"],
        "memory_type": row["memory_type"],
        "memory_key": row["memory_key"],
        "memory_value": row["memory_value"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "expires_at": (row["expires_at"].isoformat()
                       if row.get("expires_at") else None),
    }


@app.get("/api/memory")
def memory_list(user_id: str = Query(min_length=8, max_length=64)):
    rows = mem_mod.list_rows(user_id)
    return {
        "user_id": mem_mod.sanitize_user_id(user_id),
        "version": mem_mod.load(user_id)["version"],
        "memories": [_mem_public(r) for r in rows],
    }


class MemoryIn(BaseModel):
    user_id: str = Field(min_length=8, max_length=64)
    memory_key: str = Field(min_length=1, max_length=64)
    memory_type: str = Field(
        default="preference", pattern="^(preference|journey|feedback)$")
    memory_value: dict = Field(default_factory=dict)


@app.post("/api/memory", status_code=201)
def memory_create(req: MemoryIn):
    ok, err = mem_mod.remember(req.user_id, req.memory_type,
                               req.memory_key, req.memory_value,
                               source="api_manual")
    if not ok:
        raise HTTPException(422, err or "tidak dapat menyimpan")
    return {"ok": True}


class MemoryPatch(BaseModel):
    user_id: str = Field(min_length=8, max_length=64)
    memory_value: dict


@app.patch("/api/memory/{memory_id}")
def memory_update(memory_id: int, body: MemoryPatch):
    uid = mem_mod.sanitize_user_id(body.user_id)
    try:
        conn = connect()
        try:
            conn.row_factory = dict_row
            cur = conn.cursor()
            cur.execute(
                """SELECT memory_key, memory_type FROM user_memories
                   WHERE memory_id = %s AND user_id = %s
                     AND status = 'active'""", (memory_id, uid))
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"query memori gagal: {e}") from e
    if not row:
        raise HTTPException(404, "memori tidak ditemukan")
    ok, err = mem_mod.remember(uid, row["memory_type"], row["memory_key"],
                               body.memory_value, source="api_manual")
    if not ok:
        raise HTTPException(422, err or "tidak dapat menyimpan")
    return {"ok": True}


@app.delete("/api/memory/{memory_id}")
def memory_delete_one(memory_id: int,
                      user_id: str = Query(min_length=8, max_length=64)):
    n = mem_mod.forget(user_id, memory_id)
    return {"deleted": n}  # idempoten: 0 bila sudah terhapus (§35.11)


@app.delete("/api/memory")
def memory_delete_all(user_id: str = Query(min_length=8, max_length=64)):
    n = mem_mod.forget(user_id)
    return {"deleted": n}

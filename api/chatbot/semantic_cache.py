# -*- coding: utf-8 -*-
"""Semantic-response cache — context.md §11.2-B (Fase 5, §29).

Dipasang SETELAH exact cache & tool cache terbukti benar (§29).
Pertanyaan yang berbeda redaksional tetapi bermaksud & berparameter
sama tidak dihitung ulang.

KEAMANAN (probe 1 Okt 2026, `.work/probe_semantic_sim.py`):
embedding MINLM-L12 multilingual TIDAK memisahkan arah — pasangan
"rute A→B" vs "rute B→A" = 0.996 (hampir identik!) dan paraphrase
berparameter sama (0.58–0.90) berolapan dengan parameter beda
(0.55–0.81). Karena itu keputusan hit WAJIB melewati hard filter
struktur §11.2-B (match persis per field):

    intent + prompt_version + data_version   (filter query DB)
    mode, origin, dest, time, day_type       (filter Python, persis)

baru kemudian ambang embedding konservatif (0.65) sebagai sinyal
lunak. Meleset (miss) hanya berarti hitung ulang — aman; salah hit
menyasar — dicegah filter.

Jawaban personal (pengguna punya persistent memory, §35.9) TIDAK
boleh melewati cache ini: pemanggil wajib cek sebelum lookup.

Gagal (DB/embedding/model) tidak pernah menjatuhkan chat: semua
kesalahan → None (miss) + log sekali.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines"))
from db import connect, load_env  # noqa: E402

THRESHOLD = 0.65        # konservatif: gap probe tidak bersih (lihat atas)
DEDUP_THRESHOLD = 0.97  # entry baru ~identik dgn yang ada → jangan duplikat
CANDIDATE_LIMIT = 100   # skala MVP: jumlah entri per (versi, intent) kecil

# field hard filter §11.2-B (moda, asal, tujuan, arah, time bucket,
# kelompok hari). "Arah" tersirat: origin != dest harus match persis
# per field, sehingga A→B tidak cocok dgn B→A.
HARD_FIELDS = ("mode", "origin", "dest", "time", "day_type")

_model_lock = threading.Lock()
_fail_logged = False


def _err(e: Exception) -> None:
    global _fail_logged
    if not _fail_logged:
        print(f"[semantic-cache] {e.__class__.__name__}: {e} — "
              f"dioperasikan sebagai miss", flush=True)
        _fail_logged = True


def enabled() -> bool:
    """Bisa dimatikan via env SEMANTIC_CACHE=0 (jika evaluasi §24
    menemukan false hit)."""
    return load_env().get("SEMANTIC_CACHE", "1").strip() != "0"


def _embed(text: str):
    from rag_query import Embedder  # model sama dgn RAG (lazy, singleton)
    return Embedder.embed_one(text)


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def hard_filter_compatible(hint: dict, stored: dict) -> bool:
    """§11.2-B: setiap field hard filter harus SAMA PERSIS.

    ``hint`` = slot deterministik (regex) dari pertanyaan BARU;
    ``stored`` = slot LLM saat entry dihitung pertama. Bila salah satu
    pihak tidak menyebut field itu, entry TIDAK dipakai (konservatif —
    pertanyaan tanpa OD tidak boleh memakai cache pertanyaan ber-OD).
    """
    for f in HARD_FIELDS:
        if _norm(hint.get(f)) != _norm(stored.get(f)):
            return False
    return True


def _query(prompt_version: str, data_version: str, intent: str) -> list[dict]:
    conn = connect()
    try:
        conn.row_factory = __import__("psycopg").rows.dict_row
        cur = conn.cursor()
        cur.execute(
            """SELECT id, question_norm, question_embedding, slots, payload
               FROM chat_semantic_cache
               WHERE prompt_version = %s AND data_version = %s
                 AND intent = %s
               ORDER BY created_at DESC LIMIT %s""",
            (prompt_version, data_version, intent, CANDIDATE_LIMIT))
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    for r in rows:
        r["slots"] = r["slots"] if isinstance(r["slots"], dict) \
            else json.loads(r["slots"] or "{}")
        r["payload"] = r["payload"] if isinstance(r["payload"], dict) \
            else json.loads(r["payload"] or "{}")
    return rows


def lookup(intent: str, question: str, hint: dict, data_version: str,
           prompt_version: str) -> dict | None:
    """Kembalikan payload tersimpan bila ada entri yang bermakna sama
    (hard filter lolos + embedding ≥ THRESHOLD), selain itu None."""
    if not enabled() or not data_version or intent == "other":
        return None
    try:
        import numpy as np
        qv = _embed(question)
        rows = _query(prompt_version, data_version, intent)
    except Exception as e:  # noqa: BLE001
        _err(e)
        return None
    best: dict | None = None
    best_sim = 0.0
    best_id = 0
    for r in rows:
        emb = r.get("question_embedding") or []
        if not emb or not hard_filter_compatible(hint, r["slots"]):
            continue
        a, b = qv, np.asarray(emb, dtype="float64")
        sim = float(np.dot(a, b) /
                    (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        if sim >= THRESHOLD and sim > best_sim:
            best, best_sim, best_id = r, sim, r["id"]
    if best is None:
        return None
    try:
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE chat_semantic_cache "
                    "SET hits = hits + 1, last_hit_at = now() "
                    "WHERE id = %s", (best_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        _err(e)
    out = dict(best["payload"])
    out["semantic_sim"] = round(best_sim, 4)
    return out


def store(intent: str, question: str, slots: dict, payload: dict,
          data_version: str, prompt_version: str) -> None:
    """Simpan hasil perhitungan baru (dipanggil hanya utk jawaban
    non-ambigu, sama seperti exact cache). Entry ~identik (≥
    DEDUP_THRESHOLD, hard filter lolos) tidak diduplikasi."""
    if not enabled() or not data_version or intent == "other":
        return
    try:
        qv = _embed(question)
        import numpy as np
        rows = _query(prompt_version, data_version, intent)
        for r in rows:
            if not hard_filter_compatible(slots, r["slots"]):
                continue
            emb = r.get("question_embedding") or []
            if not emb:
                continue
            a, b = qv, np.asarray(emb, dtype="float64")
            sim = float(np.dot(a, b) /
                        (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
            if sim >= DEDUP_THRESHOLD:
                return  # sudah ada entry ekuivalen
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO chat_semantic_cache
                       (prompt_version, data_version, intent, question_norm,
                        question_embedding, slots, payload)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (prompt_version, data_version, intent,
                     question.strip()[:500], qv.tolist(),
                     json.dumps(slots, ensure_ascii=False),
                     json.dumps(payload, ensure_ascii=False)))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        _err(e)


def stats() -> dict:
    """Jumlah entri per (prompt_version, data_version) utk status."""
    out: dict = {}
    try:
        conn = connect()
        try:
            conn.row_factory = __import__("psycopg").rows.dict_row
            cur = conn.cursor()
            cur.execute(
                """SELECT prompt_version, data_version, intent,
                          count(*) AS n, sum(hits) AS hits
                   FROM chat_semantic_cache
                   GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""")
            for r in cur.fetchall():
                key = f"{r['prompt_version']}|{r['data_version']}"
                out.setdefault(key, {"entries": 0, "hits": 0, "intents": {}})
                out[key]["entries"] += int(r["n"])
                out[key]["hits"] += int(r["hits"] or 0)
                out[key]["intents"][r["intent"]] = int(r["n"])
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        _err(e)
    return {"enabled": enabled(), "threshold": THRESHOLD, "by_version": out}


def flush() -> int:
    """Maintenance: hapus semua entri (mis. pasca audit kualitas)."""
    n = 0
    try:
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chat_semantic_cache")
                n = cur.rowcount
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        _err(e)
    return n

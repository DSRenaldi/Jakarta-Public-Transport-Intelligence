# -*- coding: utf-8 -*-
"""Persistent user memory chatbot JPTI — context.md §35 (Fase 5).

Penyimpanan kanonik: PostgreSQL (`user_memories` + `memory_events`,
migration 0007; §35.4 — Redis BUKAN penyimpanan persisten).
`user_id` = UUID opaque yang dibuat klien (localStorage browser) —
MVP tanpa akun: isolasi per user_id, bukan identitas terverifikasi
(batasan §35.11 terdokumentasi).

Cakupan MVP (1 Okt 2026):
- Jenis: preferensi eksplisit (`preference`), rute rutin (`journey`,
  teks asal/tujuan, expiry 90 hari), umpan balik (`feedback`, 30 hari).
- Perintah (§35.8): ingat / apa yang kamu ingat / lupakan / hapus semua
  — diekstrak DETERMINISTIK (tanpa LLM) utk kosakata preferensi yang
  dikenal; tak dikenal → klarifikasi (tidak menyimpan yang tak jelas).
- Retrieval (§35.7): preferensi relevan dipakai sebagai parameter
  terstruktur (preferensi default route_planning bila pengguna tidak
  menyebut) + blok `<Preferensi pengguna>` di prompt LLM.
- Dilarang (§35.3): nomor kartu (13–19 digit), kredensial/token/PIN,
  rekening, kontak pribadi → DITOLAK + event audit (isi tak dilog).
- Version: `version` = max(updated_at) memori aktif → dimasukkan ke
  key exact cache sehingga memori berubah = hitung ulang jawaban
  (§35.9). Jawaban personal (memori aktif) TIDAK melewati semantic
  cache global (§35.9).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines"))
from db import connect  # noqa: E402
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

# ---------- filter konten (§35.3) ----------

_CARD_RE = re.compile(r"\b\d{13,19}\b")
_FORBIDDEN_WORD_RE = re.compile(
    r"\b(password|kata\s+sandi|passphrase|api\s*key|token|pin\b|cvv|"
    r"nomor\s+kartu|kartu\s+kredit|nomor\s+rekening|rekening|"
    r"nomor\s+(?:hp|handphone|telepon)|nomor\s+email|@)\b", re.I)

_FORBIDDEN_LABEL = {
    "card": "nomor kartu pembayaran",
    "word": "informasi kredensial/kontak pribadi",
}


def _forbidden_reason(text: str) -> str | None:
    if _CARD_RE.search(text):
        return "card"
    if _FORBIDDEN_WORD_RE.search(text):
        return "word"
    return None


def _event(memory_id, user_id: str, event_type: str,
           reason: str | None = None) -> None:
    try:
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO memory_events
                       (memory_id, user_id, event_type, actor, reason)
                       VALUES (%s, %s, %s, 'user', %s)""",
                    (memory_id, user_id, event_type, reason))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — audit tak boleh jatuhkan alur
        print(f"[memory] event gagal: {e}", flush=True)


# ---------- sanitasi ----------

def sanitize_user_id(user_id: str | None) -> str | None:
    uid = re.sub(r"[^A-Za-z0-9_-]", "", (user_id or "").strip())[:64]
    return uid or None


# ---------- retrieval (§35.7) ----------

def load(user_id: str | None) -> dict:
    """Muat memori aktif pengguna. Versi = max(updated_at) epoch —
    dipakai utk key cache (§35.9)."""
    out = {"active": False, "version": 0, "prefs": {}, "journeys": [],
           "n_active": 0}
    uid = sanitize_user_id(user_id)
    if not uid:
        return out
    try:
        conn = connect()
        try:
            conn.row_factory = dict_row
            cur = conn.cursor()
            cur.execute(
                """SELECT memory_key, memory_value, memory_type, updated_at
                   FROM user_memories
                   WHERE user_id = %s AND status = 'active'
                     AND (expires_at IS NULL OR expires_at > now())
                   ORDER BY updated_at DESC""", (uid,))
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"[memory] load gagal: {e}", flush=True)
        return out
    if not rows:
        return out
    out["active"] = True
    out["n_active"] = len(rows)
    version = 0
    for r in rows:
        ts = r["updated_at"]
        version = max(version, int(ts.timestamp() * 1_000_000)
                      if isinstance(ts, datetime) else int(ts))
        v = r["memory_value"]
        if isinstance(v, str):
            v = json.loads(v or "{}")
        k = r["memory_key"]
        if r["memory_type"] == "journey":
            out["journeys"].append(v)
        elif k in ("optimization", "preferred_mode", "max_walking_minutes"):
            out["prefs"][k] = v.get("value")
    out["version"] = version
    return out


def _prompt_label_opt(v: str) -> str:
    return {"tercepat": "tercepat", "termurah": "termurah",
            "min_transfers": "minim transit",
            "longgar": "longgar/sepi"}.get(v, v)


def prompt_block(mem: dict) -> str:
    """Blok utk prompt LLM — hanya preferensi relevan (§35.7)."""
    if not mem.get("active"):
        return ""
    lines = []
    p = mem.get("prefs", {})
    if p.get("optimization"):
        lines.append(f"- optimasi rute: "
                     f"{_prompt_label_opt(p['optimization'])} "
                     f"(preferensi tersimpan)")
    if p.get("preferred_mode"):
        lines.append(f"- moda favorit: {p['preferred_mode']}")
    if p.get("max_walking_minutes"):
        lines.append(f"- batas berjalan kaki: "
                     f"{p['max_walking_minutes']} menit")
    if mem.get("journeys"):
        js = ", ".join(f"{j.get('origin', '?')}→{j.get('dest', '?')}"
                       for j in mem["journeys"][:3])
        lines.append(f"- rute rutin: {js}")
    if not lines:
        return ""
    return ("<Preferensi pengguna (tersimpan; pakai bila relevan, dan "
            "sebutkan bahwa itu preferensi tersimpan bila memengaruhi "
            "jawaban)>\n" + "\n".join(lines) + "\n</Preferensi pengguna>")


# ---------- penulisan (§35.6) ----------

_EXPIRY_DAYS = {"journey": 90, "feedback": 30, "preference": None}


def remember(user_id: str, memory_type: str, memory_key: str, value: dict,
             source: str = "chat_explicit") -> tuple[bool, str]:
    """Simpan/perbarui memori (upsert per user+key; versioning §35.6:
    memori baru MENGGANTI nilai lama utk key sama, event tercatat)."""
    uid = sanitize_user_id(user_id)
    if not uid:
        return False, "Identitas sesi tidak valid."
    if memory_type not in ("preference", "journey", "feedback"):
        return False, "Jenis memori tidak dikenal."
    blob = json.dumps(value, ensure_ascii=False)
    reason = _forbidden_reason(f"{memory_key} {blob}")
    if reason:
        _event(None, uid, "reject",
               f"isi ditolak: {_FORBIDDEN_LABEL[reason]}")
        return False, (f"Maaf, saya tidak menyimpan "
                       f"{_FORBIDDEN_LABEL[reason]} — hanya preferensi "
                       "perjalanan yang Anda minta simpan. Data seperti "
                       "itu tidak perlu untuk rekomendasi.")
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=_EXPIRY_DAYS[memory_type])
               if _EXPIRY_DAYS[memory_type] else None)
    conn = connect()
    try:
        conn.row_factory = dict_row
        with conn.cursor() as cur:
            cur.execute(
                """SELECT memory_id, status, version FROM user_memories
                   WHERE user_id = %s AND memory_key = %s""",
                (uid, memory_key))
            row = cur.fetchone()
            if row:
                cur.execute(
                    """UPDATE user_memories
                       SET memory_value = %s, memory_type = %s,
                           status = 'active', updated_at = now(),
                           expires_at = %s, source = %s,
                           version = version + 1
                       WHERE memory_id = %s""",
                    (json.dumps(value, ensure_ascii=False), memory_type,
                     expires, source, row["memory_id"]))
                kind = "update"
                mid = row["memory_id"]
            else:
                cur.execute(
                    """INSERT INTO user_memories
                       (user_id, memory_type, memory_key, memory_value,
                        source, expires_at)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING memory_id""",
                    (uid, memory_type, memory_key,
                     json.dumps(value, ensure_ascii=False), source, expires))
                mid = cur.fetchone()["memory_id"]
                kind = "create"
        conn.commit()
    finally:
        conn.close()
    _event(mid, uid, kind, f"key={memory_key}")
    return True, None


def forget(user_id: str, memory_id: int | None = None) -> int:
    """Hapus satu memori (id) atau seluruh memori aktif (id=None).
    Idempoten (§35.11); soft-delete + event."""
    uid = sanitize_user_id(user_id)
    if not uid:
        return 0
    conn = connect()
    n = 0
    try:
        conn.row_factory = dict_row
        with conn.cursor() as cur:
            if memory_id is None:
                cur.execute(
                    """UPDATE user_memories SET status = 'deleted',
                       updated_at = now()
                       WHERE user_id = %s AND status = 'active'""", (uid,))
                n = cur.rowcount
                if n:
                    _event(None, uid, "delete_all", f"{n} memori")
            else:
                cur.execute(
                    """UPDATE user_memories SET status = 'deleted',
                       updated_at = now()
                       WHERE user_id = %s AND memory_id = %s
                         AND status = 'active'""", (uid, memory_id))
                n = cur.rowcount
                if n:
                    _event(memory_id, uid, "delete")
        conn.commit()
    finally:
        conn.close()
    return n


def list_rows(user_id: str) -> list[dict]:
    """Daftar memori aktif (untuk UI & perintah list)."""
    uid = sanitize_user_id(user_id)
    if not uid:
        return []
    try:
        conn = connect()
        try:
            conn.row_factory = dict_row
            cur = conn.cursor()
            cur.execute(
                """SELECT memory_id, memory_type, memory_key, memory_value,
                          created_at, updated_at, expires_at
                   FROM user_memories
                   WHERE user_id = %s AND status = 'active'
                     AND (expires_at IS NULL OR expires_at > now())
                   ORDER BY updated_at DESC""", (uid,))
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        for r in rows:
            if isinstance(r["memory_value"], str):
                r["memory_value"] = json.loads(r["memory_value"] or "{}")
            _event(r["memory_id"], uid, "retrieve")
        return rows
    except Exception as e:  # noqa: BLE001
        print(f"[memory] list gagal: {e}", flush=True)
        return []


# ---------- perintah chat (§35.8) ----------

_OPT_PATTERNS = [
    (re.compile(r"minim\s+transit|sedikit\s+transit|minim\s+transfer|"
                r"transfer\s+sedikit|paling\s+sedikit\s+transit|"
                r"min\s+transit", re.I), "min_transfers"),
    (re.compile(r"termurah|paling\s+murah|\bmurah\b", re.I), "termurah"),
    (re.compile(r"tercepat|paling\s+cepat|\bcepat\b", re.I), "tercepat"),
    (re.compile(r"longgar|\bsepi\b|tidak\s+ramai|jarang\s+ramai|"
                r"tidak\s+padat", re.I), "longgar"),
]
_MODE_PATTERNS = [
    (re.compile(r"\bkrl\b|commuter", re.I), "KRL"),
    (re.compile(r"\bmrt\b", re.I), "MRT"),
    (re.compile(r"lrt\s+jakarta|lrt\s+loop", re.I), "LRT"),
    (re.compile(r"lrt\s+jabodebek|jabodebek", re.I), "LRT"),
    (re.compile(r"trans\s?jakarta|\bbrt\b|busway", re.I), "BRT"),
]
_WALK_RE = re.compile(
    r"berjalan\s+kaki\s+(?:maksimal|maks|paling\s+lama|<|≤)?\s*(\d{1,2})"
    r"\s*menit", re.I)
_JOURNEY_RE = re.compile(
    r"rute\s+(?:saya\s+)?(?:dari|ke)\s+(?P<o>[A-Za-z0-9 .&'-]{2,40}?)\s+"
    r"(?:ke|menuju|dan)\s+(?P<d>[A-Za-z0-9 .&'-]{2,40})", re.I)


def _extract_preference(text: str) -> list[tuple[str, str, dict]]:
    """Ekstraksi deterministik: [(memory_key, type, value), ...]."""
    out = []
    for rx, val in _OPT_PATTERNS:
        if rx.search(text):
            out.append(("optimization", "preference", {"value": val}))
            break
    for rx, val in _MODE_PATTERNS:
        if rx.search(text):
            out.append(("preferred_mode", "preference", {"value": val}))
            break
    m = _WALK_RE.search(text)
    if m:
        out.append(("max_walking_minutes", "preference",
                    {"value": int(m.group(1))}))
    jm = _JOURNEY_RE.search(text)
    if jm:
        o, d = jm.group("o").strip(), jm.group("d").strip()
        if o and d and o.lower() != d.lower():
            out.append((f"journey:{o}→{d}", "journey",
                        {"origin": o, "dest": d}))
    return out


def parse_command(text: str) -> dict | None:
    t = text.lower().strip()
    # urutan penting: hapus/lupakan DIDULU — "lupakan preferensi saya"
    # memuat frasa list ("preferensi saya") tapi maksudnya hapus
    if re.search(r"\bhapus semua (memori|preferensi)\b", t) \
            or re.search(r"\blupakan semua\b", t):
        return {"kind": "forget_all"}
    if re.search(r"\bjangan simpan\b", t):
        return {"kind": "no_save"}
    if re.search(r"\blupakan\b(?! semua)", t) \
            or re.search(r"\bhapus (memori|preferensi)\b(?! semua)", t):
        return {"kind": "forget_one", "text": text}
    if re.search(r"\b(?:apa|apakah)\b.{0,40}\b(kamu|anda)\b.{0,25}\bingat\b",
                 t) \
            or re.search(r"\b(apa saja|apa yang|memori apa|preferensi apa)"
                         r".{0,25}\b(simpan|ingat|tersimpan)\b", t) \
            or re.search(r"\bapa yang tersimpan\b", t) \
            or re.search(r"\bpreferensi (saya|yang tersimpan)\b", t):
        return {"kind": "list"}
    if (re.search(r"\bingat\b", t) and
            re.search(r"\b(bahwa|saya|selalu|simpan)\b", t)) \
            or re.search(r"\bjangan lupa\b", t):
        return {"kind": "remember", "text": text}
    return None


def _describe(key: str, value: dict) -> str:
    v = value.get("value") if isinstance(value, dict) else value
    if key == "optimization":
        return f"preferensi rute: {_prompt_label_opt(str(v))}"
    if key == "preferred_mode":
        return f"moda favorit: {v}"
    if key == "max_walking_minutes":
        return f"batas berjalan kaki: {v} menit"
    if key.startswith("journey:"):
        return (f"rute rutin: {value.get('origin', '?')} → "
                f"{value.get('dest', '?')}")
    return f"{key}: {json.dumps(value, ensure_ascii=False)}"


def handle_command(cmd: dict, user_id: str) -> dict:
    """Eksekusi perintah memori; mengembalikan payload respons chat."""
    uid = sanitize_user_id(user_id)
    kind = cmd["kind"]
    if not uid:
        return {"reply": "Sesi ini belum punya identitas — coba lagi.",
                "intent": "memory"}
    if kind == "list":
        rows = list_rows(uid)
        if not rows:
            reply = ("Belum ada preferensi yang saya ingat tentang Anda. "
                     "Anda bisa minta, misal: \"ingat bahwa saya lebih suka "
                     "rute minim transit\" atau \"ingat rute saya dari "
                     "Bogor ke Jakarta Kota\".")
        else:
            lines = ["Yang saya ingat tentang preferensi perjalanan Anda:"]
            for r in rows:
                exp = ""
                if r.get("expires_at"):
                    exp = " (kedaluwarsa otomatis)"
                lines.append(f"- {_describe(r['memory_key'], r['memory_value'])}"
                             f"{exp}")
            lines.append("Ubah atau hapus kapan saja: \"lupakan ...\" / "
                         "\"hapus semua memori\".")
            reply = "\n".join(lines)
        return {"reply": reply, "intent": "memory"}
    if kind == "forget_all":
        n = forget(uid)
        reply = (f"Semua memori perjalanan Anda ({n} entri) telah dihapus."
                 if n else "Tidak ada memori yang perlu dihapus.")
        return {"reply": reply, "intent": "memory"}
    if kind == "no_save":
        return {"reply": ("Baik. Percakapan tidak disimpan permanen — hanya "
                          "preferensi yang secara eksplisit Anda minta simpan. "
                          "Itu pun bisa Anda hapus kapan saja."),
                "intent": "memory"}
    if kind == "remember":
        # konten terlarang (§35.3): tolak eksplisit SEBELUM ekstraksi —
        # nomor kartu/kredensial tidak pernah sampai ke penyimpanan
        reason = _forbidden_reason(cmd["text"])
        if reason:
            _event(None, uid, "reject",
                   f"isi ditolak: {_FORBIDDEN_LABEL[reason]}")
            return {"reply": (f"Maaf, saya tidak menyimpan "
                              f"{_FORBIDDEN_LABEL[reason]} — hanya "
                              "preferensi perjalanan yang Anda minta "
                              "simpan. Data seperti itu tidak perlu "
                              "untuk rekomendasi."),
                    "intent": "memory"}
        items = _extract_preference(cmd["text"])
        if not items:
            return {"reply": ("Bisa diperjelas preferensi apa yang ingin "
                              "saya ingat? Contoh: \"ingat bahwa saya lebih "
                              "suka rute minim transit\", \"ingat moda "
                              "favorit saya KRL\", atau \"ingat rute saya "
                              "dari Bogor ke Jakarta Kota\"."),
                    "intent": "memory"}
        saved = []
        for key, mtype, value in items:
            ok, err = remember(uid, mtype, key, value)
            if ok:
                saved.append(_describe(key, value))
            else:
                return {"reply": err or "Tidak dapat menyimpan.",
                        "intent": "memory"}
        return {"reply": "Saya akan mengingat: " + "; ".join(saved) +
                         ". (Bisa diubah/dihapus: \"lupakan ...\" atau "
                         "\"hapus semua memori\".)",
                "intent": "memory"}
    # forget_one
    text = cmd["text"]
    rows = list_rows(uid)
    targets = []
    for r in rows:
        k, v = r["memory_key"], r["memory_value"]
        if (k == "optimization" and
                any(rx.search(text) for rx, _ in _OPT_PATTERNS)) \
                or (k == "preferred_mode" and
                    any(rx.search(text) for rx, _ in _MODE_PATTERNS)) \
                or (k == "max_walking_minutes" and _WALK_RE.search(text)) \
                or (k.startswith("journey:") and
                    _JOURNEY_RE.search(text) and
                    _JOURNEY_RE.search(text).group("o").strip().lower()
                    in k.lower()):
            targets.append(r)
    if not targets:
        return {"reply": ("Saya tidak menemukan memori yang sesuai. "
                          "Memori yang tersimpan: "
                          + ("; ".join(_describe(r['memory_key'], r['memory_value'])
                                       for r in rows) or "tidak ada")
                          + "."),
                "intent": "memory"}
    if len(targets) > 1:
        opts = "; ".join(_describe(r["memory_key"], r["memory_value"])
                         for r in targets)
        return {"reply": f"Beberapa cocok — yang mana? {opts}",
                "intent": "memory"}
    r = targets[0]
    forget(uid, r["memory_id"])
    return {"reply": "Sudah saya lupakan: "
                     + _describe(r["memory_key"], r["memory_value"]) + ".",
            "intent": "memory"}

# -*- coding: utf-8 -*-
"""Session memory percakapan — konteks per session_id (context.md §11.2-D, §12).

Backend via ``cache_store.get_store()``: Redis (key ``jpti:session:{sid}``)
bila ``REDIS_URL`` diset, selain itu in-memory. TTL 60 menit, diperpanjang
setiap aktivitas (get_id/append); riwayat dipertahankan maks 12 pesan
(≈6 giliran) — cukup untuk konteks, bukan memori jangka panjang.

Selain teks history, record session menyimpan context terstruktur untuk
``pending_route`` (kandidat yang sedang diklarifikasi) dan ``last_route``
(asal/tujuan rute terakhir). State ini membuat jawaban seperti "4",
"berapa lama?", atau "pulang" dapat diproses tanpa menebak lewat LLM.

Catatan: ini BUKAN user memory permanen (§35) — tidak ada profil,
preferensi, atau data pribadi yang disimpan; konten hanya riwayat
pertanyaan-jawaban yang sudah melewati filter jawaban sistem.
"""
import re
import time
import uuid
from copy import deepcopy

from .cache_store import NS_SESSION, TTL_SESSION_SEC, get_store

MAX_MESSAGES = 12          # riwayat dibawa ke prompt (≈6 giliran)
_SID_RE = re.compile(r"[^A-Za-z0-9_-]")


class SessionStore:
    """Riwayat percakapan per session_id di backend cache_store."""

    def _key(self, sid: str) -> str:
        return f"{NS_SESSION}:{sid}"

    @staticmethod
    def _sanitize(sid: str) -> str:
        sid = _SID_RE.sub("", (sid or "").strip())[:64]
        return sid or uuid.uuid4().hex

    def get_id(self, session_id: str | None) -> str:
        sid = self._sanitize(session_id)
        store = get_store()
        key = self._key(sid)
        rec = store.get(key)
        if rec is None:
            rec = {"messages": [], "created": time.time()}
        store.set(key, rec, TTL_SESSION_SEC)   # buat / perpanjang TTL
        return sid

    def history(self, session_id: str) -> list[dict]:
        rec = get_store().get(self._key(self._sanitize(session_id)))
        if not rec:
            return []
        msgs = rec.get("messages") or []
        return [{"role": m["role"], "content": m["content"]}
                for m in msgs[-MAX_MESSAGES:]]

    def context(self, session_id: str) -> dict:
        """Ambil state percakapan terstruktur dan perpanjang TTL session."""
        store = get_store()
        key = self._key(self._sanitize(session_id))
        rec = store.get(key)
        if not rec:
            return {}
        store.set(key, rec, TTL_SESSION_SEC)
        return deepcopy(rec.get("context") or {})

    def set_context_value(self, session_id: str, name: str,
                          value: dict | None) -> None:
        """Simpan state terstruktur tanpa mencampurnya dengan teks history."""
        store = get_store()
        sid = self._sanitize(session_id)
        key = self._key(sid)
        rec = store.get(key) or {"messages": [], "created": time.time()}
        context = rec.setdefault("context", {})
        if value is None:
            context.pop(name, None)
        else:
            context[name] = deepcopy(value)
        store.set(key, rec, TTL_SESSION_SEC)

    def pending_route(self, session_id: str) -> dict | None:
        value = self.context(session_id).get("pending_route")
        return value if isinstance(value, dict) else None

    def set_pending_route(self, session_id: str,
                          value: dict | None) -> None:
        self.set_context_value(session_id, "pending_route", value)

    def route_context(self, session_id: str) -> dict | None:
        value = self.context(session_id).get("last_route")
        return value if isinstance(value, dict) else None

    def set_route_context(self, session_id: str,
                          value: dict | None) -> None:
        self.set_context_value(session_id, "last_route", value)

    def append(self, session_id: str, role: str, content: str) -> None:
        store = get_store()
        sid = self._sanitize(session_id)
        key = self._key(sid)
        rec = store.get(key) or {"messages": [], "created": time.time()}
        rec.setdefault("messages", []).append(
            {"role": role, "content": content})
        rec["messages"] = rec["messages"][-MAX_MESSAGES:]
        store.set(key, rec, TTL_SESSION_SEC)   # perpanjang TTL saat aktif

    def reset(self, session_id: str) -> None:
        get_store().delete(self._key(self._sanitize(session_id)))

    def count(self) -> int:
        """Jumlah session aktif (untuk /api/chat/status)."""
        return get_store().count(NS_SESSION)


STORE = SessionStore()

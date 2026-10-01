# -*- coding: utf-8 -*-
"""Session memory percakapan — konteks per session_id (context.md §11.2-D, §12).

Backend via ``cache_store.get_store()``: Redis (key ``jpti:session:{sid}``)
bila ``REDIS_URL`` diset, selain itu in-memory. TTL 60 menit, diperpanjang
setiap aktivitas (get_id/append); riwayat dipertahankan maks 12 pesan
(≈6 giliran) — cukup untuk konteks, bukan memori jangka panjang.

Catatan: ini BUKAN user memory permanen (§35) — tidak ada profil,
preferensi, atau data pribadi yang disimpan; konten hanya riwayat
pertanyaan-jawaban yang sudah melewati filter jawaban sistem.
"""
import re
import time
import uuid

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

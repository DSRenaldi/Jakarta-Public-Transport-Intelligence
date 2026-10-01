# -*- coding: utf-8 -*-
"""Session memory percakapan — in-memory (MVP).

Redis (namespace `session:*`) menyusul sesuai spesifikasi §11/§35;
di MVP konteks percakapan cukup disimpan per proses dengan TTL dan
batas panjang agar tidak bocor lintas pengguna (key = session_id yang
dibuat frontend, satu per browser).
"""
import threading
import time
import uuid

TTL_SEC = 60 * 60          # sesi aktif 60 menit (spec §11.5)
MAX_MESSAGES = 12          # riwayat dibawa ke prompt (≈6 giliran)


class SessionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}

    def _sweep(self, now: float):
        stale = [sid for sid, s in self._sessions.items()
                 if now - s["ts"] > TTL_SEC]
        for sid in stale:
            del self._sessions[sid]

    def get_id(self, session_id: str | None) -> str:
        sid = (session_id or "").strip()
        if not sid:
            sid = uuid.uuid4().hex
        with self._lock:
            now = time.time()
            self._sweep(now)
            if sid not in self._sessions:
                self._sessions[sid] = {"messages": [], "ts": now}
            self._sessions[sid]["ts"] = now
        return sid

    def history(self, session_id: str) -> list[dict]:
        with self._lock:
            s = self._sessions.get(session_id)
            return list(s["messages"][-MAX_MESSAGES:]) if s else []

    def append(self, session_id: str, role: str, content: str):
        with self._lock:
            s = self._sessions.setdefault(
                session_id, {"messages": [], "ts": time.time()})
            s["ts"] = time.time()
            s["messages"].append({"role": role, "content": content})
            del s["messages"][:-MAX_MESSAGES]

    def reset(self, session_id: str):
        with self._lock:
            self._sessions.pop(session_id, None)


STORE = SessionStore()

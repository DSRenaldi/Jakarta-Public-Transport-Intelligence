# -*- coding: utf-8 -*-
"""Lapisan penyimpanan cache & session chatbot — context.md §11.

Dua backend yang bisa ditukar:
- ``MemoryStore``  — dict per proses + TTL (perilaku MVP saat ini).
- ``RedisStore``   — Redis (namespace §11.3: ``jpti:cache:exact:*``,
  ``jpti:cache:tool:*``, ``jpti:cache:route:*``, ``jpti:cache:prediction:*``,
  ``jpti:session:*``, ``jpti:lock:*``).

Redis adalah cache, BUKAN sumber data (§11.1): semua entri boleh dihapus/
dibangun ulang. Backend dipilih dari env ``REDIS_URL`` (opsional, di .env):
ada → Redis (dengan pengecekan PING; bila gagal jatuh ke MemoryStore agar
situs tetap berfungsi), tidak ada → MemoryStore.

Single-flight lock (§11.6): lock singkat mencegah banyak proses menghitung
key yang sama secara bersamaan (cache stampede).

Catatan keamanan: kredensial tidak boleh dicetak ke log.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines"))
from db import load_env  # noqa: E402

KEY_PREFIX = "jpti"

# Namespace (§11.3) — rag:document:* sengaja TIDAK dipakai: indeks RAG
# tetap di Postgres (Redis bukan vector store di MVP; §26 keputusan
# vector store masih terbuka: Redis vs pgvector).
NS_EXACT = f"{KEY_PREFIX}:cache:exact"
NS_TOOL = f"{KEY_PREFIX}:cache:tool"
NS_ROUTE = f"{KEY_PREFIX}:cache:route"
NS_PREDICTION = f"{KEY_PREFIX}:cache:prediction"
NS_SESSION = f"{KEY_PREFIX}:session"
NS_LOCK = f"{KEY_PREFIX}:lock"

# TTL awal (§11.5) — nilai awal yang harus diuji; invalidasi berbasis
# versi dataset lebih penting daripada menunggu TTL (§11.5 akhir).
TTL_EXACT_SEC = 6 * 3600            # jawaban identik; key memuat
                                    # prompt_version + data_version sehingga
                                    # ingest baru menghasilkan key baru
TTL_RIDERSHIP_SEC = 12 * 3600       # statistik bulanan 6–24 jam
TTL_FARE_SCHEDULE_SEC = 12 * 3600   # tarif & jadwal reguler 1–24 jam
TTL_ROUTE_SEC = 2 * 3600            # hasil rute statis 1–6 jam
TTL_PREDICTION_SEC = 2 * 3600       # prediksi berbasis historis 1–6 jam
TTL_RAG_SEC = 24 * 3600             # retrieval dokumen historis 1–7 hari
TTL_SESSION_SEC = 60 * 60           # session 30–60 menit (diperpanjang saat aktif)
LOCK_TTL_SEC = 20                   # lock single-flight (§11.6)


class CacheStore:
    """Antarmuka backend (get/set dengan TTL, flush per namespace, lock)."""

    name = "base"

    def get(self, key: str) -> Any | None:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl_sec: int) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def count(self, namespace: str) -> int:
        raise NotImplementedError

    def flush(self, namespace: str) -> int:
        """Hapus seluruh key di namespace (invalidasi massal §11.6)."""
        raise NotImplementedError

    def acquire_lock(self, key: str, ttl_sec: int = LOCK_TTL_SEC) -> bool:
        raise NotImplementedError

    def release_lock(self, key: str) -> None:
        raise NotImplementedError

    def lock_held(self, key: str) -> bool:
        """Apakah lock masih dipegang (oleh proses/thread lain)."""
        raise NotImplementedError

    def health(self) -> str:
        raise NotImplementedError


# ---------- backend: memory ----------

class MemoryStore(CacheStore):
    """Per proses — perilaku MVP sebelum Redis. Aman untuk multi-thread."""

    name = "memory"

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, float] = {}

    def _sweep(self, now: float):
        stale = [k for k, (exp, _) in self._data.items() if exp < now]
        for k in stale:
            del self._data[k]
        for k in [k for k, exp in self._locks.items() if exp < now]:
            del self._locks[k]

    def get(self, key: str) -> Any | None:
        with self._lock:
            self._sweep(time.time())
            hit = self._data.get(key)
            return hit[1] if hit else None

    def set(self, key: str, value: Any, ttl_sec: int) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl_sec, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def count(self, namespace: str) -> int:
        with self._lock:
            now = time.time()
            return sum(1 for k, (exp, _) in self._data.items()
                       if k.startswith(namespace + ":") and exp >= now)

    def flush(self, namespace: str) -> int:
        with self._lock:
            now = time.time()
            stale = [k for k, (exp, _) in self._data.items()
                     if k.startswith(namespace + ":") and exp >= now]
            for k in stale:
                del self._data[k]
            return len(stale)

    def acquire_lock(self, key: str, ttl_sec: int = LOCK_TTL_SEC) -> bool:
        with self._lock:
            now = time.time()
            holder = self._locks.get(key)
            if holder is not None and holder >= now:
                return False
            self._locks[key] = now + ttl_sec
            return True

    def release_lock(self, key: str) -> None:
        with self._lock:
            self._locks.pop(key, None)

    def lock_held(self, key: str) -> bool:
        with self._lock:
            exp = self._locks.get(key)
            return exp is not None and exp >= time.time()

    def health(self) -> str:
        return "ok (in-memory)"


# ---------- backend: redis ----------

class RedisStore(CacheStore):
    """Redis via redis-py. Nilai di-serialize JSON (decode_responses=True).

    Kegagalan Redis saat runtime TIDAK menjatuhkan chatbot: get()
    mengembalikan None (cache miss) dan set() diabaikan — data tetap
    dihitung dari sumber (Redis hanyalah cache, §11.1).
    """

    name = "redis"

    def __init__(self, url: str):
        import redis  # import lokal: modul tidak wajib bila tak dipakai
        # protocol=2 (RESP2): server Redis 5.0 (build Windows dev) tidak
        # mendukung HELLO/RESP3 yang jadi default redis-py >= 8.
        self._redis = redis.Redis.from_url(
            url, decode_responses=True, protocol=2,
            socket_timeout=3.0,
            socket_connect_timeout=3.0)
        self._fail_logged = False

    def _err(self, e: Exception) -> None:
        if not self._fail_logged:
            print(f"[cache] Redis error ({e.__class__.__name__}); "
                  f"beroperasi tanpa cache", flush=True)
            self._fail_logged = True

    def get(self, key: str) -> Any | None:
        try:
            raw = self._redis.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception as e:  # noqa: BLE001
            self._err(e)
            return None

    def set(self, key: str, value: Any, ttl_sec: int) -> None:
        try:
            self._redis.set(key, json.dumps(value, ensure_ascii=False),
                            ex=ttl_sec)
        except Exception as e:  # noqa: BLE001
            self._err(e)

    def delete(self, key: str) -> None:
        try:
            self._redis.delete(key)
        except Exception as e:  # noqa: BLE001
            self._err(e)

    def count(self, namespace: str) -> int:
        try:
            n = 0
            for _ in self._redis.scan_iter(match=namespace + ":*",
                                           count=200):
                n += 1
            return n
        except Exception as e:  # noqa: BLE001
            self._err(e)
            return 0

    def flush(self, namespace: str) -> int:
        keys: list[str] = []
        try:
            for k in self._redis.scan_iter(match=namespace + ":*",
                                           count=200):
                keys.append(k)
            if keys:
                self._redis.delete(*keys)
        except Exception as e:  # noqa: BLE001
            self._err(e)
        return len(keys)

    def acquire_lock(self, key: str, ttl_sec: int = LOCK_TTL_SEC) -> bool:
        try:
            return bool(self._redis.set(key, "1", nx=True, ex=ttl_sec))
        except Exception as e:  # noqa: BLE001
            self._err(e)
            return True  # tanpa lock (fail-open) agar chat tetap jalan

    def release_lock(self, key: str) -> None:
        try:
            self._redis.delete(key)
        except Exception as e:  # noqa: BLE001
            self._err(e)

    def lock_held(self, key: str) -> bool:
        try:
            return bool(self._redis.exists(key))
        except Exception as e:  # noqa: BLE001
            self._err(e)
            return False

    def health(self) -> str:
        try:
            pong = self._redis.ping()
            if not pong:
                return "gagal PING"
            try:
                ver = self._redis.info("server")["redis_version"]
            except Exception:  # noqa: BLE001
                ver = "?"
            return f"ok (pong={pong}, server={ver})"
        except Exception as e:  # noqa: BLE001
            self._err(e)
            return f"gagal terhubung ({e.__class__.__name__})"


# ---------- factory ----------

_store: CacheStore | None = None
_store_lock = threading.Lock()


def _mask_url(url: str) -> str:
    if "@" in url and "//" in url:
        head, tail = url.split("//", 1)
        _, _, creds = tail.partition("@")
        if ":" in creds:
            user, _pw = creds.split(":", 1)
            return f"{head}//{user}:***@{tail.partition('@')[2]}"
    return url


def get_store(refresh: bool = False) -> CacheStore:
    """Backend aktif: REDIS_URL (jika diset & sehat) → Redis, selain itu
    MemoryStore. Hasil di-cache per proses."""
    global _store
    if _store is not None and not refresh:
        return _store
    with _store_lock:
        if _store is not None and not refresh:
            return _store
        url = load_env().get("REDIS_URL", "").strip()
        if url:
            try:
                cand = RedisStore(url)
                health = cand.health()
                if health.startswith("ok"):
                    _store = cand
                    print(f"[cache] backend: redis — {_mask_url(url)} "
                          f"({health})", flush=True)
                    return _store
                print(f"[cache] REDIS_URL diset tapi {health} — "
                      f"pakai memory", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[cache] gagal hubungkan Redis ({e}) — "
                      f"pakai memory", flush=True)
        _store = MemoryStore()
        print("[cache] backend: memory (REDIS_URL tidak diset)", flush=True)
        return _store


def invalidate_chatbot(data_version: str | None = None) -> dict:
    """Invalidasi seluruh cache chatbot (dipanggil bila pipeline ingest
    baru menghasilkan data_version baru; §11.6).

    Key exact memuat data_version sehingga entri lama takkan di-hit lagi;
    flush tetap dilakukan agar Redis tidak menumpuk key versi lama.
    """
    store = get_store()
    out = {ns: store.flush(ns) for ns in
           (NS_EXACT, NS_TOOL, NS_ROUTE, NS_PREDICTION)}
    out["backend"] = store.name
    if data_version:
        out["new_data_version"] = data_version
    return out

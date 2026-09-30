# -*- coding: utf-8 -*-
"""Helper koneksi DB (baca .env, tanpa hardcode kredensial)."""
import psycopg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path | None = None) -> dict:
    path = path or (ROOT / ".env")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def connect(db: str | None = None, autocommit: bool = False):
    env = load_env()
    conn = psycopg.connect(
        host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
        password=env["PGPASSWORD"], dbname=db or env["PGDATABASE"],
        connect_timeout=10,
    )
    if autocommit:
        conn.autocommit = True
    return conn

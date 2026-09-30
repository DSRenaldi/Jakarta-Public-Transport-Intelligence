# -*- coding: utf-8 -*-
"""Probe koneksi Postgres + PostGIS dari variabel .env (tanpa hardcode kredensial)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


env = load_env(ROOT / ".env")
import psycopg

maint = env.get("PGMAINTENANCE_DATABASE", "postgres")
conn = psycopg.connect(
    host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
    password=env["PGPASSWORD"], dbname=maint, connect_timeout=10,
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT version()")
print("server:", cur.fetchone()[0][:70])
cur.execute("SELECT datname FROM pg_database WHERE datname=%s", (env["PGDATABASE"],))
dbs = [r[0] for r in cur.fetchall()]
print("db target ada:", dbs == [env["PGDATABASE"]], "->", dbs)
if not dbs:
    cur.execute("CREATE DATABASE %s" % env["PGDATABASE"])
    print("db dibuat:", env["PGDATABASE"])
    conn.commit()
    conn.close()
    sys.exit(0)

conn.close()
conn = psycopg.connect(
    host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
    password=env["PGPASSWORD"], dbname=env["PGDATABASE"], connect_timeout=10,
)
conn.autocommit = True
cur = conn.cursor()
try:
    cur.execute("SELECT postgis_version()")
    print("postgis:", cur.fetchone()[0])
except Exception as e:
    print("postgis TIDAK ADA:", str(e).splitlines()[0][:140])
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cur.execute("SELECT postgis_version()")
        print("postgis setelah CREATE EXTENSION:", cur.fetchone()[0])
    except Exception as e2:
        print("CREATE EXTENSION GAGAL:", str(e2).splitlines()[0][:140])
cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
print("tabel di public:", cur.fetchone()[0])
conn.close()
print("OK")

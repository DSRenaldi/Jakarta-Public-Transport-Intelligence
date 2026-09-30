# -*- coding: utf-8 -*-
"""Cek ekstensi Postgres tersedia (vector, pg_trgm) + coba install bila perlu."""
import sys

import psycopg

conn = psycopg.connect(host="localhost", port=5432, user="postgres",
                       password="dicky", dbname="transum_jakarta")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT name, default_version FROM pg_available_extensions "
            "WHERE name IN ('vector','pg_trgm','postgis')")
print("tersedia:", cur.fetchall())
for ext in ("vector", "pg_trgm"):
    try:
        cur.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
        cur.execute(f"SELECT extversion FROM pg_extension WHERE extname='{ext}'")
        print(f"{ext}: AKTIF {cur.fetchone()[0]}")
    except Exception as e:
        print(f"{ext}: GAGAL {str(e).splitlines()[0][:120]}")
conn.close()

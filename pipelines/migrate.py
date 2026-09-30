# -*- coding: utf-8 -*-
"""Terapkan migration SQL berurutan dari db/migrations/."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MIG_DIR = ROOT / "db" / "migrations"


def main():
    conn = connect(autocommit=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name VARCHAR(64) PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("SELECT name FROM schema_migrations")
    applied = {r[0] for r in cur.fetchall()}
    files = sorted(MIG_DIR.glob("*.sql"))
    for f in files:
        if f.name in applied:
            print(f"== {f.name}: sudah diterapkan, lewati")
            continue
        print(f"== {f.name}: menerapkan...")
        sql = f.read_text(encoding="utf-8")
        cur.execute(sql)
        cur.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (f.name,))
        conn.commit()
        print(f"   OK")
    conn.close()
    print("Semua migration diterapkan.")


if __name__ == "__main__":
    main()

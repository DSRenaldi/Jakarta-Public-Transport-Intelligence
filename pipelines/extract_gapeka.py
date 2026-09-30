# -*- coding: utf-8 -*-
"""Ekstrak teks GAPEKA KRL (13 halaman) untuk membaca daftar stasiun per relasi."""
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "raw" / "krl" / "jadwal_gapeka_jabodetabek_update_feb2026.pdf"

reader = PdfReader(str(PDF))
out = ROOT / ".work" / "gapeka_text.txt"
out.parent.mkdir(exist_ok=True)
out.write_text("", encoding="utf-8")
for i, page in enumerate(reader.pages):
    text = page.extract_text() or ""
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"\n===== HALAMAN {i+1} =====\n{text}\n")
print(f"OK: {out} ({len(reader.pages)} halaman)")
# ringkas: tampilkan 3000 char pertama + 2000 char tengah
t = out.read_text(encoding="utf-8")
print(t[:2500])

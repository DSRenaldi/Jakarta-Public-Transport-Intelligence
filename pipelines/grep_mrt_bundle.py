# -*- coding: utf-8 -*-
"""Grep bundle MRT untuk path API (station/jadwal/line)."""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
h = Path(r"D:\Porto\analisis_mrt_jakarta\.work\mrt_index.js").read_text(encoding="utf-8")

pats = [
    r'''["']([^"']{0,40}/stations?[^"']{0,40})["']''',
    r'''["']([^"']{0,40}/jadwal[^"']{0,40})["']''',
    r'''["']([^"']{0,40}/lines?[^"']{0,40})["']''',
]
for p in pats:
    ms = re.findall(p, h)
    uniq = sorted({m for m in ms if len(m) < 80})
    print(f"== {len(uniq)} unik")
    for u in uniq[:30]:
        print("   ", u)

print("== konteks middleware ==")
for m in re.finditer(r"middleware", h):
    s = h[max(0, m.start() - 150): m.end() + 150]
    print("   ", re.sub(r"\s+", " ", s))

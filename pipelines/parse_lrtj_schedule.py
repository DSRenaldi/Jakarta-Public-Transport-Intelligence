# -*- coding: utf-8 -*-
"""Parsai JSON stasiun ter-embed di halaman /schedule LRT Jakarta."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / ".work" / "lrtj_schedule.html").read_text(encoding="utf-8")

# carilah semua objek stasiun: {"id":"...","name":"...","address":null,...,"relations":[...]}
pat = re.compile(r'\{"id":"([^"]+)","name":"([^"]+)","address":null[^{]*?"relations":\[(.*?)\]\}')
stations = {}
for m in pat.finditer(html):
    sid, name, rels = m.group(1), m.group(2), m.group(3)
    rel_names = re.findall(r'"name":"([^"]+)"', rels)
    stations[sid] = {"name": name, "relations": rel_names}

print(f"{len(stations)} stasiun ditemukan:\n")
for sid, s in stations.items():
    print(f"  {s['name']:<28} relations: {', '.join(s['relations'])}")

out = ROOT / ".work" / "lrtj_stations.json"
out.write_text(json.dumps(stations, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n-> {out}")

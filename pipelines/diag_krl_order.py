# -*- coding: utf-8 -*-
"""Tampilkan urutan nama node untuk relasi KRL utama (diagnostic)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
nodes = {n["id"]: n for n in
         json.loads((WORK / "osm_member_nodes.json").read_text(encoding="utf-8"))}

for rid in (16877211, 16877210, 2922163, 2922215, 2922235, 17193008, 17675694):
    f = WORK / f"osm_rel_{rid}.json"
    if not f.exists():
        print(f"== {rid}: tidak ada")
        continue
    data = json.loads(f.read_text(encoding="utf-8"))
    rel = next((e for e in data["elements"] if e["type"] == "relation"), None)
    print(f"== rel {rid} {rel.get('tags', {}).get('name')}")
    names = []
    for m in rel.get("members", []):
        if m["type"] != "node":
            continue
        n = nodes.get(m["ref"], {})
        nm = (n.get("tags") or {}).get("name")
        names.append(nm if nm else f"?{m['ref']}")
    print("   ", " -> ".join(names))
    print()

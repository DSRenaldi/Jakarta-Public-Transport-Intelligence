# -*- coding: utf-8 -*-
"""Diagnostic: nama node LRT Jabodebek + MRT + LRT Jakarta (urutan member)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
nodes = {n["id"]: n for n in
         json.loads((WORK / "osm_member_nodes.json").read_text(encoding="utf-8"))}

import glob
rels = {}
for f in sorted(glob.glob(str(WORK / "osm_rel_*.json"))):
    data = json.loads(Path(f).read_text(encoding="utf-8"))
    for e in data["elements"]:
        if e["type"] == "relation":
            rels[e["id"]] = e
print(f"{len(rels)} relasi di .work\n")
# tampilkan semua nama relasi dulu, lalu detail yang diminta
for rid, rel in rels.items():
    nm = (rel.get("tags") or {}).get("name", "(tanpa nama)")
    n_nodes = sum(1 for m in rel.get("members", []) if m["type"] == "node")
    print(f"  {rid}: {n_nodes} node | {nm}")
print()
for rid in rels:
    pass
# detail semua relasi (nama berurutan)
for rid in sorted(rels):
    rel = rels[rid]
    nm = (rel.get("tags") or {}).get("name", "(tanpa nama)")
    names = []
    for m in rel.get("members", []):
        if m["type"] != "node":
            continue
        n = nodes.get(m["ref"], {})
        nname = (n.get("tags") or {}).get("name")
        names.append(nname if nname else f"?{m['ref']}")
    print(f"== {rid} | {nm}")
    print("   ", " -> ".join(names))
    print()

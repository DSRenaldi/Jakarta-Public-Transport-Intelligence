# -*- coding: utf-8 -*-
"""Ringkas urutan node per relasi OSM (untuk menyusun konfigurasi ingest rail)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"


def load_nodes():
    f = WORK / "osm_member_nodes.json"
    if not f.exists():
        return {}
    data = json.loads(f.read_text(encoding="utf-8"))
    return {n["id"]: n for n in data}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    nodes = load_nodes()
    print(f"node tersedia: {len(nodes)}\n")
    for f in sorted(WORK.glob("osm_rel_*.json"), key=lambda p: int(p.stem.split("_")[2])):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            print(f"== {f.name}: FILE RUSAK")
            continue
        rels = [e for e in data.get("elements", []) if e["type"] == "relation"]
        if not rels:
            print(f"== {f.name}: tanpa relasi")
            continue
        rel = rels[0]
        t = rel.get("tags", {})
        print(f"== rel {rel['id']}  {t.get('name')}  (route={t.get('route')}, ref={t.get('ref')})")
        for m in rel["members"]:
            if m["type"] != "node":
                continue
            n = nodes.get(m["ref"], {})
            tags = n.get("tags", {})
            name = tags.get("name", "(tanpa nama)")
            lat = n.get("lat", "?")
            lon = n.get("lon", "?")
            print(f"   {m['ref']:<12} {name:<32} {lat},{lon}")
        print()


if __name__ == "__main__":
    main()

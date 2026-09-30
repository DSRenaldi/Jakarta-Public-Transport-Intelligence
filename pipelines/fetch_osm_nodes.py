# -*- coding: utf-8 -*-
"""Lengkapi data node anggota relasi (nama, koordinat, tag) — batch per 120 ID."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overpass_helper import overpass  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rel_files = sorted(WORK.glob("osm_rel_*.json"))
    print(f"{len(rel_files)} file relasi")
    all_nodes: dict[int, dict] = {}
    for f in rel_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            print(f"{f.name}: file rusak, lewati")
            continue
        rels = [e for e in data.get("elements", []) if e["type"] == "relation"]
        if not rels:
            continue
        node_ids = [m["ref"] for m in rels[0]["members"] if m["type"] == "node"]
        if not node_ids:
            continue
        need = [n for n in node_ids if n not in all_nodes]
        for i in range(0, len(need), 120):
            chunk = need[i:i + 120]
            q = f"[out:json][timeout:120];\nnode({','.join(map(str, chunk))});\nout body;\n"
            for attempt in range(3):
                try:
                    res = overpass(q)
                    for e in res.get("elements", []):
                        if e["type"] == "node":
                            all_nodes[e["id"]] = e
                    break
                except Exception:
                    print(f"  chunk gagal attempt {attempt+1}", flush=True)
                    time.sleep(15)
            time.sleep(1.5)
        print(f"{f.name}: {len(node_ids)} node anggota", flush=True)
    out = WORK / "osm_member_nodes.json"
    existing = 0
    if out.exists():
        try:
            existing = len(json.loads(out.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not all_nodes or (existing and len(all_nodes) < existing):
        print(f"\nAMANKAN: hasil {len(all_nodes)} node < existing {existing} "
              f"— file lama TIDAK ditimpa (Overpass gagal sebagian?)")
        sys.exit(1)
    out.write_text(json.dumps(list(all_nodes.values()), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    named = [n for n in all_nodes.values() if (n.get("tags") or {}).get("name")]
    print(f"\nTOTAL: {len(all_nodes)} node unik, {len(named)} bernama -> {out}", flush=True)


if __name__ == "__main__":
    main()

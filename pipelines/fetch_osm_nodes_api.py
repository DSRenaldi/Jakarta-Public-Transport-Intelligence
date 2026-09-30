# -*- coding: utf-8 -*-
"""
Fallback node fetch via OSM API utama, per-node (list endpoint tidak aktif).

GET https://api.openstreetmap.org/api/0.6/node/{id}  — 251 id, ~1.2 dtk/req.
Idempoten + resume: node yang sudah ada di osm_member_nodes.json dilewati.
"""
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
API = "https://api.openstreetmap.org/api/0.6/node/"
UA = "JPTI-research/1.0 (analisis moda transportasi Jakarta; proyek lokal)"
OUT = WORK / "osm_member_nodes.json"


def load_existing() -> dict:
    if OUT.exists():
        try:
            data = json.loads(OUT.read_text(encoding="utf-8"))
            return {n["id"]: n for n in data}
        except Exception:
            return {}
    return {}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    all_ids = []
    seen = set()
    for f in sorted(WORK.glob("osm_rel_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for e in data.get("elements", []):
            if e["type"] != "relation":
                continue
            for m in e.get("members", []):
                if m["type"] == "node" and m["ref"] not in seen:
                    seen.add(m["ref"])
                    all_ids.append(m["ref"])
    print(f"{len(all_ids)} node unik")

    nodes = load_existing()
    pending = [i for i in all_ids if i not in nodes]
    print(f"sudah ada: {len(all_ids) - len(pending)}, tersisa: {len(pending)}")

    failed = []
    for k, nid in enumerate(pending, 1):
        ok = False
        for attempt in range(3):
            try:
                r = requests.get(API + str(nid), headers={"User-Agent": UA},
                                 timeout=60)
                if r.status_code == 200:
                    root = ET.fromstring(r.content)
                    el = root.find("node")
                    if el is not None:
                        tags = {t.attrib["k"]: t.attrib["v"]
                                for t in el.findall("tag")}
                        nodes[nid] = {
                            "type": "node", "id": nid,
                            "lat": float(el.attrib["lat"]),
                            "lon": float(el.attrib["lon"]),
                            "tags": tags,
                        }
                        ok = True
                        break
                    # node tidak terlihat
                    break
                time.sleep(8 * (attempt + 1))
            except Exception:
                time.sleep(8 * (attempt + 1))
        if not ok:
            failed.append(nid)
        if k % 20 == 0 or k == len(pending):
            # simpan berkala utk resume
            OUT.write_text(
                json.dumps(list(nodes.values()), ensure_ascii=False, indent=1),
                encoding="utf-8")
            print(f"  {k}/{len(pending)} (terkumpul {len(nodes)}, "
                  f"gagal {len(failed)})", flush=True)
        time.sleep(1.2)

    OUT.write_text(json.dumps(list(nodes.values()), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    named = [n for n in nodes.values() if (n.get("tags") or {}).get("name")]
    print(f"\nSELESAI: {len(nodes)} node, {len(named)} bernama, "
          f"gagal: {len(failed)} {failed[:10]}")


if __name__ == "__main__":
    main()

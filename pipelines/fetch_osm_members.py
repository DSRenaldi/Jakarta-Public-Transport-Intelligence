# -*- coding: utf-8 -*-
"""Ambil anggota relasi rute PER RELASI (query ringan), robust + idempoten."""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overpass_helper import overpass  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
WORK.mkdir(exist_ok=True)

TARGETS = {
    "mrt": [9677669, 9677670, 18663751, 18663752],
    "lrt": [10693119, 10693160, 16036440, 16036441, 16079478, 16079479],
    "krl": [3442471, 2922163, 2922215, 2922235, 2922237, 15094545,
            15097496, 15097497, 15097498, 15097499, 15097500, 15097501,
            15097502, 15097503, 15097504, 15097505, 15097506, 15097507,
            16877210, 16877211, 16877212, 16877213, 17193008, 17193463,
            17675694, 17675695],
}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failed = []
    for group, ids in TARGETS.items():
        for rid in ids:
            out = WORK / f"osm_rel_{rid}.json"
            if out.exists() and out.stat().st_size > 200:
                continue
            for attempt in range(3):
                try:
                    q = f"[out:json][timeout:120];\nrelation({rid});\nout body;\n"
                    data = overpass(q)
                    out.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
                    rels = [e for e in data.get("elements", []) if e["type"] == "relation"]
                    if rels:
                        rel = rels[0]
                        t = rel.get("tags", {})
                        members = rel.get("members", [])
                        n_stop = sum(1 for m in members if m["type"] == "node")
                        print(f"[{group}] rel {rid} OK: {t.get('name')} "
                              f"({len(members)} members, {n_stop} node)", flush=True)
                    else:
                        print(f"[{group}] rel {rid} OK (tanpa relasi?)" , flush=True)
                    break
                except Exception:
                    print(f"[{group}] rel {rid} attempt {attempt+1} GAGAL", flush=True)
                    traceback.print_exc()
                    time.sleep(15)
                    if attempt == 2:
                        failed.append(rid)
            time.sleep(2.0)
    print(f"\nSELESAI. gagal: {failed if failed else 'tidak ada'}", flush=True)


if __name__ == "__main__":
    main()

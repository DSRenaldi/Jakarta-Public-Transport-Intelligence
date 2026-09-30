# -*- coding: utf-8 -*-
"""
Ambil relasi rute MRT/LRT (dan kandidat KRL) dari OSM Overpass.

Langkah 1: daftar relasi `route` (subway/lrt/tram) di bbox Jabodetabek + tag.
Langkah 2: anggota berurutan (node stasiun) relasi target.

Output: .work/osm_route_relations.json + .work/osm_relation_<id>.json
Overpass membutuhkan User-Agent (406 tanpa itu).
"""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
WORK.mkdir(exist_ok=True)

UA = "JPTI-research/1.0 (analisis moda transportasi Jakarta; kontak: proyek lokal)"
API = "https://overpass-api.de/api/interpreter"

# bbox Jabodetabek (S, W, N, E)
BBOX = "[-6.50,105.80,-5.95,107.30]"

QUERY_RELATIONS = """
[out:json][timeout:180];
relation(-6.50,105.80,-5.95,107.30)["route"~"^(subway|ltr|rtb|tram)$"]["name"];
out tags;
"""


def overpass(query: str) -> dict:
    for api in ("https://overpass-api.de/api/interpreter",
                "https://overpass.kumi.systems/api/interpreter"):
        try:
            r = requests.post(api, data={"data": query}, headers={"User-Agent": UA},
                              timeout=360)
            if r.status_code == 200:
                return r.json()
            print(f"  {api} -> {r.status_code}: {r.text[:400]}")
        except Exception as e:
            print(f"  {api} -> ERR {str(e)[:120]}")
    raise RuntimeError("semua endpoint Overpass gagal")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("== langkah 1: daftar relasi route ==")
    data = overpass(QUERY_RELATIONS)
    (WORK / "osm_route_relations.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    rels = data.get("elements", [])
    print(f"{len(rels)} relasi")
    keep = []
    for e in rels:
        t = e.get("tags", {})
        name = t.get("name", "")
        if any(k in name.lower() for k in ("mrt", "lrt", "commuter", "krl", "jabodebek", "loop")):
            print(f"  rel {e['id']}  route={t.get('route'):<8} ref={t.get('ref',''):<12} {name}")
            keep.append(e["id"])
    (WORK / "osm_target_relation_ids.json").write_text(json.dumps(keep), encoding="utf-8")
    return keep


if __name__ == "__main__":
    main()

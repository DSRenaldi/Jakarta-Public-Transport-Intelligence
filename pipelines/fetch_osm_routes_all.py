# -*- coding: utf-8 -*-
"""Lebar: semua relasi route (tanpa syarat name) di bbox Jabodetabek."""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
UA = "JPTI-research/1.0 (analisis moda transportasi Jakarta; kontak: proyek lokal)"
API = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:180];
relation(-6.50,105.80,-5.95,107.30)["route"];
out tags;
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = requests.post(API, data={"data": QUERY}, headers={"User-Agent": UA}, timeout=360)
    r.raise_for_status()
    data = r.json()
    (WORK / "osm_all_route_relations.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    els = data.get("elements", [])
    print(f"{len(els)} relasi route total")
    for e in els:
        t = e.get("tags", {})
        print(f"  {e['id']:<10} {str(t.get('route')):<10} ref={str(t.get('ref')):<6} {t.get('name', '(tanpa nama)')}")


if __name__ == "__main__":
    main()

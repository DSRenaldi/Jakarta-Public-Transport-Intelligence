# -*- coding: utf-8 -*-
"""Helper Overpass: multi-mirror, retry + backoff, log galat penuh."""
import re
import sys
import time

import requests

UA = "JPTI-research/1.0 (analisis moda transportasi Jakarta; kontak: proyek lokal)"
MIRRORS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def overpass(query: str, attempts: int = 4, pause: float = 8.0) -> dict:
    """Jalankan query Overpass dengan retry lintas mirror. Gagal total -> RuntimeError."""
    last_err = "?"
    for attempt in range(attempts):
        for i, api in enumerate(MIRRORS):
            mirror = MIRRORS[(i + attempt) % len(MIRRORS)]
            host = mirror.split("/")[2]
            try:
                r = requests.post(mirror, data={"data": query},
                                  headers={"User-Agent": UA}, timeout=300)
                if r.status_code == 200:
                    return r.json()
                err = " ".join(re.sub(r"<[^>]+>", " ", r.text).split())[:200]
                last_err = f"{host} {r.status_code}: {err}"
                print(f"    [{host}] {r.status_code}: {err[:120]}", flush=True)
            except Exception as e:
                last_err = f"{host} ERR {str(e)[:150]}"
                print(f"    [{host}] ERR {str(e)[:100]}", flush=True)
        time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"semua mirror gagal: {last_err}")

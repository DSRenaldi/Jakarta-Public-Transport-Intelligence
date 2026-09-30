# -*- coding: utf-8 -*-
"""
Fetch BPS DKI Jakarta monthly transport ridership tables.

Mekanisme (ditemukan 29 Sep 2026):
- Halaman tabel Next.js memuat tahun default dalam RSC flight payload
  (`self.__next_f.push`) sebagai objek `"data":{status, last_update, var,
  listTahun, datacontent, ...}`.
- Tahun lain diambil via React Server Action `getDataTable` (POST
  `Next-Action: <action_id>` ke URL halaman; body = array JSON argumen;
  maksimal 2 tahun per request).
- Kunci datacontent: `{vervar}{var}{turvar}{th_id_tahun}{bulan_1..13}`
  (bulan 13 = "Annually").

Output:
- data/raw/bps/<mode>_monthly_passengers.csv
- data/raw/bps/<mode>_metadata.json
- data/raw/bps/rsc_raw/<mode>_<years>.json (respons mentah)
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "bps"
RSC_RAW = RAW / "rsc_raw"

ACTION_ID = "40a85bc730ecaf8c01a30f235eb913efeb365605b6"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TABLES = [
    {
        "mode": "mrt_jakarta",
        "table_id": "MTMxOCMy",
        "locale": "id",
        "url": "https://jakarta.bps.go.id/id/statistics-table/2/MTMxOCMy/jumlah-penumpang-mass-rapid-transit-mrt-jakarta.html",
    },
    {
        "mode": "lrt_jakarta",
        "table_id": "MTMyMCMy",
        "locale": "eng",
        "url": "https://jakarta.bps.go.id/en/statistics-table/2/MTMyMCMy/number-of-jakarta-light-rail-transit--lrt--passengers.html",
    },
    {
        "mode": "transjakarta",
        "table_id": "MTMyNCMy",
        "locale": "eng",
        "url": "https://jakarta.bps.go.id/en/statistics-table/2/MTMyNCMy/number-of-transjakarta-bus-passengers-by-month.html",
    },
]

MONTHS = {1: "01", 2: "02", 3: "03", 4: "04", 5: "05", 6: "06",
          7: "07", 8: "08", 9: "09", 10: "10", 11: "11", 12: "12", 13: "99"}


def extract_escaped_json(html: str, marker: str) -> dict | None:
    """Cari objek JSON ter-escape (\"...\") di raw HTML flight payload via brace matching."""
    m = html.find(marker)
    while m >= 0:
        start = html.find("{", m)
        if start < 0:
            break
        depth = 0
        i = start
        n = len(html)
        while i < n:
            ch = html[i]
            if ch == "\\":
                i += 2  # lewati pasangan escape (\" atau \\)
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = html[start : i + 1]
                    unescaped = raw.replace('\\"', '"').replace("\\\\", "\\")
                    try:
                        return json.loads(unescaped)
                    except json.JSONDecodeError:
                        break
            i += 1
        m = html.find(marker, m + 1)
    return None


def fetch_page(sess: requests.Session, url: str) -> str:
    r = sess.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def parse_data_object(html: str) -> dict:
    obj = extract_escaped_json(html, '\\"data\\":{\\"status\\":\\"OK\\"')
    if obj and "datacontent" in obj:
        return obj
    raise RuntimeError("objek data tabel tidak ditemukan di flight payload")


def parse_list_tahun(html: str) -> dict:
    """{tahun_label: th_id} dari prop `listTahun` di flight payload."""
    out = {}
    for m in re.finditer(r'\\"th_id\\":(\d+),\\"th\\":\\"(\d{4})\\"', html):
        out[m.group(2)] = int(m.group(1))
    return out


def rsc_fetch_years(sess: requests.Session, url: str, table_id: str, locale: str, years: list[str], mode: str) -> dict:
    """POST RSC action untuk tahun-tahun yang belum ada. Max 2 tahun per panggilan."""
    out = {}
    for i in range(0, len(years), 2):
        batch = years[i : i + 2]
        body = json.dumps([json.dumps({"locale": locale, "id": table_id, "year": ";".join(batch)})])
        h = dict(HEADERS)
        h["Next-Action"] = ACTION_ID
        h["Content-Type"] = "text/plain;charset=UTF-8"
        h["Referer"] = url
        r = sess.post(url, headers=h, data=body.encode("utf-8"), timeout=60)
        r.raise_for_status()
        (RSC_RAW / f"{mode}_{';'.join(batch)}.txt").write_text(r.text, encoding="utf-8")
        parsed = None
        for line in r.text.splitlines():
            if line.startswith("1:"):
                parsed = json.loads(line[2:])
                break
        if not parsed or not parsed.get("status"):
            raise RuntimeError(f"RSC gagal untuk {batch}: {r.text[:200]}")
        resp = parsed["response"]
        if resp.get("status") != "OK":
            raise RuntimeError(f"RSC error {batch}: {resp}")
        out.update(resp.get("datacontent") or {})
        time.sleep(1.5)
    return out


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    RSC_RAW.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    summary = []
    for t in TABLES:
        print(f"== {t['mode']} ({t['table_id']}) ==")
        html = fetch_page(sess, t["url"])
        data = parse_data_object(html)
        var = data["var"][0]
        ver = data["vervar"][0]["val"] if data.get("vervar") else 1
        tur = data["turvar"][0]["val"] if data.get("turvar") else "0"
        th_map = parse_list_tahun(html) or {y["label"]: y["val"] for y in data["tahun"]}
        datacontent = dict(data.get("datacontent") or {})

        # tahun yang belum tersedia di payload
        prefix = f"{ver}{var['val']}{tur}"
        have_years = {k[len(prefix): len(prefix) + 3] for k in datacontent if k.startswith(prefix)}
        missing = [str(th_map[y]) for y in sorted(th_map) if str(th_map[y]) not in have_years]
        if missing:
            print(f"   payload: {sorted(have_years)}; fetch RSC: {missing}")
            datacontent.update(rsc_fetch_years(sess, t["url"], t["table_id"], t["locale"], missing, t["mode"]))

        rows = []
        for key, val in datacontent.items():
            # key = ver + var + tur + th(3) + bulan(1)
            if not key.startswith(prefix):
                continue
            suffix = key[len(prefix):]
            th_id, month = suffix[:3], int(suffix[3])
            year = [y for y, i in th_map.items() if i == int(th_id)]
            if not year:
                continue
            rows.append({
                "mode": t["mode"],
                "year": int(year[0]),
                "month": MONTHS[month],
                "passenger_count": int(val),
                "is_annual": month == 13,
                "source_id": "SRC-BPS-02",
                "source_url": t["url"],
                "definition": var.get("def", ""),
                "note": var.get("note", ""),
                "unit": var.get("unit", "Person"),
                "last_update": data.get("last_update", ""),
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
        rows.sort(key=lambda r: (r["year"], r["month"]))
        csv_path = RAW / f"{t['mode']}_monthly_passengers.csv"
        if rows:
            import csv as _csv
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        meta = {
            "table_id": t["table_id"],
            "url": t["url"],
            "var": var,
            "last_update": data.get("last_update"),
            "data_availability": data.get("data-availability"),
            "tahun": data.get("tahun"),
            "rows": len(rows),
            "csv": str(csv_path.relative_to(ROOT)),
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        (RAW / f"{t['mode']}_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        span = f"{rows[0]['year']}-{rows[-1]['year']}" if rows else "?"
        print(f"   OK: {len(rows)} baris, rentang {span}, last_update={data.get('last_update')}")
        summary.append(f"{t['mode']}: {len(rows)} rows ({span})")
        time.sleep(2)
    print("=== SELESAI ===")
    for s in summary:
        print("  " + s)


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
Ingest GTFS TransJakarta (data/raw/transjakarta/gtfs_transjakarta_2026-07-27.zip)
ke Postgres/PostGIS (transum_jakarta).

Pemetaan:
- stops.txt      -> stops (geometri Point 4326)
- routes.txt     -> lines (satu line per route GTFS)
- stop_times.txt -> route_stops (urutan unik per arah) + trips + stop_times
- calendar.txt   -> service_calendars
- calendar_dates -> service_calendar_dates
- frequencies    -> frequencies
- fare_*.txt     -> fares
- agency.txt     -> operators

Sumber: SRC-TJ-02 (CC BY 4.0, versi feed 27 Jul 2026).
"""
import csv
import io
import json
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GTFS_ZIP = ROOT / "data" / "raw" / "transjakarta" / "gtfs_transjakarta_2026-07-27.zip"
SOURCE_ID = "SRC-TJ-02"
FEED_DATE = "2026-07-27"


def read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    with zf.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def gtfs_time_to_pg(t: str | None):
    """HH:MM:SS -> 'HH:MM:SS' (PG TIME); handle >24h (HH+24) -> mod 24 + day_offset."""
    if not t:
        return None, 0
    parts = t.split(":")
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
    return f"{h % 24:02d}:{m:02d}:{s:02d}", h // 24


def main():
    t0 = time.time()
    zf = zipfile.ZipFile(GTFS_ZIP)
    conn = connect()
    cur = conn.cursor()

    # ---------- provenance ----------
    cur.execute("""
        INSERT INTO data_sources(source_id, name, url, access_method, license,
                                 update_frequency, status, verified_at, notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source_id) DO UPDATE SET
            status=EXCLUDED.status, verified_at=EXCLUDED.verified_at,
            notes=EXCLUDED.notes
    """, (SOURCE_ID, "GTFS resmi TransJakarta (PT Transportasi Jakarta)",
          "https://gtfs.transjakarta.co.id/files/file_gtfs.zip", "auto",
          "CC BY 4.0", "±1-2 bulan", "live", "2026-09-29",
          f"feed versi {FEED_DATE}; 13 file; terunduh Fase 1"))
    print("data_sources OK")

    # ---------- operator ----------
    agency = read_csv(zf, "agency.txt")[0]
    cur.execute("""
        INSERT INTO operators(operator_id, canonical_name, display_name, legal_name, website)
        VALUES ('TRANSJAKARTA', %s, %s, %s, %s)
        ON CONFLICT (operator_id) DO NOTHING
    """, (agency.get("agency_name", "PT Transportasi Jakarta"),
          "TransJakarta", agency.get("agency_name", ""),
          agency.get("agency_url", "")))
    cur.execute("""
        INSERT INTO modes(mode_id, operator_id, display_name)
        VALUES ('BRT', 'TRANSJAKARTA', 'Bus Rapid Transit (TransJakarta)')
        ON CONFLICT (mode_id, operator_id) DO NOTHING
    """)
    print("operator+mode OK")

    # ---------- stops ----------
    stops = read_csv(zf, "stops.txt")
    stop_rows = []
    for s in stops:
        try:
            lat = float(s["stop_lat"])
            lng = float(s["stop_lon"])
            geom = f"SRID=4326;POINT({lng} {lat})"
        except (KeyError, ValueError):
            geom = None
        name = s.get("stop_name", "").strip()
        stop_rows.append((
            f"TJ_{s['stop_id']}", name, name, geom, geom, s["stop_id"],
            SOURCE_ID,
        ))
    cur.executemany("""
        INSERT INTO stops(stop_id_internal, operator_id, mode_id, canonical_name,
                          display_name, geometry, gtfs_stop_id, source_id)
        VALUES (%s, 'TRANSJAKARTA', 'BRT', %s, %s,
                CASE WHEN %s::text IS NULL THEN NULL ELSE ST_GeomFromEWKT(%s) END,
                %s, %s)
        ON CONFLICT (stop_id_internal) DO UPDATE SET
            geometry = EXCLUDED.geometry, display_name = EXCLUDED.display_name
    """, stop_rows)
    conn.commit()
    print(f"stops: {len(stop_rows)}")

    # ---------- routes -> lines + routes ----------
    routes = read_csv(zf, "routes.txt")
    line_rows, route_rows = [], []
    for r in routes:
        line_id = f"TJ_{r['route_id']}"
        color = r.get("route_color")
        color = f"#{color}" if color and not color.startswith("#") else color
        line_rows.append((
            line_id, "TRANSJAKARTA", "BRT", r.get("route_long_name", r["route_id"]),
            f"{r.get('route_short_name','')} — {r.get('route_long_name','')}" if r.get("route_short_name") else r.get("route_long_name"),
            color, FEED_DATE, None, SOURCE_ID,
        ))
        dir_map = {"0": "outbound", "1": "inbound"}
        for d in ("0", "1"):
            route_rows.append((f"{line_id}_d{d}", line_id,
                               f"{r.get('route_long_name','')} (arah {d})",
                               dir_map[d],
                               FEED_DATE, None, SOURCE_ID))
    cur.executemany("""
        INSERT INTO lines(line_id, operator_id, mode_id, canonical_name, display_name,
                          color, valid_from, valid_to, source_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (line_id) DO NOTHING
    """, line_rows)
    cur.executemany("""
        INSERT INTO routes(route_id, line_id, pattern_name, direction,
                           valid_from, valid_to, source_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (route_id) DO NOTHING
    """, route_rows)
    conn.commit()
    print(f"lines: {len(line_rows)}, routes: {len(route_rows)}")

    # ---------- trips + stop_times -> route_stops ----------
    trips = read_csv(zf, "trips.txt")
    trip_rows = []
    for t in trips:
        gid = t["trip_id"]
        line_id = f"TJ_{t['route_id']}"
        route_id = f"{line_id}_d{t.get('direction_id', '0')}"
        trip_rows.append((
            f"TJ_{gid}", route_id, t.get("trip_headsign", "").strip() or None,
            t.get("direction_id") and int(t["direction_id"]),
            t.get("shape_id") or None, SOURCE_ID,
        ))
    cur.executemany("""
        INSERT INTO trips(trip_id, route_id, trip_headsign, direction_id, shape_id, source_id)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (trip_id) DO NOTHING
    """, trip_rows)
    conn.commit()
    print(f"trips: {len(trip_rows)}")

    stop_times = read_csv(zf, "stop_times.txt")
    trip_dir = {t["trip_id"]: t.get("direction_id", "0") or "0" for t in trips}
    trip_route = {t["trip_id"]: f"TJ_{t['route_id']}" for t in trips}
    st_rows = []
    skipped = 0
    seen_route_stop: dict[str, dict[str, int]] = {}
    for st in stop_times:
        trip_id = f"TJ_{st['trip_id']}"
        line_id = trip_route.get(st["trip_id"])
        if line_id is None:
            skipped += 1
            continue
        direction = st.get("direction_id") or trip_dir.get(st["trip_id"], "0")
        route_id = f"{line_id}_d{direction}"
        stop_int = f"TJ_{st['stop_id']}"
        arr, day_off = gtfs_time_to_pg(st.get("arrival_time"))
        dep, day_off2 = gtfs_time_to_pg(st.get("departure_time"))
        st_rows.append((trip_id, stop_int, int(st["stop_sequence"]),
                        arr, dep, max(day_off, day_off2)))
        m = seen_route_stop.setdefault(route_id, {})
        if stop_int not in m:
            m[stop_int] = len(m) + 1
    cur.executemany("""
        INSERT INTO stop_times(trip_id, stop_id_internal, seq, arrival_time,
                               departure_time, arrival_day_offset)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (trip_id, seq) DO NOTHING
    """, st_rows)
    conn.commit()
    print(f"stop_times: {len(st_rows)} (lewati {skipped} trip tak dikenal)")

    rs_rows = [(r, s, i) for r, m in seen_route_stop.items() for s, i in m.items()]
    cur.executemany("""
        INSERT INTO route_stops(route_id, stop_id_internal, seq)
        VALUES (%s,%s,%s)
        ON CONFLICT (route_id, seq) DO NOTHING
    """, rs_rows)
    conn.commit()
    print(f"route_stops: {len(rs_rows)}")

    # ---------- calendars ----------
    cal = read_csv(zf, "calendar.txt")
    cur.executemany("""
        INSERT INTO service_calendars(service_id, description, monday, tuesday,
            wednesday, thursday, friday, saturday, sunday, start_date, end_date, source_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (service_id) DO NOTHING
    """, [(c["service_id"], c.get("service_description", ""), int(c["monday"]),
           int(c["tuesday"]), int(c["wednesday"]), int(c["thursday"]), int(c["friday"]),
           int(c["saturday"]), int(c["sunday"]), c["start_date"], c["end_date"], SOURCE_ID)
          for c in cal])
    conn.commit()
    print(f"calendars: {len(cal)}")
    if "calendar_dates.txt" in zf.namelist():
        cd = read_csv(zf, "calendar_dates.txt")
        cur.executemany("""
            INSERT INTO service_calendar_dates(service_id, date, exception)
            VALUES (%s,%s,%s) ON CONFLICT (service_id, date) DO NOTHING
        """, [(c["service_id"], c["date"], int(c["exception"])) for c in cd])
        conn.commit()
        print(f"calendar_dates: {len(cd)}")

    # ---------- frequencies ----------
    if "frequencies.txt" in zf.namelist():
        freq = read_csv(zf, "frequencies.txt")
        f_rows = []
        for f in freq:
            s_t, _ = gtfs_time_to_pg(f["start_time"])
            e_t, _ = gtfs_time_to_pg(f["end_time"])
            f_rows.append((f"TJ_{f['trip_id']}", s_t, e_t, int(f["headway_secs"]),
                           int(f.get("exact_times", 0))))
        cur.executemany("""
            INSERT INTO frequencies(trip_id, start_time, end_time, headway_sec, exact_times)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (trip_id, start_time) DO NOTHING
        """, f_rows)
        conn.commit()
        print(f"frequencies: {len(f_rows)}")

    # ---------- fares ----------
    fa = read_csv(zf, "fare_attributes.txt")
    fr = read_csv(zf, "fare_rules.txt")
    for a in fa:
        rules = [r for r in fr if r["fare_id"] == a["fare_id"]]
        cur.execute("""
            INSERT INTO fares(operator_id, mode_id, fare_type, price_idr, valid_from,
                              legal_basis, source_id, notes)
            VALUES ('TRANSJAKARTA','BRT','flat',%s,%s,NULL,%s,%s)
        """, (int(float(a["price"])), FEED_DATE, SOURCE_ID,
              f"GTFS fare_rules: {len(rules)} route(s)"))
    conn.commit()
    print(f"fares: {len(fa)}")

    # ---------- line geometries (per line, dari route arah 0) ----------
    cur.execute("""
        DELETE FROM line_geometries
    """)
    cur.execute("SELECT DISTINCT line_id FROM lines")
    line_ids = [r[0] for r in cur.fetchall()]
    geom_done = 0
    for lid in line_ids:
        pts = None
        for suffix in ("_d0", "_d1"):
            cur.execute("""
                SELECT ST_X(s.geometry), ST_Y(s.geometry) FROM route_stops rs
                JOIN stops s ON s.stop_id_internal = rs.stop_id_internal
                WHERE rs.route_id = %s AND s.geometry IS NOT NULL
                ORDER BY rs.seq
            """, (lid + suffix,))
            rows = cur.fetchall()
            if len(rows) >= 2:
                pts = rows
                break
        if pts:
            wkt = "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in pts) + ")"
            cur.execute("""
                INSERT INTO line_geometries(line_id, geometry)
                VALUES (%s, ST_SetSRID(ST_GeomFromText(%s), 4326))
                ON CONFLICT (line_id) DO UPDATE SET geometry = EXCLUDED.geometry
            """, (lid, wkt))
            geom_done += 1
    conn.commit()
    print(f"line_geometries: {geom_done}/{len(line_ids)}")

    # ---------- quality + run log ----------
    cur.execute("""
        INSERT INTO data_quality_results(dataset, check_type, result, details)
        VALUES ('gtfs_transjakarta', 'schema', 'pass', %s)
    """, (f"feed {FEED_DATE}; stops={len(stop_rows)}, trips={len(trip_rows)}, "
          f"stop_times={len(st_rows)}, routes={len(route_rows)}",))
    cur.execute("""
        INSERT INTO ingest_runs(pipeline, finished_at, rows_affected, notes)
        VALUES (%s, now(), %s, %s)
    """, ("ingest_gtfs.py", len(stop_rows) + len(st_rows) + len(rs_rows),
          f"GTFS {FEED_DATE}"))
    conn.commit()
    conn.close()
    print(f"\nSELESAI dalam {time.time()-t0:.1f} detik")


if __name__ == "__main__":
    main()

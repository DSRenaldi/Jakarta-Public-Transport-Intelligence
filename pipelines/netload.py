# -*- coding: utf-8 -*-
"""Muat jaringan dari Postgres -> objek Network (routing.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402
from routing import (AUTO_TRANSFER_MAX_M, DWELL_SEC, FALLBACK_HEADWAY_SEC,  # noqa: E402
                     Network, Edge, Stop, WALK_SPEED_MPS, haversine_m)

TJ_SUFFIXES = (" (A)", " (B)", " (a)", " (b)")

# semua state mode yang mungkin di sebuah stop (mode aktif = None setelah
# jalan kaki antar-moda tetap moda asal — jadi semua state bisa tercapai)
ALL_STATES = (None, "MRT", "KRL", "LRT", "BRT")


def _norm_tj_name(name: str) -> str:
    for s in TJ_SUFFIXES:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def load_network(conn=None) -> Network:
    own = conn is None
    if own:
        conn = connect()
    cur = conn.cursor()
    net = Network()

    # ---------- registry provenance ----------
    cur.execute("""
        SELECT source_id, name, url, verified_at, status
        FROM data_sources
    """)
    net.source_meta = {
        source_id: {
            "source_id": source_id,
            "title": name,
            "url": url,
            "verified_at": verified_at.isoformat() if verified_at else None,
            "status": status,
        }
        for source_id, name, url, verified_at, status in cur.fetchall()
    }

    # ---------- stops ----------
    cur.execute("""
        SELECT stop_id_internal, mode_id, canonical_name, display_name,
               ST_Y(geometry), ST_X(geometry)
        FROM stops WHERE geometry IS NOT NULL
    """)
    for sid, mode, name, disp, lat, lon in cur.fetchall():
        net.add_stop(Stop(sid, mode, name, lat, lon, disp))

    # ---------- alias (riwayat nama) per stop ----------
    # nama lama resmi / nama populer dari stop_name_history; nama yang sama
    # dgn nama kini (canonical atau display) dikecualikan — itu bukan alias.
    cur.execute("""
        SELECT stop_id_internal, name
        FROM stop_name_history
        WHERE name IS NOT NULL AND name <> ''
        ORDER BY stop_id_internal, valid_from DESC NULLS LAST
    """)
    for sid, alias in cur.fetchall():
        s = net.stops.get(sid)
        if not s or alias == s.name or alias == (s.display_name or ""):
            continue
        if alias not in s.aliases:
            s.aliases.append(alias)

    # ---------- nama line utk tampilan ----------
    cur.execute("""
        SELECT line_id, canonical_name, display_name, source_id
        FROM lines
    """)
    net.line_name = {}
    net.line_display = {}
    net.line_source = {}
    for line_id, canon, disp, source_id in cur.fetchall():
        net.line_name[line_id] = canon
        net.line_display[line_id] = disp or canon
        net.line_source[line_id] = source_id

    # ---------- tarif flat per moda (proxy: harga minimum POSITIF) ----------
    cur.execute("""
        SELECT DISTINCT ON (mode_id)
               mode_id, price_idr, source_id, valid_from, valid_to,
               legal_basis, fare_type
        FROM fares
        WHERE price_idr > 0
        ORDER BY mode_id, price_idr, valid_from DESC NULLS LAST, fare_id
    """)
    net.mode_fare = {}
    net.mode_fare_source = {}
    for (mode, price, source_id, valid_from, valid_to,
         legal_basis, fare_type) in cur.fetchall():
        net.mode_fare[mode] = price
        net.mode_fare_source[mode] = {
            "source_id": source_id,
            "price_idr": price,
            "valid_from": valid_from.isoformat() if valid_from else None,
            "valid_to": valid_to.isoformat() if valid_to else None,
            "legal_basis": legal_basis,
            "fare_type": fare_type,
        }

    # ---------- headway per line ----------
    cur.execute("""
        SELECT line_id, AVG(headway_min) FROM line_headways
        GROUP BY line_id
    """)
    line_headway = {lid: int(round(h * 60)) for lid, h in cur.fetchall() if h}

    # ---------- waktu tempuh GTFS (BRT) per (route, a, b) ----------
    cur.execute("""
        WITH ordered AS (
            SELECT trip_id, seq, stop_id_internal,
                   EXTRACT(EPOCH FROM departure_time) + arrival_day_offset * 86400 AS dep
            FROM stop_times WHERE departure_time IS NOT NULL
        ),
        pair AS (
            SELECT a.stop_id_internal AS sa, b.stop_id_internal AS sb,
                   t.route_id, b.dep - a.dep AS dt
            FROM ordered a
            JOIN ordered b ON b.trip_id = a.trip_id AND b.seq = a.seq + 1
            JOIN trips t ON t.trip_id = a.trip_id
            WHERE b.dep > a.dep AND b.dep - a.dep < 3600
        )
        SELECT route_id, sa, sb, AVG(dt)
        FROM pair GROUP BY route_id, sa, sb
    """)
    gtfs_edge_time: dict[tuple, float] = {}
    for route_id, sa, sb, dt in cur.fetchall():
        gtfs_edge_time[(route_id, sa, sb)] = float(dt)

    # ---------- headwait per route (BRT dari frequencies) ----------
    cur.execute("""
        SELECT t.route_id, MIN(f.headway_sec)
        FROM frequencies f JOIN trips t ON t.trip_id = f.trip_id
        GROUP BY t.route_id
    """)
    route_headway = dict(cur.fetchall())

    # ---------- urutan stop per route -> edge ----------
    cur.execute("""
        SELECT rs.route_id, r.direction, l.line_id, rs.stop_id_internal, rs.seq
        FROM route_stops rs
        JOIN routes r ON r.route_id = rs.route_id
        JOIN lines l ON l.line_id = r.line_id
        ORDER BY rs.route_id, rs.seq
    """)
    routes: dict[str, list[str]] = {}
    route_meta: dict[str, tuple[str, str]] = {}
    for route_id, _dir, line_id, sid, _seq in cur.fetchall():
        routes.setdefault(route_id, []).append(sid)
        route_meta[route_id] = (line_id, line_id)

    for route_id, sids in routes.items():
        line_id = route_meta[route_id][0]
        mode = net.stops[sids[0]].mode if sids and sids[0] in net.stops else "BRT"
        if mode == "BRT":
            wait = (route_headway.get(route_id) or 300) / 2.0
            fare = net.mode_fare.get("BRT", 3500)
        else:
            wait = (line_headway.get(line_id) or FALLBACK_HEADWAY_SEC.get(mode, 300)) / 2.0
            fare = net.mode_fare.get(mode, 0)
        for a, b in zip(sids, sids[1:]):
            if a not in net.stops or b not in net.stops:
                continue
            if mode == "BRT":
                t = gtfs_edge_time.get((route_id, a, b))
                if t is None:
                    sa, sb = net.stops[a], net.stops[b]
                    t = (haversine_m(sa.lat, sa.lon, sb.lat, sb.lon)
                         / SPEED_BY_MODE["BRT"]) * 3.6 + DWELL_SEC["BRT"]
                    time_method = "distance_speed_dwell_proxy"
                else:
                    time_method = "gtfs_schedule_average"
            else:
                sa, sb = net.stops[a], net.stops[b]
                dist = haversine_m(sa.lat, sa.lon, sb.lat, sb.lon)
                t = dist / SPEED_BY_MODE[mode] * 3.6 + DWELL_SEC.get(mode, 40)
                time_method = "distance_speed_dwell_proxy"
            # edge tersedia dari semua state di a (boarding diurus di route()):
            for sm in ALL_STATES:
                net.add_edge(a, sm, Edge(b, mode, t, wait, fare, mode, line_id,
                                         route_id,
                                         time_method=time_method,
                                         source_id=net.line_source.get(line_id)))

    # ---------- transfers ----------
    cur.execute("""
        SELECT from_stop_id, to_stop_id, walking_time_sec, source_id
        FROM transfers
    """)
    for a, b, w, source_id in cur.fetchall():
        if a in net.stops and b in net.stops:
            for m in ALL_STATES:
                net.add_edge(a, m, Edge(b, m, float(w), 0, 0, None, None, None,
                                        is_transfer=True,
                                        time_method="transfer_table_walk",
                                        source_id=source_id))
    # auto transfer antar moda < 250 m (SQL PostGIS)
    cur.execute(f"""
        SELECT a.stop_id_internal, b.stop_id_internal,
               ST_Distance(a.geometry::geography, b.geometry::geography) AS m
        FROM stops a
        JOIN stops b ON a.stop_id_internal < b.stop_id_internal
           AND a.mode_id <> b.mode_id
           AND ST_DWithin(a.geometry::geography, b.geometry::geography, {AUTO_TRANSFER_MAX_M})
        WHERE a.geometry IS NOT NULL AND b.geometry IS NOT NULL
    """)
    n_auto = 0
    for a, b, m in cur.fetchall():
        if a not in net.stops or b not in net.stops:
            continue
        w = max(60.0, float(m) / WALK_SPEED_MPS)
        for mm in ALL_STATES:
            net.add_edge(a, mm, Edge(
                b, mm, w, 0, 0, None, None, None, is_transfer=True,
                time_method="geometry_walk_proxy"))
        for mm in ALL_STATES:
            net.add_edge(b, mm, Edge(
                a, mm, w, 0, 0, None, None, None, is_transfer=True,
                time_method="geometry_walk_proxy"))
        n_auto += 1

    # auto transfer A<->B pada halte BRT yang sama (nama sama, jarak < 150 m)
    from collections import defaultdict
    groups: dict[tuple, list[str]] = defaultdict(list)
    for sid, s in net.stops.items():
        if s.mode == "BRT":
            groups[(s.mode, _norm_tj_name(s.name))].append(sid)
    n_ab = 0
    for key, sids in groups.items():
        if len(sids) < 2:
            continue
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                a, b = net.stops[sids[i]], net.stops[sids[j]]
                if haversine_m(a.lat, a.lon, b.lat, b.lon) > 150:
                    continue
                for mm in ALL_STATES:
                    net.add_edge(sids[i], mm, Edge(sids[j], mm, 60.0, 0, 0, None,
                                                   None, None, is_transfer=True,
                                                   time_method="geometry_walk_proxy"))
                for mm in ALL_STATES:
                    net.add_edge(sids[j], mm, Edge(sids[i], mm, 60.0, 0, 0, None,
                                                   None, None, is_transfer=True,
                                                   time_method="geometry_walk_proxy"))
                n_ab += 1
    if own:
        conn.close()
    print(f"[netload] stops={len(net.stops)}, routes={len(routes)}, "
          f"auto_transfer_antarmoda={n_auto}, transfer_AB={n_ab}", file=sys.stderr)
    return net


SPEED_BY_MODE = {"MRT": 33.0, "KRL": 36.0, "LRT": 45.0, "BRT": 30.0}


def _states_at(net: Network, stop_id: str) -> list:
    """State mode yang mungkin berada di stop ini: mode stop itu sendiri + None."""
    s = net.stops.get(stop_id)
    return [None, s.mode] if s else [None]

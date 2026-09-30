# -*- coding: utf-8 -*-
"""
Mesin pencarian rute JPTI (Fase 2 — MVP).

Model (context.md §17):
    generalized_cost =
        travel_time_weight × travel_time
      + waiting_weight × waiting_time
      + transfer_weight × transfer_count
      + fare_weight × fare

Graf:
- State = (stop_id_internal, mode_aktif|None)
- Edge rute = antarestasiun berurutan; waktu = GTFS stop_times (BRT, aktual
  jadwal) atau haversine/kecepatan + dwell (rail — label PROKSI)
- Edge transfer = tabel transfers + auto-deteksi < 250 m antar moda
- Menunggu = headway/2 saat berpindah moda (BRT dari frequencies, rail dari
  line_headways)
- Tarif = flat per moda saat moda baru ditumpangi (satu tap BRT = semua BRT)

Limitasi MVP: single-label Dijkstra (bukan Pareto); tanpa gangguan layanan.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field


# ---------- konstanta asumsi (label: proksi) ----------
SPEED_KMH = {  # kecepatan rata-rata in-vehicle utk moda tanpa jadwal
    "MRT": 33.0,
    "KRL": 36.0,
    "LRT": 45.0,
    "BRT": 30.0,  # fallback; BRT memakai stop_times GTFS bila ada
}
DWELL_SEC = {"MRT": 40, "KRL": 45, "LRT": 40, "BRT": 30}
FALLBACK_HEADWAY_SEC = {"MRT": 300, "KRL": 600, "LRT": 600, "BRT": 300}
WALK_SPEED_MPS = 1.3
AUTO_TRANSFER_MAX_M = 250.0
TRANSFER_PENALTY_SEC = 180  # bagian tetap dari transfer_weight per perpindahan

# preferensi -> (w_time, w_wait, w_transfer, w_fare)
PREFERENCES = {
    "tercepat": (1.0, 1.0, 60.0, 0.0005),
    "termurah": (0.05, 0.05, 120.0, 1.0),
    "min_transfers": (0.3, 0.3, 300.0, 0.001),
    "longgar": (0.5, 0.5, 90.0, 0.1),
}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Stop:
    stop_id: str
    mode: str
    name: str
    lat: float | None
    lon: float | None


@dataclass
class Edge:
    to_stop: str
    to_mode: str | None
    travel_sec: float
    wait_sec: float
    fare: int
    mode: str | None
    line_id: str | None = None
    route_id: str | None = None
    is_transfer: bool = False


@dataclass
class RouteResult:
    found: bool
    time_sec: float
    fare: int
    transfers: int
    segments: list = field(default_factory=list)
    message: str = ""


class Network:
    def __init__(self):
        self.stops: dict[str, Stop] = {}
        self.edges: dict[tuple[str, str | None], list[Edge]] = {}
        self.mode_fare: dict[str, int] = {}
        self.mode_headway: dict[str, int] = {}
        self.line_name: dict[str, str] = {}

    def add_stop(self, s: Stop):
        self.stops[s.stop_id] = s

    def add_edge(self, stop_id: str, mode: str | None, e: Edge):
        self.edges.setdefault((stop_id, mode), []).append(e)

    # ---------- pencarian ----------
    def route(self, origin: str, dest: str, preference: str = "tercepat") -> RouteResult:
        if origin not in self.stops or dest not in self.stops:
            return RouteResult(False, 0, 0, 0, [], "stop tidak ditemukan di jaringan")
        w_t, w_w, w_x, w_f = PREFERENCES[preference]

        NONE = None
        start = (origin, NONE)
        # label: (cost, time, wait, fare, transfers)
        labels = {start: (0.0, 0.0, 0.0, 0, 0)}
        prev: dict[tuple, tuple] = {}
        pq = [(0.0, start)]
        done: set[tuple] = set()

        while pq:
            c, state = heapq.heappop(pq)
            if state in done:
                continue
            done.add(state)
            s_id, mode = state
            _, cur_time, cur_wait, cur_fare, cur_tr = labels[state]
            for e in self.edges.get(state, []):
                if e.is_transfer:
                    n_tr = cur_tr + 1
                    n_cost = c + w_t * e.travel_sec + w_x * TRANSFER_PENALTY_SEC
                    n_time = cur_time + e.travel_sec
                    n_wait, n_fare, n_mode = cur_wait, cur_fare, mode
                else:
                    boarding = (mode != e.mode)
                    n_tr = cur_tr + (1 if (boarding and mode is not None) else 0)
                    n_wait = cur_wait + (e.wait_sec if boarding else 0.0)
                    n_fare = cur_fare + (e.fare if boarding else 0)
                    n_cost = (c + w_t * e.travel_sec
                              + w_w * (e.wait_sec if boarding else 0.0)
                              + (w_x * TRANSFER_PENALTY_SEC
                                 if (boarding and mode is not None) else 0.0))
                    n_time = cur_time + e.travel_sec + (e.wait_sec if boarding else 0.0)
                    n_mode = e.mode
                nstate = (e.to_stop, n_mode)
                if nstate in done:
                    continue
                old = labels.get(nstate)
                if old is None or n_cost < old[0]:
                    labels[nstate] = (n_cost, n_time, n_wait, n_fare, n_tr)
                    prev[nstate] = state
                    heapq.heappush(pq, (n_cost, nstate))

        best_mode, best_lab = None, None
        for (s_id, mode), lab in labels.items():
            if s_id != dest:
                continue
            if best_lab is None or lab[0] < best_lab[0]:
                best_mode, best_lab = mode, lab
        if best_lab is None:
            return RouteResult(False, 0, 0, 0, [],
                               "tidak ada rute dari origin ke dest")

        # rekonstruksi path state
        path = []
        cur = (dest, best_mode)
        while cur is not None:
            path.append(cur)
            cur = prev.get(cur)
        path.reverse()

        segs = []
        for i in range(1, len(path)):
            a, b = path[i - 1], path[i]
            e = self._find_edge(a, b)
            if e is None:
                continue
            if e.is_transfer:
                segs.append({"type": "transfer", "from": a[0], "to": b[0],
                             "walk_sec": e.travel_sec})
            else:
                segs.append({"type": "ride", "mode": e.mode, "line": e.line_id,
                             "route": e.route_id, "from": a[0], "to": b[0],
                             "travel_sec": e.travel_sec,
                             "wait_sec": max(0.0, labels[b][2] - labels[a][2]),
                             "fare": e.fare if b[1] != a[1] else 0})
        return RouteResult(True, best_lab[1], best_lab[3], best_lab[4], segs)

    def _find_edge(self, a: tuple, b: tuple) -> Edge | None:
        for e in self.edges.get(a, []):
            if e.to_stop == b[0] and e.to_mode == b[1]:
                return e
        return None

    @staticmethod
    def fmt_time(sec: float) -> str:
        m = int(round(sec / 60))
        if m < 60:
            return f"{m} mnt"
        return f"{m // 60} j {m % 60:02d} mnt"

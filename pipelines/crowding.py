# -*- coding: utf-8 -*-
"""Model kepadatan JPTI — baseline pattern `crowding-v1` (proksi berlabel).

Dasar spesifikasi (context.md):
- §15.6  kategori awal longgar/sedang/padat/sangat_padat; ambang PROVISIONAL
         (jangan permanen sebelum validasi data).
- §16.3  baseline dulu; model lanjutan hanya bila mengungguli baseline.
- §27.1  data per jam/OD tidak tersedia → proksi yang diberi label.
- §29.5  prediksi berbasis pola historis dengan label ketidakpastian.
- §7     label aktual/historis/prediksi/proksi; sumber + periode per angka.

Model v1 = pola dari input TERDOKUMENTASI (bukan supervised learning —
tidak ada ground truth):

    score(line, t, day) = W(t) × D(day)   ∈ [0,1]

    W(t):  jendela sibuk (DB line_headways ← SRC-KRL-03) = 1.0
           ± shoulder 30 mnt = 0.65
           offpeak siang (04:00-24:00) = 0.30
           malam (< 04:00) = 0.10
    D(day): weekday = 1.0; weekend = 0.38
           (rail: SRC-SEC-07; BRT: asumsi, ditandai)

    Kategori: padat ≥ 0.85; sedang ≥ 0.35; longgar < 0.35;
              'sangat_padat' DITAHAN — tidak dihasilkan v1 (butuh validasi).

Setiap output selalu membawa: data_label="proksi", confidence (tier),
basis per klaim (source_id), dan limitation. Model TIDAK mengklaim
mengetahui kepadatan aktual.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, time as dtime
from pathlib import Path

from db import connect

PRIORS_PATH = Path(__file__).resolve().parent / "crowding_priors.json"
MODEL_VERSION = "crowding-v1"
_NIGHT_START = dtime(4, 0)
_SHOULDER_FALLBACK_MIN = 30

_prior_cache: tuple[float, dict] | None = None
_hw_cache: tuple[float, dict] | None = None
_CACHE_TTL_SEC = 3600


def _load_priors() -> dict:
    global _prior_cache
    now = time.time()
    if _prior_cache and now - _prior_cache[0] < _CACHE_TTL_SEC:
        return _prior_cache[1]
    with open(PRIORS_PATH, encoding="utf-8") as f:
        p = json.load(f)
    _prior_cache = (now, p)
    return p


_WIN_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def _parse_windows(spec: str | None) -> list[tuple[dtime, dtime]]:
    out = []
    for m in _WIN_RE.finditer(spec or ""):
        out.append((dtime(int(m.group(1)), int(m.group(2))),
                    dtime(int(m.group(3)), int(m.group(4)))))
    return out


def load_headways(refresh: bool = False) -> dict:
    """Baca line_headways → per jalur: jendela sibuk, headway, sumber.

    Key: line_id. Jalur tanpa peak_windows (mis. LRTJ) tetap terdaftar
    dengan windows=[] (estimasi datar offpeak)."""
    global _hw_cache
    now = time.time()
    if _hw_cache and not refresh and now - _hw_cache[0] < _CACHE_TTL_SEC:
        return _hw_cache[1]
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT line_id, direction, period_type, headway_min,
                              peak_windows, source_id, notes
                       FROM line_headways
                       ORDER BY line_id, period_type""")
        rows = cur.fetchall()
    finally:
        conn.close()
    out: dict[str, dict] = {}
    for line_id, direction, period, headway, windows, src, notes in rows:
        e = out.setdefault(line_id, {
            "line_id": line_id, "windows": [], "headway_peak": None,
            "headway_offpeak": None, "sources": [], "notes": [],
            "all_day": False,
        })
        if period == "peak":
            e["windows"] = _parse_windows(windows)
            e["headway_peak"] = headway
        elif period == "offpeak":
            e["headway_offpeak"] = headway
        elif period == "all":
            e["all_day"] = True
            e["headway_peak"] = e["headway_peak"] or headway
        if src and src not in e["sources"]:
            e["sources"].append(src)
        if notes and notes not in e["notes"]:
            e["notes"].append(notes)
    _hw_cache = (now, out)
    return out


def line_mode(line_id: str | None) -> str | None:
    if not line_id:
        return None
    if line_id.startswith("KRL_"):
        return "KRL"
    if line_id.startswith("LRTJ_"):
        return "LRT"
    if line_id.startswith("LRTB_"):
        return "LRT"
    if line_id.startswith("MRT_"):
        return "MRT"
    if line_id.upper() in ("BRT", "TRANSJAKARTA"):
        return "BRT"
    return None


def _confidence_tier(scope_line: str | None, priors: dict) -> str:
    tiers = priors["confidence_tiers"]["by_prefix"]
    if scope_line is None or line_mode(scope_line) == "BRT":
        return "low"
    for prefix, tier in tiers.items():
        if scope_line.startswith(prefix):
            return tier
    return "low"


def _mode_context(mode: str | None, priors: dict) -> dict | None:
    for c in priors["mode_daily_context"]:
        if c["mode_id"] in (mode, (mode or "").upper()) or \
                c["mode_id"].startswith(mode or "\x00"):
            return c
    # LRT terbagi dua operator; mode generik "LRT" tidak punya entri tunggal
    return None


def _window_state(t: dtime, windows: list[tuple[dtime, dtime]],
                  shoulder_min: int) -> str:
    if t < _NIGHT_START:
        return "night"
    if t >= dtime(23, 30):
        return "night"
    for (s, e) in windows:
        if s <= t < e:
            return "peak"
        # shoulder: shoulder_min menit sebelum mulai / sesudah selesai
        if (t.hour, t.minute) >= (0, 0):
            sh_start = _shift(s, -shoulder_min)
            sh_end = _shift(e, shoulder_min)
            if sh_start <= t < s or e <= t < sh_end:
                return "shoulder"
    return "offpeak"


def _shift(t: dtime, minutes: int) -> dtime:
    from datetime import timedelta
    dt = datetime(2000, 1, 1, t.hour, t.minute) + timedelta(minutes=minutes)
    return dt.time()


def estimate(line_id: str | None = None, mode: str | None = None,
             t: "dtime | datetime | str" = None,
             day_type: str = "weekday") -> dict:
    """Estimasi kepadatan (proksi) untuk satu jalur ATAU satu moda.

    Args:
      line_id: id jalur (mis. KRL_BOGOR_LINE). Diprioritaskan.
      mode:    "MRT"|"KRL"|"LRT"|"BRT" (untuk BRT; atau bila line tak dikenal)
      t:       dtime/datetime/"HH:MM". Default: sekarang (Asia/Jakarta).
      day_type: "weekday" | "weekend" (hari libur diperlakukan sebagai
                weekend — asumsi, ditandai di output).
    """
    priors = _load_priors()
    hw = load_headways()
    day_type = (day_type or "weekday").lower()
    if day_type not in ("weekday", "weekend"):
        day_type = "weekday"

    if isinstance(t, str):
        hh, mm = (x.zfill(2) for x in t.strip().split(":"))
        t = dtime(int(hh[:2]), int(mm[:2]))
    elif isinstance(t, datetime):
        t = t.time()
    if t is None:
        from zoneinfo import ZoneInfo
        t = datetime.now(ZoneInfo("Asia/Jakarta")).time()

    # ---------- scope ----------
    scope_line = line_id if (line_id and line_id in hw) else None
    if scope_line:
        entry = hw[scope_line]
        scope_mode = line_mode(scope_line)
        scope_name = scope_line
        windows = entry["windows"]
        src = entry["sources"][0] if entry["sources"] else None
        assumed_window = False
    else:
        m = (mode or "").upper()
        if m == "LRT":
            # tanpa line spesifik: gabungkan kedua operator LRT
            scope_mode = "LRT"
            scope_name = "LRT (Jakarta + Jabodebek)"
            wins = set()
            srcs = set()
            for lid, e in hw.items():
                if lid.startswith(("LRTJ_", "LRTB_")):
                    wins.update(e["windows"])
                    srcs.update(e["sources"])
            windows = sorted(wins)
            src = sorted(srcs)[0] if srcs else None
            assumed_window = False
        else:
            scope_mode = m or None
            scope_name = scope_mode or "Jabodetabek"
            if scope_mode == "BRT":
                windows = _parse_windows(
                    priors["window_sources"]["brt_assumed_windows"])
                src = "SRC-KRL-03 (asumsi: jendela rail Jabodetabek)"
                assumed_window = True
            elif scope_mode in ("MRT", "KRL"):
                wins = set()
                srcs = set()
                for lid, e in hw.items():
                    if line_mode(lid) == scope_mode:
                        wins.update(e["windows"])
                        srcs.update(e["sources"])
                windows = sorted(wins)
                src = sorted(srcs)[0] if srcs else None
                assumed_window = False
            else:
                windows = []
                src = None
                assumed_window = False

    # ---------- skor ----------
    ws = _window_state(t, windows,
                       priors["window_weights"]["shoulder_min"])
    ww = priors["window_weights"]
    w = {"peak": ww["peak"], "shoulder": ww["shoulder"],
         "offpeak": ww["offpeak_day"], "night": ww["night"]}[ws]
    key = "brt" if scope_mode == "BRT" else "rail"
    d = priors["day_factors"][key][day_type]
    score = round(w * d, 3)

    th = priors["thresholds"]
    if score >= th["padat_min"]:
        category = "padat"
    elif score >= th["sedang_min"]:
        category = "sedang"
    else:
        category = "longgar"

    tier = _confidence_tier(scope_line, priors)

    # ---------- basis per klaim ----------
    basis: list[dict] = []
    if windows:
        wtxt = "; ".join(f"{s:%H:%M}-{e:%H:%M}" for s, e in windows)
        if assumed_window:
            basis.append({
                "fact": f"jendela {wtxt} (ASUMSI untuk BRT — mengikuti pola "
                        "rail Jabodetabek; belum terverifikasi)",
                "source_id": "SRC-KRL-03"})
        else:
            basis.append({
                "fact": f"jendela sibuk terdokumentasi {wtxt} (rilis KCI "
                        "Jan 2026 / GAPEKA)",
                "source_id": src})
        if scope_line and hw[scope_line]["headway_peak"]:
            basis.append({
                "fact": f"headway puncak ±{hw[scope_line]['headway_peak']} mnt "
                        "(kapasitas maksimal dijadwalkan di jendela ini)",
                "source_id": src})
    else:
        basis.append({
            "fact": "tidak ada jendela sibuk terdokumentasi untuk scope ini — "
                    "estimasi datar offpeak (perlu verifikasi)",
            "source_id": None})
    if day_type == "weekend":
        df = priors["day_factors"][key]
        basis.append({
            "fact": df["note"],
            "source_id": df["source_id"]})
    ctx = _mode_context(scope_mode if scope_mode != "LRT" else "LRT_JABODEBEK",
                        priors)
    if ctx:
        basis.append({
            "fact": f"konteks skala permintaan: ±{ctx['daily_passengers']:,}"
                    f" penumpang/hari ({ctx['period']})"
                    .replace(",", "."),
            "source_id": ctx["source_id"]})

    conf_notes = {
        "medium": "jendela & headway dari rilis resmi; rasio akhir pekan "
                  "berbasis satu moda (LRT Jabodebek)",
        "low": "jendela/headway berlabel PROKSI atau asumsi; rasio akhir "
               "pekan untuk BRT belum terverifikasi",
    }
    out = {
        "model_version": MODEL_VERSION,
        "scope": {"line_id": scope_line, "mode": scope_mode,
                  "name": scope_name},
        "time": f"{t:%H:%M}",
        "day_type": day_type,
        "window_state": ws,
        "score": score,
        "category": category,
        "data_label": "proksi",
        "confidence": tier,
        "confidence_note": conf_notes.get(tier, ""),
        "basis": basis,
        "limitation": ("Pola dari proksi terdokumentasi (jendela sibuk, rasio "
                       "akhir pekan), BUKAN pengukuran load factor. Data per "
                       "jam & per stasiun tidak tersedia (data gap). Ambang "
                       "kategori provisional v1 — belum divalidasi."),
    }
    return out


def daily_profile(line_id: str | None = None, mode: str | None = None,
                  day_type: str = "weekday") -> dict:
    """Profil kepadatan 30 menit per hari (untuk dashboard/API)."""
    priors = _load_priors()
    th = priors["thresholds"]
    buckets = []
    for mins in range(0, 24 * 60, 30):
        t = dtime(mins // 60, mins % 60)
        e = estimate(line_id=line_id, mode=mode, t=t, day_type=day_type)
        buckets.append({
            "time": e["time"], "score": e["score"],
            "category": e["category"], "window_state": e["window_state"]})
    first = estimate(line_id=line_id, mode=mode, t=dtime(0, 0),
                     day_type=day_type)
    return {"model_version": MODEL_VERSION,
            "scope": first["scope"], "day_type": day_type,
            "data_label": "proksi",
            "confidence": first["confidence"],
            "thresholds": {k: th[k] for k in ("padat_min", "sedang_min")},
            "buckets": buckets}


def _time_spans(times: list[str]) -> list[str]:
    """Kelompok slot 30 mnt berurutan jadi rentang 'AWAL-AKHIR' (AKHIR =
    slot terakhir + 30 mnt; slot 'HH:MM' mencakup HH:MM–HH:MM+29)."""
    spans: list[tuple[str, str]] = []
    cur_start = cur_end = None
    for t in times:
        if cur_start is None:
            cur_start = cur_end = t
            continue
        prev_end_dt = dtime.fromisoformat(cur_end)
        next_dt = _shift(prev_end_dt, 30)
        if dtime.fromisoformat(t) == next_dt:
            cur_end = t
        else:
            spans.append((cur_start, cur_end))
            cur_start = cur_end = t
    if cur_start is not None:
        spans.append((cur_start, cur_end))
    out = []
    for s, e in spans:
        # satu slot 'HH:MM' mencakup HH:MM–(HH:MM+29); tampilkan sampai
        # batas akhir slot (+30 mnt) agar rentangnya eksplisit
        if e == "23:30":
            out.append("23:30-23:59")
        else:
            end_dt = _shift(dtime.fromisoformat(e), 30)
            out.append(f"{s}-{end_dt:%H:%M}")
    return out


def daily_summary(line_id: str | None = None, mode: str | None = None,
                  day_type: str = "weekday") -> dict:
    """Ringkasan harian: rentang jam per kategori (ringkas utk prompt LLM)."""
    prof = daily_profile(line_id=line_id, mode=mode, day_type=day_type)
    ranges = {}
    for cat in ("padat", "sedang", "longgar"):
        buckets = [b["time"] for b in prof["buckets"] if b["category"] == cat]
        ranges[cat] = _time_spans(buckets)
    return {"model_version": MODEL_VERSION, "scope": prof["scope"],
            "day_type": day_type, "data_label": "proksi",
            "confidence": prof["confidence"], "ranges": ranges,
            "note": "Rentang jam per kategori (model pola proksi; bukan "
                    "pengukuran)."}


def annotate_route_segments(segments: list[dict],
                            dep_time: "dtime | datetime" | None) -> list[dict]:
    """Tandai segmen ride hasil rute dengan estimasi kepadatan (proksi).

    `segments` = bentuk internal RouteResult (kunci: type/line/from/travel_sec/
    wait_sec). Waktu boarding tiap segmen diakumulasi dari dep_time.
    Mengembalikan list paralel (hanya segmen ride) — pemanggil menempelkan
    ke respons.
    """
    if not segments:
        return []
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    if isinstance(dep_time, datetime):
        cur = dep_time
    elif isinstance(dep_time, dtime):
        cur = datetime.now(ZoneInfo("Asia/Jakarta")).replace(
            hour=dep_time.hour, minute=dep_time.minute,
            second=0, microsecond=0)
    else:
        cur = datetime.now(ZoneInfo("Asia/Jakarta"))
    out = []
    for seg in segments:
        if seg.get("type") != "ride":
            continue
        board = cur.time()
        cur = cur.replace(second=0, microsecond=0)
        cur = cur + timedelta(seconds=seg.get("wait_sec", 0)
                              + seg.get("travel_sec", 0))
        e = estimate(line_id=seg.get("line"), t=board)
        out.append({
            "line_id": seg.get("line"),
            "mode": seg.get("mode"),
            "board_time": f"{board:%H:%M}",
            "category": e["category"],
            "score": e["score"],
            "data_label": "proksi",
            "confidence": e["confidence"],
        })
    return out


def status() -> dict:
    priors = _load_priors()
    hw = load_headways()
    return {
        "model_version": MODEL_VERSION,
        "status": priors["status"],
        "thresholds": priors["thresholds"],
        "n_lines": len(hw),
        "lines": sorted(hw.keys()),
        "category_note": "sangat_padat ditahan (tidak dihasilkan v1)",
    }

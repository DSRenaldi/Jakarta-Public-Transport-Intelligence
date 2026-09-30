# -*- coding: utf-8 -*-
"""Bangun dashboard/network_map.html: galeri peta rute resmi per moda.

Sumber: asset resmi operator (kci.id, transjakarta.co.id) + FDTJ
(data/raw/maps/MANIFEST.json). Gambar disalin ke dashboard/maps/ agar
dashboard self-contained. Peta interaktif Leaflet tetap tersedia di
dashboard/network_map_interaktif.html (lihat export_map.py).
"""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "data" / "raw" / "maps"
DASH = ROOT / "dashboard"
DM = DASH / "maps"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (file, judul tab)
TABS = [
    ("fdtj_integrasi_2026_08c.png", "Peta Integrasi"),
    ("krl_area0.png", "KRL Commuter Line"),
    ("tj_integrasi.jpg", "TransJakarta"),
    ("fdtj_mrt_2026_01.png", "MRT Jakarta"),
    ("fdtj_lrtj_2024_11.png", "LRT Jakarta"),
    ("fdtj_lrtb_2024_11.png", "LRT Jabodebek"),
]

# koridor TransJakarta (tampilkan di tab TransJakarta)
TJ_KORIDOR = [f"tj_kor{i}.jpg" for i in range(1, 15)]

# catatan tambahan per tab (label versi penting)
TAB_NOTES = {
    "fdtj_integrasi_2026_08c.png":
        "Semua moda dalam satu peta, edisi terbaru (v26.08c). Klik utk memperbesar.",
    "krl_area0.png":
        "Peta resmi KAI Commuter (kci.id), Jabodetabek & Merak. "
        "Stasiun Karet digarisabai = dinonaktifkan.",
    "tj_integrasi.jpg":
        "Peta integrasi resmi TransJakarta + 14 koridor di bawahnya "
        "(peta per koridor terbaru, 2025-2026).",
    "fdtj_mrt_2026_01.png":
        "Lin Utara-Selatan, 13 stasiun (Lebak Bulus - Bundaran HI), edisi Jan 2026.",
    "fdtj_lrtj_2024_11.png":
        "PERHATIAN: edisi Nov 2024 — hanya fase 1A (6 stasiun, s.d. Velodrome). "
        "Ekstensi fase 1B (Velodrome-Manggarai, +5 stasiun, total 11) diuji coba "
        "10 Sep 2026 dan diresmikan Presiden 16 Sep 2026 — lihat Peta Integrasi "
        "untuk jaringan terkini.",
    "fdtj_lrtb_2024_11.png":
        "Lin Cibubur (Dukuh Atas BNI - Harjamukti) & Lin Bekasi (Dukuh Atas BNI - "
        "Jatimulya), 18 stasiun. Tidak ada perubahan lin sejak 2023.",
}


def main():
    DM.mkdir(exist_ok=True)
    # salin gambar yang dipakai
    used = [f for f, _ in TABS] + TJ_KORIDOR
    for f in used:
        src = M / f
        if not src.exists():
            print(f"!! absen: {f}")
            continue
        shutil.copy2(src, DM / f)
    print(f"disalin {len(used)} gambar -> {DM}")

    html = build_html()
    out = DASH / "network_map.html"
    out.write_text(html, encoding="utf-8")
    print(f"-> {out} ({out.stat().st_size:,} B)")


def meta_line(fname: str) -> str:
    man = json.loads((M / "MANIFEST.json").read_text(encoding="utf-8"))
    info = man.get("file", {}).get(fname, {})
    src = info.get("sumber", "")
    ver = info.get("versi", "")
    parts = []
    if ver:
        parts.append(f"Versi: {ver}")
    if src:
        if src.startswith("http"):
            parts.append(f'<a href="{src}" target="_blank" rel="noopener">Sumber</a>')
        else:
            parts.append(f"Sumber: {src}")
    parts.append(f"Diakses: {man.get('diakses', '')}")
    return " &middot; ".join(parts)


def tab_section(fname: str, title: str, active: bool, idx: int) -> str:
    note = TAB_NOTES.get(fname, "")
    note_html = (f'<p class="note">{note}</p>' if note else "")
    kor_grid = ""
    if fname == "tj_integrasi.jpg":
        cells = []
        for k in TJ_KORIDOR:
            if (DM / k).exists():
                cells.append(
                    f'<figure class="kor"><img loading="lazy" src="maps/{k}" '
                    f'alt="Peta koridor {k}"><figcaption>Koridor {k[5:-4]}</figcaption></figure>'
                )
        kor_grid = (
            '<h3 class="sub">Koridor &mdash; peta rute resmi per koridor</h3>'
            f'<div class="grid">{"".join(cells)}</div>'
        )
    cls = "tab active" if active else "tab"
    hid = "" if active else " hidden"
    return f"""
<section id="tab-{idx}" class="{cls}"{hid}>
  <h2>{title}</h2>
  {note_html}
  <div class="mapbox"><img src="maps/{fname}" alt="Peta {title}"
       loading="{'eager' if active else 'lazy'}" onclick="zoom(this)"></div>
  <p class="meta">{meta_line(fname)}</p>
  {kor_grid}
</section>"""


def build_html() -> str:
    today = date.today().strftime("%d %B %Y")
    tabs_html = []
    nav = []
    for i, (f, title) in enumerate(TABS):
        tabs_html.append(tab_section(f, title, i == 0, i))
        nav.append(f'<button class="navbtn{" active" if i == 0 else ""}" '
                   f'onclick="show({i})">{title}</button>')
    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JPTI — Peta Jaringan Jabodetabek (Peta Resmi per Moda)</title>
<style>
  :root {{ --ink:#14181f; --sub:#5b6572; --line:#e3e7ec; --bg:#f6f7f9; }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; font:15px/1.55 system-ui,'Segoe UI',sans-serif;
         color:var(--ink); background:var(--bg) }}
  header {{ background:var(--ink); color:#fff; padding:18px 28px }}
  header h1 {{ margin:0; font-size:19px; font-weight:650 }}
  header p {{ margin:4px 0 0; color:#aab3bf; font-size:13px }}
  nav {{ display:flex; gap:8px; flex-wrap:wrap; padding:14px 28px 0;
         background:#fff; border-bottom:1px solid var(--line) }}
  .navbtn {{ border:1px solid var(--line); background:#fff; border-radius:999px;
             padding:7px 16px; font-size:13.5px; cursor:pointer; color:var(--sub) }}
  .navbtn:hover {{ border-color:#9aa4b1 }}
  .navbtn.active {{ background:var(--ink); color:#fff; border-color:var(--ink) }}
  main {{ max-width:1180px; margin:0 auto; padding:22px 24px 60px }}
  section.tab {{ display:none }}
  section.tab.active {{ display:block }}
  h2 {{ font-size:20px; margin:6px 0 4px }}
  .note {{ background:#fff8e6; border:1px solid #f0dca0; color:#6b5310;
           padding:10px 14px; border-radius:8px; font-size:13.5px }}
  .mapbox {{ background:#fff; border:1px solid var(--line); border-radius:12px;
             padding:10px; margin-top:12px; text-align:center }}
  .mapbox img {{ max-width:100%; max-height:78vh; border-radius:6px;
                 cursor:zoom-in; display:inline-block }}
  .meta {{ color:var(--sub); font-size:12.5px; margin-top:10px }}
  .meta a {{ color:#2456a6 }}
  .sub {{ margin:26px 0 10px; font-size:15px }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
           gap:12px }}
  .kor {{ margin:0; background:#fff; border:1px solid var(--line);
          border-radius:10px; overflow:hidden }}
  .kor img {{ width:100%; height:150px; object-fit:cover; object-position:top;
              cursor:zoom-in }}
  .kor figcaption {{ font-size:12.5px; padding:7px 10px; color:var(--sub) }}
  footer {{ text-align:center; color:var(--sub); font-size:12.5px;
            padding:18px; border-top:1px solid var(--line) }}
  #zoomer {{ position:fixed; inset:0; background:rgba(10,12,16,.92);
             display:none; place-items:center; z-index:99; cursor:zoom-out }}
  #zoomer.open {{ display:grid }}
  #zoomer img {{ max-width:96vw; max-height:96vh; box-shadow:0 8px 40px rgba(0,0,0,.5) }}
</style>
</head>
<body>
<header>
  <h1>JPTI &mdash; Peta Jaringan Jabodetabek</h1>
  <p>Peta rute resmi per moda &middot; dibuat {today} &middot;
     MRT Jakarta, KRL, LRT Jakarta, LRT Jabodebek, TransJakarta</p>
</header>
<nav>{''.join(nav)}</nav>
<main>{''.join(tabs_html)}</main>
<footer>
  Sumber: situs resmi operator &amp; FDTJ (Transport for Jakarta) &mdash;
  detail per file ada di <code>data/raw/maps/MANIFEST.json</code>.
  Peta interaktif berbasis data (Leaflet):
  <a href="network_map_interaktif.html">buka di sini</a>.
</footer>
<div id="zoomer" onclick="this.classList.remove('open')">
  <img id="zoomimg" alt="">
</div>
<script>
function show(i) {{
  document.querySelectorAll('section.tab').forEach((s, j) =>
    s.classList.toggle('active', i === j));
  document.querySelectorAll('.navbtn').forEach((b, j) =>
    b.classList.toggle('active', i === j));
  window.scrollTo({{top: 0, behavior: 'smooth'}});
}}
function zoom(img) {{
  document.getElementById('zoomimg').src = img.src;
  document.getElementById('zoomer').classList.add('open');
}}
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') document.getElementById('zoomer').classList.remove('open');
}});
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()

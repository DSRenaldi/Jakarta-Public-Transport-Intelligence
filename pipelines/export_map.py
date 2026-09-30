# -*- coding: utf-8 -*-
"""
Ekspor jaringan ke GeoJSON + bangun dashboard/network_map.html (Leaflet).

Lapisan: line (warna per moda), stasiun (dot), hub transfer (ring).
Jalankan SETELAH ingest_gtfs + ingest_rail + build_transfers.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

MODE_COLORS = {"MRT": "#e40028", "LRT": "#00a651", "KRL": "#f5a623",
               "BRT": "#0072bc"}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    conn = connect()
    cur = conn.cursor()

    # line geometries
    cur.execute("""
        SELECT lg.line_id, l.mode_id, l.canonical_name,
               ST_AsGeoJSON(lg.geometry)
        FROM line_geometries lg JOIN lines l USING (line_id)
        WHERE lg.geometry IS NOT NULL
    """)
    lines = []
    for lid, mode, name, gj in cur.fetchall():
        g = json.loads(gj)
        lines.append({
            "type": "Feature",
            "properties": {"line_id": lid, "mode": mode, "name": name,
                           "color": MODE_COLORS.get(mode, "#666")},
            "geometry": g,
        })

    # stops (rail penuh + BRT hanya yang punya transfer agar peta tidak berat)
    cur.execute("""
        SELECT stop_id_internal, mode_id, canonical_name, display_name,
               ST_AsGeoJSON(geometry)
        FROM stops
        WHERE geometry IS NOT NULL
          AND (mode_id <> 'BRT' OR stop_id_internal IN (
                 SELECT DISTINCT from_stop_id FROM transfers
                 UNION SELECT DISTINCT to_stop_id FROM transfers))
    """)
    stops = []
    for sid, mode, cname, dname, gj in cur.fetchall():
        stops.append({
            "type": "Feature",
            "properties": {
                "stop_id": sid, "mode": mode, "name": cname,
                "display": dname or cname,
                "color": MODE_COLORS.get(mode, "#666"),
                "is_brt": mode == "BRT",
            },
            "geometry": json.loads(gj),
        })

    # transfer edges (rail<->non-rail)
    cur.execute("""
        SELECT a.canonical_name, b.canonical_name,
               ST_AsGeoJSON(ST_MakeLine(a.geometry, b.geometry))
        FROM transfers t
        JOIN stops a ON a.stop_id_internal = t.from_stop_id
        JOIN stops b ON b.stop_id_internal = t.to_stop_id
        WHERE t.type = 'intermodal'
          AND a.mode_id IN ('MRT','LRT','KRL')
          AND a.geometry IS NOT NULL AND b.geometry IS NOT NULL
    """)
    xfers = []
    for an, bn, gj in cur.fetchall():
        xfers.append({
            "type": "Feature",
            "properties": {"from": an, "to": bn},
            "geometry": json.loads(gj),
        })

    conn.close()
    geo = {
        "type": "FeatureCollection",
        "features": lines + stops + xfers,
    }
    (ROOT / ".work" / "network.geojson").write_text(
        json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    print(f"geojson: {len(lines)} line, {len(stops)} stop, {len(xfers)} transfer")

    html = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<title>JPTI — Peta Jaringan (Fase 2)</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html,body,#map{height:100%;margin:0}
  .panel{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;
         padding:10px 14px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.25);
         font:13px/1.5 system-ui;max-width:320px}
  .panel h1{font-size:14px;margin:0 0 6px}
  .sw{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px}
  label{display:block;cursor:pointer}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <h1>JPTI — Jaringan Jabodetabek</h1>
  <label><input type="checkbox" id="l-lines" checked>
    <span class="sw" style="background:#e40028"></span>MRT</label>
  <label><input type="checkbox" id="l-lrt" checked>
    <span class="sw" style="background:#00a651"></span>LRT (Jakarta + Jabodebek)</label>
  <label><input type="checkbox" id="l-krl" checked>
    <span class="sw" style="background:#f5a623"></span>KRL</label>
  <label><input type="checkbox" id="l-brt" checked>
    <span class="sw" style="background:#0072bc"></span>TransJakarta (halte di hub)</label>
  <label><input type="checkbox" id="l-xfer" checked>
    <span class="sw" style="background:#888"></span>Transfer antarmoda</label>
  <label><input type="checkbox" id="l-stops" checked> Stasiun</label>
  <div style="margin-top:6px;color:#666" id="count"></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const geo = __GEOJSON__;
const map = L.map('map').setView([-6.22, 106.83], 11);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  {attribution: '&copy; OpenStreetMap contributors', maxZoom: 19}).addTo(map);
const byMode = {
  MRT: L.layerGroup(), LRT: L.layerGroup(),
  KRL: L.layerGroup(), BRT: L.layerGroup(),
};
const xfers = L.layerGroup();
const stopsLayer = {
  MRT: L.layerGroup(), LRT: L.layerGroup(),
  KRL: L.layerGroup(), BRT: L.layerGroup(),
};
for (const f of geo.features) {
  const p = f.properties;
  const isLine = f.geometry.type === 'LineString'
              || f.geometry.type === 'MultiLineString';
  if (isLine) {
    if (p.mode) byMode[p.mode].addLayer(
      L.geoJSON(f, {style: {color: p.color, weight: 3.5, opacity: .85}}));
    else xfers.addLayer(
      L.geoJSON(f, {style: {color: '#888', weight: 1.5, dashArray: '4 4', opacity: .7}}));
  } else if (f.geometry.type === 'Point') {
    const m = p.mode;
    const marker = L.circleMarker(f.geometry.coordinates,
      p.is_brt ? {radius: 3, color: p.color, weight: 1, fillOpacity: .5}
               : {radius: 5.5, color: '#fff', weight: 1.5, fillColor: p.color, fillOpacity: 1});
    marker.bindTooltip(`${p.display} <span style="color:#888">[${m}]</span>`);
    stopsLayer[m].addLayer(marker);
  }
}
function apply() {
  const on = id => document.getElementById(id).checked;
  if (on('l-lines')) map.addLayer(byMode.MRT); else map.removeLayer(byMode.MRT);
  if (on('l-lrt'))   map.addLayer(byMode.LRT); else map.removeLayer(byMode.LRT);
  if (on('l-krl'))   map.addLayer(byMode.KRL); else map.removeLayer(byMode.KRL);
  if (on('l-brt'))   map.addLayer(byMode.BRT); else map.removeLayer(byMode.BRT);
  if (on('l-xfer'))  map.addLayer(xfers);   else map.removeLayer(xfers);
  for (const m of ['MRT', 'LRT', 'KRL', 'BRT']) {
    const show = on('l-stops') && (m !== 'BRT' || on('l-brt'));
    if (show) map.addLayer(stopsLayer[m]); else map.removeLayer(stopsLayer[m]);
  }
  document.getElementById('count').textContent =
    `${geo.features.length} fitur (rail + halte di hub transfer)`;
}
for (const id of ['l-lines', 'l-lrt', 'l-krl', 'l-brt', 'l-xfer', 'l-stops'])
  document.getElementById(id).addEventListener('change', apply);
apply();
</script>
</body>
</html>"""
    out = (ROOT / "dashboard" / "network_map_interaktif.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html.replace("__GEOJSON__", json.dumps(geo, ensure_ascii=False)),
                   encoding="utf-8")
    print(f"-> {out} ({out.stat().st_size:,} B)")


if __name__ == "__main__":
    main()

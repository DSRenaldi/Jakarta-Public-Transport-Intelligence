# -*- coding: utf-8 -*-
"""
Bangun dashboard historis minimal (Fase 1) dari data/processed/ridership_monthly.csv.

Output: dashboard/index.html (self-contained; ECharts via CDN; data ter-embed).
Menampilkan: tren bulanan 2026 (BPS), tren MRT panjang (SDI), perbandingan
tahunan antar moda, titik data KRL & LRT Jabodebek, plus panel sumber & freshness.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "processed" / "ridership_monthly.csv"

rows = list(csv.DictReader(open(SRC, encoding="utf-8")))

# ---------- struktur data ----------
def months(series_ids, start="2026-01", end="2026-07"):
    """Bulanan 2026 untuk series BPS (MRT, LRT Jakarta, TJ). Kunci = YYYY-MM."""
    out = defaultdict(dict)
    for r in rows:
        if r["series_id"] in series_ids and r["period_type"] == "month" and start <= r["period_start"][:7] <= end:
            out[r["series_id"]][r["period_start"][:7]] = int(r["passenger_count"])
    return out

bps2026 = months({"mrt_bps_tapin", "lrtj_bps", "tj_bps_tapin"})
m2026 = months({"mrt_sdi_dishub"})
sdi = [
    {"d": r["period_start"], "v": int(r["passenger_count"]), "n": r["notes"]}
    for r in rows if r["series_id"] == "mrt_sdi_dishub"
]
sdi.sort(key=lambda x: x["d"])

annual = defaultdict(dict)
for r in rows:
    if r["period_type"] == "year":
        annual[r["series_id"]][r["period_start"][:4]] = int(r["passenger_count"])
# MRT 2023/2024 dari total SDI
sdi_year = defaultdict(int)
for r in rows:
    if r["series_id"] == "mrt_sdi_dishub":
        sdi_year[r["period_start"][:4]] += int(r["passenger_count"])
mrt_annual = {y: sdi_year[y] for y in ("2023", "2024")}
mrt_annual["2025"] = 46_449_629  # resmi operator (juga ada di CSV series mrt_operator)

krl = [
    {"d": r["period_start"], "end": r["period_end"], "v": int(r["passenger_count"]),
     "t": r["period_type"], "n": r["notes"], "sec": r["provenance"] == "sekunder"}
    for r in rows if r["series_id"] == "krl_kci"
]
lrtb = [
    {"d": r["period_start"], "end": r["period_end"], "v": int(r["passenger_count"]),
     "t": r["period_type"], "n": r["notes"], "sec": r["provenance"] == "sekunder",
     "approx": r["is_approx"] == "true"}
    for r in rows if r["series_id"] == "lrtb_kai"
]

# panel sumber & freshness
sources = []
seen = set()
for r in rows:
    key = (r["series_id"], r["source_id"])
    if key in seen:
        continue
    seen.add(key)
    sources.append({
        "series": r["series_id"],
        "source_id": r["source_id"],
        "source": r["source_name"],
        "definition": r["definition_ref"],
        "published": r["published_at"],
        "retrieved": r["retrieved_at"],
        "provenance": r["provenance"],
        "label": r["data_label"],
    })

payload = {
    "asOf": "2026-09-29",
    "bps2026": {
        "months": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
        "mrt": [bps2026["mrt_bps_tapin"].get(m) for m in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]],
        "lrtj": [bps2026["lrtj_bps"].get(m) for m in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]],
        "tj": [bps2026["tj_bps_tapin"].get(m) for m in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]],
        "tjMonths": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"],
    },
    "mrtSdi": {"dates": [x["d"] for x in sdi], "values": [x["v"] for x in sdi], "notes": {x["d"]: x["n"] for x in sdi if x["n"]}},
    "mrt2026": {"dates": [k for k in sorted(m2026["mrt_sdi_dishub"])], "values": [m2026["mrt_sdi_dishub"][k] for k in sorted(m2026["mrt_sdi_dishub"])]},
    "annual": {
        "years": ["2020", "2021", "2022", "2023", "2024", "2025"],
        "lrtj": [annual["lrtj_annual"].get(y) for y in ["2020", "2021", "2022", "2023", "2024", "2025"]],
        "mrt": [mrt_annual.get(y) for y in ["2020", "2021", "2022", "2023", "2024", "2025"]],
        "tj": [annual["tj_bps_annual"].get(y) or annual["tj_operator"].get(y) for y in ["2020", "2021", "2022", "2023", "2024", "2025"]],
        "krl": [annual["krl_kci"].get(y) for y in ["2020", "2021", "2022", "2023", "2024", "2025"]],
    },
    "krl": krl,
    "lrtb": lrtb,
    "sources": sources,
    "notes": {
        "mrtAnnual": "MRT 2023/2024 = total bulanan SDI (definisi Dishub); 2025 = resmi operator (46.449.629). Definisi berbeda antar series — jangan dijumlahkan lintas series.",
        "tjAnnual": "TJ 2024 = operator (371,4 jt); 2025 = BPS (414,35 jt). Definisi berbeda.",
        "krl": "KRL: hanya titik data yang dipublikasikan kci.id (bulanan parsial, kuartal, semester, tahunan). Bukan seri lengkap.",
        "lrtb": "LRT Jabodebek: titik data dari rilis KAI; S1-2025 angka pembulatan ('>13 juta').",
    },
}

data_json = json.dumps(payload, ensure_ascii=False)

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JPTI — Dashboard Tren Historis (Fase 1)</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  :root { --bg:#0e1117; --panel:#161b24; --ink:#e6e9ef; --mut:#8b93a7; --acc:#4f9cf9; --line:#232a37; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif; }
  header { padding:28px 32px 12px; }
  header h1 { margin:0 0 4px; font-size:20px; letter-spacing:.2px; }
  header p { margin:0; color:var(--mut); font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(12,1fr); gap:16px; padding:16px 32px 8px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 16px 8px; grid-column:span 12; }
  .card h2 { margin:0 0 2px; font-size:15px; }
  .card .sub { color:var(--mut); font-size:12px; margin:0 0 8px; }
  .chart { width:100%; height:300px; }
  .chart.tall { height:360px; }
  .half { grid-column:span 6; }
  @media (max-width:980px){ .half { grid-column:span 12; } }
  .src { margin:4px 0 12px; border-top:1px dashed var(--line); padding-top:8px; font-size:11.5px; color:var(--mut); }
  .src b { color:var(--ink); font-weight:600; }
  .badge { display:inline-block; border:1px solid var(--line); border-radius:6px; padding:0 6px; margin-right:6px; font-size:11px; }
  .badge.sec { border-color:#7a5b1e; color:#e0b45f; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th,td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { color:var(--mut); font-weight:600; }
  footer { padding:8px 32px 32px; color:var(--mut); font-size:12px; }
  code { background:#0b0e13; padding:1px 5px; border-radius:4px; font-size:11.5px; }
</style>
</head>
<body>
<header>
  <h1>JPTI — Dashboard Tren Penumpang Historis <span style="color:var(--acc)">(Fase 1)</span></h1>
  <p>Data per __ASOF__ · Semua angka berlabel sumber &amp; definisi · Granularitas tertinggi publik: bulanan (riil: harian 2023 TransJakarta — file sumber rusak, lihat registry)</p>
</header>
<div class="grid">

  <div class="card half">
    <h2>MRT Jakarta — 2026 (definisi tap-in BPS)</h2>
    <p class="sub">Jan–Jun 2026 · sumber: tabel statistik BPS DKI (last update 7 Agu 2026)</p>
    <div id="c-mrt" class="chart"></div>
    <div class="src"><b>Sumber:</b> SRC-BPS-02 (BPS DKI Jakarta) · definisi: tap-in pintu masuk stasiun keberangkatan/NFC · diambil __ASOF__ · label <span class="badge">historis</span></div>
  </div>
  <div class="card half">
    <h2>LRT Jakarta — 2026 (definisi tap-in BPS)</h2>
    <p class="sub">Jan–Jun 2026 · sumber: tabel statistik BPS DKI</p>
    <div id="c-lrtj" class="chart"></div>
    <div class="src"><b>Sumber:</b> SRC-BPS-02 (BPS DKI Jakarta) · label <span class="badge">historis</span> · <b>Catatan:</b> koridor baru Kelapa Gading–Manggarai diresmikan 16 Sep 2026 (setelah periode ini)</div>
  </div>
  <div class="card half">
    <h2>TransJakarta — 2026 (definisi tap-in BPS)</h2>
    <p class="sub">Jan–Jul 2026 · Jul 2026 dari rilis BPS via media (sekunder, dibulatkan)</p>
    <div id="c-tj" class="chart"></div>
    <div class="src"><b>Sumber:</b> SRC-BPS-02 (Jan–Jun) + SRC-SEC-06 (Jul, sekunder) · label <span class="badge">historis</span> <span class="badge sec">sekunder (Jul)</span></div>
  </div>
  <div class="card half">
    <h2>Total bulanan 2026 — MRT + LRT Jakarta + TransJakarta</h2>
    <p class="sub">Seri BPS yang konsisten (Jan–Jun) · jangan dicampur dengan series definisi lain</p>
    <div id="c-total" class="chart"></div>
    <div class="src"><b>Sumber:</b> SRC-BPS-02 (ketiga moda, definisi sama) · label <span class="badge">historis</span></div>
  </div>

  <div class="card">
    <h2>MRT Jakarta — Tren Panjang Jan 2023 – Jun 2026 (Satu Data Indonesia / Dishub)</h2>
    <p class="sub">Definisi berbeda dari BPS (perbandingan: Apr 2026 SDI 4.347.308 vs BPS 3.879.260). Titik berwarna = ada catatan kualitas.</p>
    <div id="c-sdi" class="chart tall"></div>
    <div class="src"><b>Sumber:</b> SRC-MRT-01 (data.go.id / satudata.jakarta.go.id, modif 3 Sep 2026) · label <span class="badge">historis</span> ·
    <b>Kualitas:</b> Jan–Mar 2023 anomali rendah; Jul 2025 = Jun 2025 (dugaan duplikat)</div>
  </div>

  <div class="card">
    <h2>Perbandingan Tahunan antar Moda (2020–2025)</h2>
    <p class="sub">Setiap series memakai definisi &amp; sumbernya sendiri (lihat catatan bawah grafik) — untuk orientasi skala, bukan perbandingan resmi.</p>
    <div id="c-annual" class="chart tall"></div>
    <div class="src"><b>Sumber:</b> LRT Jakarta: Wikipedia (ref BPK/BPS, <span class="badge sec">sekunder</span>) · MRT 2023/24: total SDI, 2025: resmi operator · TJ 2024: operator, 2025: BPS (<span class="badge sec">sekunder</span>) · KRL 2025: Antara (<span class="badge sec">sekunder</span>) · LRT Jabodebek: belum ada angka tahunan resmi</div>
  </div>

  <div class="card half">
    <h2>KRL Commuter Line — titik data yang dipublikasikan (kci.id)</h2>
    <p class="sub">Tidak ada seri bulanan lengkap; hanya periode yang dirilis operator.</p>
    <div id="c-krl" class="chart tall"></div>
    <div class="src"><b>Sumber:</b> SRC-KRL-01 (kci.id) + SRC-SEC-05 (FY2025, <span class="badge sec">sekunder</span>) · definisi "volume pengguna" Jabodetabek</div>
  </div>
  <div class="card half">
    <h2>LRT Jabodebek — titik data (rilis KAI)</h2>
    <p class="sub">Ketersediaan ridership terbaik di antara moda non-BPS (rilis kumulatif berkala).</p>
    <div id="c-lrtb" class="chart tall"></div>
    <div class="src"><b>Sumber:</b> SRC-LRTB-05 (kai.id / lrtjabodebek.kai.id / sosmed) + SRC-SEC-07 (rincian Q1, <span class="badge sec">sekunder</span>)</div>
  </div>

  <div class="card">
    <h2>Registri Sumber &amp; Freshness (semua series di dashboard ini)</h2>
    <p class="sub"><code>provenance</code>: primer = terbit operator/instansi; sekunder = dikutip media. <code>label</code>: mengikuti aturan jawaban proyek.</p>
    <div style="overflow-x:auto"><table id="t-src">
      <thead><tr><th>Series</th><th>Source ID</th><th>Sumber</th><th>Definisi (ringkas)</th><th>Published</th><th>Diambil</th><th>Provenance</th><th>Label</th></tr></thead>
      <tbody></tbody>
    </table></div>
  </div>

</div>
<footer>
  Fase 1 — Fondasi data &amp; dashboard historis · dibangun dari <code>data/processed/ridership_monthly.csv</code> (87 baris, 10 series) ·
  Keterbatasan: OD &amp; data per jam <code>unavailable</code> publik; real-time tidak ada; LRT Jabodebek tidak ada angka tahunan resmi.
</footer>
<script>
const D = __DATA__;
const fmt = v => v == null ? '–' : v.toLocaleString('id-ID');
const ax = { axisLine:{lineStyle:{color:'#3a4356'}}, axisLabel:{color:'#8b93a7'}, splitLine:{lineStyle:{color:'#1d2430'}} };
function base(title){ return {
  backgroundColor:'transparent',
  tooltip:{ trigger:'axis', valueFormatter:fmt, backgroundColor:'#0b0e13', borderColor:'#232a37', textStyle:{color:'#e6e9ef'} },
  grid:{ left:64, right:24, top:32, bottom:36 },
  xAxis:{ type:'category', ...ax }, yAxis:{ type:'value', ...ax, axisLabel:{color:'#8b93a7', formatter:v=> v>=1e6? (v/1e6)+'jt' : (v/1e3)+'rb'} },
};}
function mk(id, opt){ const c = echarts.init(document.getElementById(id), null, {renderer:'canvas'}); c.setOption(opt); window.addEventListener('resize', ()=>c.resize()); }

// 2026 per moda (BPS)
const b = D.bps2026;
mk('c-mrt', {...base(), xAxis:{type:'category',...ax,data:b.months}, yAxis:base().yAxis,
  series:[{type:'line',smooth:true,data:b.mrt,areaStyle:{opacity:.15},lineStyle:{width:2.5,color:'#4f9cf9'},itemStyle:{color:'#4f9cf9'}}]});
mk('c-lrtj', {...base(), xAxis:{type:'category',...ax,data:b.months}, yAxis:base().yAxis,
  series:[{type:'line',smooth:true,data:b.lrtj,areaStyle:{opacity:.15},lineStyle:{width:2.5,color:'#3ecf8e'},itemStyle:{color:'#3ecf8e'}}]});
const tjOpt = {...base(), xAxis:{type:'category',...ax,data:b.tjMonths}, yAxis:base().yAxis,
  series:[{type:'line',smooth:true,data:b.tj,areaStyle:{opacity:.15},lineStyle:{width:2.5,color:'#f2b544'},itemStyle:{color:'#f2b544'},
    markPoint:{data:[{coord:['2026-07', b.tj[6]], value:'sekunder', itemStyle:{color:'#7a5b1e'}, label:{fontSize:10}}]}}]};
mk('c-tj', tjOpt);
const totalM = b.months.map((m,i)=> (b.mrt[i]||0)+(b.lrtj[i]||0)+(b.tj[i]||0));
mk('c-total', {...base(), xAxis:{type:'category',...ax,data:b.months}, yAxis:base().yAxis,
  series:[{type:'bar',data:totalM,itemStyle:{color:'#7c6cf0',borderRadius:[4,4,0,0]}, barWidth:'55%'},
          {type:'line',data:[...b.mrt,...[null]],lineStyle:{type:'dashed',color:'#4f9cf9',width:1.5},itemStyle:{color:'#4f9cf9'},name:'MRT'},
          {type:'line',data:[...b.tj.slice(0,6),null],lineStyle:{type:'dashed',color:'#f2b544',width:1.5},itemStyle:{color:'#f2b544'},name:'TJ'}],
  legend:{textStyle:{color:'#8b93a7'},top:0}});

// MRT SDI panjang
const sdi = D.mrtSdi;
const anom = d => !!D.mrtSdi.notes[d];
mk('c-sdi', {...base(), xAxis:{type:'category',...ax,data:sdi.dates,axisLabel:{color:'#8b93a7',rotate:45}}, yAxis:base().yAxis,
  series:[{type:'line',smooth:true,data:sdi.values,lineStyle:{width:2.5,color:'#4f9cf9'},itemStyle:{color:'#4f9cf9'},
    areaStyle:{opacity:.12},
    markPoint:{ data: sdi.dates.filter(anom).map(d=>({coord:[d, sdi.values[sdi.dates.indexOf(d)]], value:'?', itemStyle:{color:'#e0654f'}, label:{show:false}})),
      symbolSize:14 }}]});

// tahunan
const a = D.annual;
mk('c-annual', {...base(), xAxis:{type:'category',...ax,data:a.years}, yAxis:base().yAxis,
  series:[
    {name:'MRT (SDI/operator)',type:'bar',data:a.mrt,itemStyle:{color:'#4f9cf9',borderRadius:[4,4,0,0]}},
    {name:'LRT Jakarta (sekunder)',type:'bar',data:a.lrtj,itemStyle:{color:'#3ecf8e',borderRadius:[4,4,0,0]}},
    {name:'TransJakarta (operator/BPS)',type:'bar',data:a.tj,itemStyle:{color:'#f2b544',borderRadius:[4,4,0,0]}},
    {name:'KRL (sekunder)',type:'bar',data:a.krl,itemStyle:{color:'#c678dd',borderRadius:[4,4,0,0]}}
  ],
  legend:{textStyle:{color:'#8b93a7'},top:0}});

// KRL titik
const krl = D.krl;
const krlLabels = krl.map(k=> `${k.d.slice(0,4)}-${k.d.slice(5,7)}${k.t!=='month'?' ('+k.t+')':''}`);
mk('c-krl', {...base(), xAxis:{type:'category',...ax,data:krlLabels,axisLabel:{color:'#8b93a7',rotate:30}}, yAxis:base().yAxis,
  series:[{type:'bar',data:krl.map(k=>({value:k.v,itemStyle:{color:k.sec?'#8a6d2f':'#c678dd',borderRadius:[4,4,0,0]}})), barWidth:'50%'}],
  tooltip:{...base().tooltip, valueFormatter:fmt}});

// LRT Jabodebek titik
const lb = D.lrtb;
const lbLabels = lb.map(k=> `${k.d.slice(0,4)}-${k.d.slice(5,7)}${k.t!=='month'?' ('+k.t+')':''}${k.approx?' ~':''}`);
mk('c-lrtb', {...base(), xAxis:{type:'category',...ax,data:lbLabels,axisLabel:{color:'#8b93a7',rotate:30}}, yAxis:base().yAxis,
  series:[{type:'bar',data:lb.map(k=>({value:k.v,itemStyle:{color:k.sec?'#8a6d2f':'#3ecf8e',borderRadius:[4,4,0,0]}})), barWidth:'50%'}],
  tooltip:{...base().tooltip, valueFormatter:fmt}});

// tabel sumber
const tb = document.querySelector('#t-src tbody');
D.sources.forEach(s=>{
  const tr = document.createElement('tr');
  tr.innerHTML = `<td><code>${s.series}</code></td><td>${s.source_id}</td><td>${s.source}</td><td>${s.definition}</td><td>${s.published||'–'}</td><td>${s.retrieved}</td><td>${s.provenance==='sekunder'?'<span class="badge sec">sekunder</span>':'primer'}</td><td>${s.label}</td>`;
  tb.appendChild(tr);
});
</script>
</body>
</html>
"""

html = HTML.replace("__DATA__", data_json).replace("__ASOF__", payload["asOf"])
out = ROOT / "dashboard" / "index.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"OK: {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")

import { useEffect, useMemo, useRef, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { getRidership, getLines } from '../api.js'
import { MODE_COLORS } from '../lib.js'

const MODES = ['MRT', 'KRL', 'LRT', 'BRT']
const FILTER_ORDER = ['MRT', 'LRT', 'KRL', 'BRT']
const MODE_LABEL = { MRT: 'MRT Jakarta', KRL: 'KRL Commuter Line', LRT: 'LRT Jakarta & Jabodebek', BRT: 'TransJakarta' }

function monthLabel(ys) {
  const [y, m] = ys.split('-').map(Number)
  const nama = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'][m - 1]
  return `${nama} ${y}`
}

function seriesForMode(rows, mode) {
  // semua series bulanan per moda; label = series_id ringkas
  const byId = {}
  for (const r of rows) {
    if (r.mode_id !== mode || r.period_type !== 'month') continue
    byId[r.series_id] ??= []
    byId[r.series_id].push({ x: r.period_start, y: r.passenger_count, src: r.source_id, def: r.definition_ref })
  }
  return Object.entries(byId).map(([id, pts]) => ({ id, pts: pts.sort((a, b) => a.x.localeCompare(b.x)) }))
}

function StatCard({ mode, latest }) {
  const c = MODE_COLORS[mode]
  if (!latest) return null
  return (
    <div className="stat" style={{ borderTop: `3px solid ${c}` }}>
      <span className="stat-mode">{MODE_LABEL[mode]}</span>
      <span className="stat-val">{latest.y.toLocaleString('id-ID')}</span>
      <span className="stat-sub">
        {monthLabel(latest.x)} · <code>{latest.series}</code> · historis
      </span>
    </div>
  )
}

export default function Dashboard() {
  // Satu-satunya sumber kebenaran filter moda di halaman ini ('all' = Semua).
  const [mode, setMode] = useState('all')
  const [rows, setRows] = useState(null)
  const [lines, setLines] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const seq = useRef(0)

  // Fetch ulang hanya saat filter moda berubah (deps [mode]) — tanpa mode
  // yang sama tidak ada fetch duplikat. Guard `seq` membuang respons usang
  // jika pengguna ganti filter cepat (respons lama tak boleh menimpa data baru).
  useEffect(() => {
    const id = ++seq.current
    const m = mode === 'all' ? null : mode
    setBusy(true)
    setError(null)
    Promise.all([getRidership(m, 'month'), getLines(m)])
      .then(([riders, net]) => {
        if (id !== seq.current) return
        setRows(riders.rows)
        setLines(net.lines)
        setBusy(false)
      })
      .catch((e) => {
        if (id !== seq.current) return
        setError(e.message)
        setBusy(false)
      })
  }, [mode])

  const perMode = useMemo(() => {
    if (!rows) return {}
    return Object.fromEntries(MODES.map((m) => [m, seriesForMode(rows, m)]))
  }, [rows])

  const latestPerMode = useMemo(() => {
    const out = {}
    for (const m of MODES) {
      let best = null
      for (const s of perMode[m] || []) {
        const last = s.pts[s.pts.length - 1]
        if (last && (!best || last.x > best.x)) best = { ...last, series: s.id }
      }
      out[m] = best
    }
    return out
  }, [perMode])

  const lineCountByMode = useMemo(() => {
    const out = {}
    for (const l of lines || []) out[l.mode_id] = (out[l.mode_id] || 0) + 1
    return out
  }, [lines])

  const shownModes = mode === 'all' ? MODES : [mode]
  const shownLines = mode === 'all' ? [] : (lines || []).filter((l) => l.mode_id === mode)

  if (error) return <div className="page"><p className="error">Gagal memuat data: {error}</p></div>
  if (!rows) return <div className="page"><p className="note">Memuat data ridership…</p></div>

  const chart = (mode) => {
    const series = (perMode[mode] || []).map((s) => ({
      name: s.id,
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      data: s.pts.map((p) => ({
        value: [p.x, p.y],
        tooltip: {
          formatter: `${monthLabel(p.x)}<br/>${p.y.toLocaleString('id-ID')} orang<br/><i>${p.id} · ${p.src}</i>`,
        },
      })),
      connectNulls: true,
    }))
    return {
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 62, right: 14, top: 18, bottom: 34 },
      xAxis: {
        type: 'category',
        data: [...new Set(series.flatMap((s) => s.data.map((d) => d.value[0])))].sort(),
        axisLabel: { formatter: (v) => monthLabel(v).replace(' 20', "'") },
      },
      yAxis: { type: 'value', axisLabel: { formatter: (v) => (v / 1e6).toFixed(0) + ' jt' } },
      series,
    }
  }

  return (
    <div className="page">
      <div className="mode-filter">
        <span className="mode-filter-label">Moda:</span>
        <div className="chips">
          <button className={`chip${mode === 'all' ? ' on' : ''}`} onClick={() => setMode('all')}>Semua</button>
          {FILTER_ORDER.map((m) => (
            <button key={m} className={`chip${mode === m ? ' on' : ''}`} onClick={() => setMode(m)}>
              <i style={{ background: MODE_COLORS[m] }} />{m}
            </button>
          ))}
        </div>
        {busy && <span className="note">Memuat…</span>}
      </div>

      <section className="card">
        <h2>
          {mode === 'all'
            ? 'Penumpang per moda — data historis'
            : `Penumpang ${MODE_LABEL[mode]} — data historis`}
        </h2>
        <p className="note">
          Sumber: BPS DKI Jakarta (tabel transportasi), KCI, KAI, operator TransJakarta, SDI
          Dishub — label <b>historis</b>, tiap baris punya <code>source_id</code> + definisi
          (hover titik untuk detail). Definisi antar-sumber bisa berbeda (mis. tap-in BPS vs
          perhitungan operator).
        </p>
        <div className="stats" style={shownModes.length === 1 ? { gridTemplateColumns: '1fr' } : undefined}>
          {shownModes.map((m) => <StatCard key={m} mode={m} latest={latestPerMode[m]} />)}
        </div>
      </section>

      <section className="card">
        <h2>Jaringan moda</h2>
        <p className="note">
          Jalur dari database jaringan (GTFS TransJakarta + rel OSM) — data jaringan,
          bukan angka penumpang. Daftar ikut filter moda di atas.
        </p>
        {mode === 'all' ? (
          <div className="mode-legend">
            {MODES.map((m) => (
              <span key={m} className="legend-item">
                <i style={{ background: MODE_COLORS[m] }} />
                {MODE_LABEL[m]} · {lineCountByMode[m] ?? 0} jalur
              </span>
            ))}
          </div>
        ) : shownLines.length === 0 ? (
          <p className="note">Tidak ada jalur untuk moda ini.</p>
        ) : (
          <div className="line-list">
            {shownLines.map((l) => (
              <span key={l.line_id} className="chip" title={l.canonical_name}>
                {l.display_name || l.canonical_name}
                {l.stop_count ? ` · ${l.stop_count} stasiun` : ''}
              </span>
            ))}
          </div>
        )}
      </section>

      <div className="dash-grid" style={shownModes.length === 1 ? { gridTemplateColumns: '1fr' } : undefined}>
        {shownModes.map((m) => (
          <section key={m} className="card chart-card">
            <h3 style={{ color: MODE_COLORS[m] }}>{MODE_LABEL[m]}</h3>
            {(perMode[m] || []).length === 0
              ? <p className="note">Tidak ada series bulanan.</p>
              : <ReactECharts option={chart(m)} style={{ height: 260 }} notMerge />}
          </section>
        ))}
      </div>
    </div>
  )
}

import { useEffect, useMemo, useRef, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { getRidership, getLines } from '../api.js'
import { MODE_COLORS } from '../lib.js'

const MODES = ['MRT', 'KRL', 'LRT', 'BRT']
const FILTER_ORDER = ['MRT', 'LRT', 'KRL', 'BRT']
const MODE_LABEL = { MRT: 'MRT Jakarta', KRL: 'KRL Commuter Line', LRT: 'LRT Jakarta & Jabodebek', BRT: 'TransJakarta' }

function monthLabel(value) {
  const [year, month] = value.split('-').map(Number)
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
  return `${names[month - 1]} ${year}`
}

function seriesForMode(rows, mode) {
  const grouped = {}
  for (const row of rows) {
    if (row.mode_id !== mode || row.period_type !== 'month') continue
    grouped[row.series_id] ??= []
    grouped[row.series_id].push({ x: row.period_start, y: row.passenger_count, src: row.source_id, def: row.definition_ref })
  }
  return Object.entries(grouped).map(([id, points]) => ({ id, pts: points.sort((a, b) => a.x.localeCompare(b.x)) }))
}

function RidershipRow({ mode, latest, maximum }) {
  if (!latest) return null
  const color = MODE_COLORS[mode]
  return (
    <div className="ridership-row">
      <div className="ridership-label"><i style={{ background: color }} /><span><strong>{MODE_LABEL[mode]}</strong><small>{monthLabel(latest.x)} · historis</small></span></div>
      <div className="ridership-value"><strong>{latest.y.toLocaleString('id-ID')}</strong><span>penumpang</span></div>
      <div className="ridership-track" aria-hidden><span style={{ width: `${Math.max(5, (latest.y / maximum) * 100)}%`, background: color }} /></div>
    </div>
  )
}

export default function Dashboard() {
  const [mode, setMode] = useState('all')
  const [rows, setRows] = useState(null)
  const [lines, setLines] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const sequence = useRef(0)

  useEffect(() => {
    const id = ++sequence.current
    const selected = mode === 'all' ? null : mode
    Promise.all([getRidership(selected, 'month'), getLines(selected)])
      .then(([ridership, network]) => {
        if (id !== sequence.current) return
        setRows(ridership.rows); setLines(network.lines); setBusy(false)
      })
      .catch((requestError) => {
        if (id !== sequence.current) return
        setError(requestError.message); setBusy(false)
      })
  }, [mode])

  const perMode = useMemo(() => {
    if (!rows) return {}
    return Object.fromEntries(MODES.map((item) => [item, seriesForMode(rows, item)]))
  }, [rows])

  const latestPerMode = useMemo(() => {
    const output = {}
    for (const item of MODES) {
      let latest = null
      for (const series of perMode[item] || []) {
        const last = series.pts[series.pts.length - 1]
        if (last && (!latest || last.x > latest.x)) latest = { ...last, series: series.id }
      }
      output[item] = latest
    }
    return output
  }, [perMode])

  const lineCountByMode = useMemo(() => {
    const output = {}
    for (const line of lines || []) output[line.mode_id] = (output[line.mode_id] || 0) + 1
    return output
  }, [lines])

  const selectMode = (nextMode) => {
    if (nextMode === mode) return
    setBusy(true)
    setError(null)
    setMode(nextMode)
  }

  if (error) return <div className="page"><p className="error">Data belum dapat dimuat: {error}</p></div>
  if (!rows) return <div className="page loading-state"><span className="typing"><i /><i /><i /></span><p>Menyiapkan analisis penumpang…</p></div>

  const shownModes = mode === 'all' ? MODES : [mode]
  const shownLines = mode === 'all' ? [] : (lines || []).filter((line) => line.mode_id === mode)
  const latestMaximum = Math.max(...shownModes.map((item) => latestPerMode[item]?.y || 0), 1)
  const leader = shownModes.reduce((best, item) => {
    if (!latestPerMode[item]) return best
    return !best || latestPerMode[item].y > latestPerMode[best].y ? item : best
  }, null)

  const chart = (chartMode) => {
    const series = (perMode[chartMode] || []).map((item) => ({
      name: item.id,
      type: 'line', smooth: 0.25, symbol: 'circle', symbolSize: 5, lineStyle: { width: 3 },
      data: item.pts.map((point) => ({
        value: [point.x, point.y],
        tooltip: { formatter: `${monthLabel(point.x)}<br/>${point.y.toLocaleString('id-ID')} orang<br/><i>${item.id} · ${point.src}</i>` },
      })),
      connectNulls: true,
    }))
    return {
      color: [MODE_COLORS[chartMode]],
      textStyle: { fontFamily: '"Atkinson Hyperlegible", "Segoe UI", sans-serif', color: '#536578' },
      tooltip: { trigger: 'axis', backgroundColor: '#0B1F33', borderWidth: 0, textStyle: { color: '#fff' } },
      legend: { bottom: 0, textStyle: { fontSize: 11, color: '#536578' } },
      grid: { left: 58, right: 14, top: 18, bottom: 38 },
      xAxis: { type: 'category', data: [...new Set(series.flatMap((item) => item.data.map((point) => point.value[0])))].sort(), axisLine: { lineStyle: { color: '#B8C6D3' } }, axisLabel: { formatter: (value) => monthLabel(value).replace(' 20', "'") } },
      yAxis: { type: 'value', axisLine: { show: false }, splitLine: { lineStyle: { color: '#E1E8EF' } }, axisLabel: { formatter: (value) => `${(value / 1e6).toFixed(0)} jt` } },
      series,
    }
  }

  return (
    <div className="page analytics-page">
      <div className="analytics-toolbar">
        <div><span className="field-label">Tampilkan moda</span><div className="chips filter-chips">
          <button className={`chip${mode === 'all' ? ' on' : ''}`} onClick={() => selectMode('all')}>Semua moda</button>
          {FILTER_ORDER.map((item) => <button key={item} className={`chip${mode === item ? ' on' : ''}`} onClick={() => selectMode(item)}><i style={{ background: MODE_COLORS[item] }} />{item}</button>)}
        </div></div>
        <span className="freshness"><span className="system-dot online" />Data historis terhubung{busy ? ' · memperbarui…' : ''}</span>
      </div>

      <section className="insight-panel">
        <div className="insight-copy">
          <span className="section-kicker">Ringkasan periode terbaru</span>
          <h2>{mode === 'all' && leader ? `${MODE_LABEL[leader]} mencatat volume terbesar` : `Perkembangan ${MODE_LABEL[shownModes[0]]}`}</h2>
          <p>{mode === 'all' ? 'Bandingkan skala setiap moda tanpa menyamakan definisi sumber. Panjang garis mengikuti angka terbaru yang tersedia.' : 'Lihat angka terbaru, cakupan jaringan, dan perubahan bulanan pada satu tampilan.'}</p>
        </div>
        <span className="label-pill historical">Data historis</span>
        <div className="ridership-ribbon">{shownModes.map((item) => <RidershipRow key={item} mode={item} latest={latestPerMode[item]} maximum={latestMaximum} />)}</div>
        <details className="method-details compact"><summary>Sumber dan batas perbandingan</summary><p>Sumber mencakup BPS DKI Jakarta, KCI, KAI, operator TransJakarta, dan SDI Dishub. Definisi antar-sumber dapat berbeda, misalnya tap-in BPS dan perhitungan operator. Arahkan kursor ke titik grafik untuk melihat source ID.</p></details>
      </section>

      <section className="network-band">
        <div><span className="section-kicker">Cakupan jaringan</span><h2>Jalur yang dapat direncanakan</h2><p>GTFS TransJakarta dan relasi jaringan OSM. Angka ini menunjukkan jalur, bukan penumpang.</p></div>
        {mode === 'all' ? (
          <div className="mode-legend">{MODES.map((item) => <span key={item} className="legend-item"><i style={{ background: MODE_COLORS[item] }} />{MODE_LABEL[item]}<strong>{lineCountByMode[item] ?? 0}</strong></span>)}</div>
        ) : shownLines.length === 0 ? <p className="note">Belum ada jalur untuk moda ini.</p> : (
          <div className="line-list">{shownLines.map((line) => <span key={line.line_id} className="chip" title={line.canonical_name}>{line.display_name || line.canonical_name}{line.stop_count ? ` · ${line.stop_count} stasiun` : ''}</span>)}</div>
        )}
      </section>

      <div className="dash-grid" style={shownModes.length === 1 ? { gridTemplateColumns: '1fr' } : undefined}>
        {shownModes.map((item) => (
          <section key={item} className="chart-panel">
            <div className="chart-heading"><div><span className="section-kicker">Tren bulanan</span><h3>{MODE_LABEL[item]}</h3></div><i style={{ background: MODE_COLORS[item] }} /></div>
            {(perMode[item] || []).length === 0 ? <p className="note">Belum ada seri bulanan.</p> : <ReactECharts option={chart(item)} style={{ height: 290 }} notMerge />}
          </section>
        ))}
      </div>
    </div>
  )
}

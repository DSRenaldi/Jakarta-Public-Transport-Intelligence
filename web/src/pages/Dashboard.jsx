import { useEffect, useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { getRidership } from '../api.js'
import { MODE_COLORS } from '../lib.js'

const MODES = ['MRT', 'KRL', 'LRT', 'BRT']
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
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getRidership().then((r) => setRows(r.rows)).catch((e) => setError(e.message))
  }, [])

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
      <section className="card">
        <h2>Penumpang per moda — data historis</h2>
        <p className="note">
          Sumber: BPS DKI Jakarta (tabel transportasi), KCI, KAI, operator TransJakarta, SDI
          Dishub — label <b>historis</b>, tiap baris punya <code>source_id</code> + definisi
          (hover titik untuk detail). Definisi antar-sumber bisa berbeda (mis. tap-in BPS vs
          perhitungan operator).
        </p>
        <div className="stats">
          {MODES.map((m) => <StatCard key={m} mode={m} latest={latestPerMode[m]} />)}
        </div>
      </section>

      <div className="dash-grid">
        {MODES.map((m) => (
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

import { useEffect, useState } from 'react'
import Planner from './pages/Planner.jsx'
import RagPage from './pages/RagPage.jsx'
import Dashboard from './pages/Dashboard.jsx'
import MapsPage from './pages/MapsPage.jsx'
import { getHealth } from './api.js'

const TABS = [
  { id: 'rute', label: 'Penencana Rute', el: <Planner /> },
  { id: 'rag', label: 'Tanya Dokumen', el: <RagPage /> },
  { id: 'dashboard', label: 'Dashboard', el: <Dashboard /> },
  { id: 'peta', label: 'Peta Resmi', el: <MapsPage /> },
]

export default function App() {
  const [tab, setTab] = useState('rute')
  const [health, setHealth] = useState(null)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>▤</span>
          <div>
            <h1>JPTI</h1>
            <p>Transportasi Umum Jabodetabek</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Halaman utama">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? 'tab active' : 'tab'}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="status" title={health ? JSON.stringify(health) : 'backend tidak tercapai'}>
          <span className={health ? 'dot ok' : 'dot err'} />
          {health ? `API · ${health.network.stops.toLocaleString('id-ID')} titik` : 'API offline'}
        </div>
      </header>

      <main>{TABS.find((t) => t.id === tab).el}</main>

      <footer>
        <p>
          Waktu rail = <b>proksi</b> (jarak/kecepatan rata-rata + dwell) · BRT dari jadwal GTFS ·
          tarif = flat minimum per moda. Semua angka membawa label sumber
          (<code>aktual</code>/<code>historis</code>/<code>prediksi</code>/<code>proksi</code>) dan
          dapat ditelusuri ke sumbernya.
        </p>
        <p className="small">
          Moda dibedakan: MRT Jakarta · KRL Commuter Line · LRT Jakarta · LRT Jabodebek · TransJakarta.
          Data: BPS, kci.id, jakartamrt.co.id, lrtjakarta.co.id, GTFS TransJakarta, OSM (lihat registry sumber).
        </p>
      </footer>
    </div>
  )
}

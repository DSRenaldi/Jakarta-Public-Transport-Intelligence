import { useEffect, useState } from 'react'
import Planner from './pages/Planner.jsx'
import ChatPage from './pages/ChatPage.jsx'
import Dashboard from './pages/Dashboard.jsx'
import MapsPage from './pages/MapsPage.jsx'
import { getHealth } from './api.js'

const TABS = [
  { id: 'rute', label: 'Rute', el: <Planner /> },
  { id: 'chat', label: 'Tanya', el: <ChatPage /> },
  { id: 'dashboard', label: 'Data', el: <Dashboard /> },
  { id: 'peta', label: 'Peta', el: <MapsPage /> },
]
const ACTIVE_TAB_KEY = 'jpti_active_tab'

function getInitialTab() {
  try {
    const saved = localStorage.getItem(ACTIVE_TAB_KEY)
    if (TABS.some((tab) => tab.id === saved)) return saved
  } catch { /* private mode */ }
  return 'rute'
}

// Marka simpul interchange — tiga lin moda bertemu di satu stasiun
function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden>
      <svg viewBox="0 0 48 48" role="img">
        <rect width="48" height="48" fill="#101216" />
        <g fill="none" strokeLinecap="round">
          <path d="M8 24 H40" stroke="#1B5FD9" strokeWidth="5" />
          <path d="M24 8 V40" stroke="#0B7A4B" strokeWidth="5" />
          <path d="M11 37 L37 11" stroke="#F2A900" strokeWidth="5" />
        </g>
        <circle cx="24" cy="24" r="6.5" fill="#F6F7F5" stroke="#101216" strokeWidth="3" />
      </svg>
    </span>
  )
}

export default function App() {
  const [tab, setTab] = useState(getInitialTab)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  const selectTab = (tabId) => {
    setTab(tabId)
    try { localStorage.setItem(ACTIVE_TAB_KEY, tabId) } catch { /* abaikan */ }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <BrandMark />
          <div>
            <h1>JPTI</h1>
            <p>Jabodetabek Transit Intelligence</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Halaman utama">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? 'tab active' : 'tab'}
              onClick={() => selectTab(t.id)}
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

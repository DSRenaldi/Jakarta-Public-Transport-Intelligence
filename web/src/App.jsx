import { useCallback, useEffect, useState } from 'react'
import Planner from './pages/Planner.jsx'
import ChatPage from './pages/ChatPage.jsx'
import Dashboard from './pages/Dashboard.jsx'
import MapsPage from './pages/MapsPage.jsx'
import { getHealth } from './api.js'

const SECTIONS = [
  {
    id: 'rute', label: 'Perjalanan', short: 'Rute', component: Planner,
    eyebrow: 'Perencana multimoda', title: 'Rencanakan perjalanan',
    description: 'Bandingkan waktu, tarif, perpindahan, dan perkiraan kepadatan.',
  },
  {
    id: 'chat', label: 'Asisten', short: 'Tanya', component: ChatPage,
    eyebrow: 'Asisten mobilitas', title: 'Tanyakan perjalanan atau data',
    description: 'Jawaban berbasis jaringan, statistik, dan dokumen resmi.',
  },
  {
    id: 'dashboard', label: 'Analisis', short: 'Data', component: Dashboard,
    eyebrow: 'Analisis historis', title: 'Pahami pergerakan Jabodetabek',
    description: 'Bandingkan penumpang dan jaringan setiap moda dalam satu ruang kerja.',
  },
  {
    id: 'peta', label: 'Jaringan', short: 'Peta', component: MapsPage,
    eyebrow: 'Atlas transportasi', title: 'Jelajahi jaringan antarmoda',
    description: 'Peta integrasi dan peta resmi setiap operator.',
  },
]

const ACTIVE_TAB_KEY = 'jpti_active_tab'

function getInitialTab() {
  try {
    const saved = localStorage.getItem(ACTIVE_TAB_KEY)
    if (SECTIONS.some((section) => section.id === saved)) return saved
  } catch { /* private mode */ }
  return 'rute'
}

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden>
      <svg viewBox="0 0 48 48" role="img">
        <rect width="48" height="48" rx="13" fill="#fff" />
        <path d="M7 24h34" stroke="#1769E0" strokeWidth="5" strokeLinecap="round" />
        <path d="M24 7v34" stroke="#007F73" strokeWidth="5" strokeLinecap="round" />
        <path d="M10 38 38 10" stroke="#FFC72C" strokeWidth="5" strokeLinecap="round" />
        <circle cx="24" cy="24" r="6.5" fill="#0B1F33" stroke="#fff" strokeWidth="3" />
      </svg>
    </span>
  )
}

function NavIcon({ id }) {
  const paths = {
    rute: <><circle cx="6" cy="17" r="2.2" /><circle cx="18" cy="7" r="2.2" /><path d="M7.8 15.5 16.2 8.5" /></>,
    chat: <><path d="M4 5h16v11H9l-5 4V5Z" /><path d="M8 9h8M8 12h5" /></>,
    dashboard: <><path d="M5 19V11M12 19V5M19 19v-6" /><path d="M3 19h18" /></>,
    peta: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z" /><path d="M9 3v15M15 6v15" /></>,
  }
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[id]}</svg>
}

function DataDrawer({ open, onClose, health }) {
  if (!open) return null
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside className="data-drawer" role="dialog" aria-modal="true" aria-labelledby="data-drawer-title" onMouseDown={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div><span className="eyebrow">Transparansi data</span><h2 id="data-drawer-title">Tentang perkiraan</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Tutup informasi data">×</button>
        </div>
        <div className="drawer-body">
          <div className="data-principle"><span className="label-pill historical">Historis</span><p>Angka penumpang yang telah diterbitkan BPS atau operator.</p></div>
          <div className="data-principle"><span className="label-pill proxy">Proksi</span><p>Perkiraan dari jarak, kecepatan, dwell time, headway, atau pola jam sibuk—bukan pengukuran langsung.</p></div>
          <div className="data-principle"><span className="label-pill prediction">Prediksi</span><p>Hasil model untuk waktu yang belum terjadi dan selalu disertai tingkat keyakinan.</p></div>
          <hr />
          <h3>Dasar perhitungan</h3>
          <ul className="plain-list">
            <li>Waktu perjalanan rail menggunakan jarak, kecepatan rata-rata, dan dwell time.</li>
            <li>Perjalanan BRT menggunakan jadwal GTFS TransJakarta.</li>
            <li>Tarif rute adalah tarif minimum yang tersedia per moda.</li>
            <li>Setiap angka membawa sumber dan periode data.</li>
          </ul>
          <div className="system-card">
            <span className={health ? 'system-dot online' : 'system-dot'} />
            <div><strong>{health ? 'Layanan data aktif' : 'Layanan data tidak terjangkau'}</strong><small>{health ? `${health.network.stops.toLocaleString('id-ID')} titik jaringan dimuat` : 'Periksa backend API'}</small></div>
          </div>
        </div>
      </aside>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState(getInitialTab)
  const [journeyPrefill, setJourneyPrefill] = useState(null)
  const consumeJourneyPrefill = useCallback(() => setJourneyPrefill(null), [])
  const [health, setHealth] = useState(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => { getHealth().then(setHealth).catch(() => setHealth(null)) }, [])
  useEffect(() => {
    const close = (event) => event.key === 'Escape' && setDrawerOpen(false)
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [])

  const selectTab = (tabId) => {
    setTab(tabId)
    try { localStorage.setItem(ACTIVE_TAB_KEY, tabId) } catch { /* private mode */ }
  }

  const openJourney = (prefill) => {
    setJourneyPrefill(prefill)
    selectTab('rute')
  }

  const active = SECTIONS.find((section) => section.id === tab)
  const ActivePage = active.component
  const pageProps = active.id === 'rute'
    ? { prefill: journeyPrefill, onPrefillConsumed: consumeJourneyPrefill }
    : active.id === 'chat'
      ? { onOpenJourney: openJourney }
      : {}

  return (
    <div className="app-shell">
      <aside className="shell-sidebar">
        <div className="brand">
          <BrandMark />
          <div><strong>JPTI</strong><span>Pusat Mobilitas<br />Jabodetabek</span></div>
        </div>
        <nav className="journey-nav" aria-label="Halaman utama">
          {SECTIONS.map((section) => (
            <button key={section.id} className={tab === section.id ? 'journey-stop active' : 'journey-stop'} onClick={() => selectTab(section.id)}>
              <span className="stop-node"><NavIcon id={section.id} /></span>
              <span><strong>{section.label}</strong><small>{section.eyebrow}</small></span>
            </button>
          ))}
        </nav>
        <button className="sidebar-data-button" onClick={() => setDrawerOpen(true)}>
          <span className={health ? 'system-dot online' : 'system-dot'} />
          <span><strong>{health ? 'Data siap digunakan' : 'API offline'}</strong><small>{health ? `${health.network.stops.toLocaleString('id-ID')} titik jaringan` : 'Lihat status sistem'}</small></span>
        </button>
      </aside>

      <div className="shell-content">
        <header className="page-header">
          <div><span className="eyebrow">{active.eyebrow}</span><h1>{active.title}</h1><p>{active.description}</p></div>
          <button className="data-info-button" onClick={() => setDrawerOpen(true)}><span className="info-glyph">i</span>Tentang data</button>
        </header>
        <main className={`main-content page-${tab}`}><ActivePage {...pageProps} /></main>
      </div>

      <nav className="mobile-nav" aria-label="Navigasi mobile">
        {SECTIONS.map((section) => (
          <button key={section.id} className={tab === section.id ? 'active' : ''} onClick={() => selectTab(section.id)}>
            <NavIcon id={section.id} /><span>{section.short}</span>
          </button>
        ))}
      </nav>
      <DataDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} health={health} />
    </div>
  )
}

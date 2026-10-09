import { useState } from 'react'

// Port dari dashboard/network_map.html — caption & metadata sumber dipertahankan.
const TABS = [
  {
    id: 'integrasi', label: 'Integrasi',
    title: 'Peta Integrasi',
    note: 'Semua moda dalam satu peta, edisi terbaru (FDTJ v26.08c). Klik untuk memperbesar.',
    img: 'fdtj_integrasi_2026_08c.png',
    meta: 'Diakses: 2026-09-29',
  },
  {
    id: 'krl', label: 'KRL',
    title: 'KRL Commuter Line',
    note: 'Peta resmi KAI Commuter (kci.id), Jabodetabek & Merak. Stasiun Karet digarisbawahi = dinonaktifkan.',
    img: 'krl_area0.png',
    meta: 'Versi: terkini (diakses 2026-09-30) · Sumber: kci.id · Diakses: 2026-09-29',
  },
  {
    id: 'tj', label: 'TransJakarta',
    title: 'TransJakarta',
    note: 'Peta integrasi resmi TransJakarta + 14 koridor di bawahnya (peta per koridor terbaru, 2025–2026).',
    img: 'tj_integrasi.jpg',
    meta: 'Versi: terkini (diakses 2026-09-30) · Sumber: transjakarta.co.id · Diakses: 2026-09-29',
    kor: Array.from({ length: 14 }, (_, i) => ({ img: `tj_kor${i + 1}.jpg`, cap: `Koridor ${i + 1}` })),
  },
  {
    id: 'mrt', label: 'MRT Jakarta',
    title: 'MRT Jakarta',
    note: 'Lin Utara-Selatan, 13 stasiun (Lebak Bulus – Bundaran HI), edisi Jan 2026.',
    img: 'fdtj_mrt_2026_01.png',
    meta: 'Diakses: 2026-09-29',
  },
  {
    id: 'lrtj', label: 'LRT Jakarta',
    title: 'LRT Jakarta',
    note: 'PERHATIAN: edisi Nov 2024 — hanya fase 1A (6 stasiun, s.d. Velodrome). Ekstensi fase 1B (Velodrome–Manggarai, +5 stasiun, total 11) diuji coba 10 Sep 2026 dan diresmikan 16 Sep 2026 — lihat tab Integrasi untuk jaringan terkini.',
    img: 'fdtj_lrtj_2024_11.png',
    meta: 'Diakses: 2026-09-29',
  },
  {
    id: 'lrtb', label: 'LRT Jabodebek',
    title: 'LRT Jabodebek',
    note: 'Lin Cibubur (Dukuh Atas BNI – Harjamukti) & Lin Bekasi (Dukuh Atas BNI – Jatimulya), 18 stasiun. Tidak ada perubahan lin sejak 2023.',
    img: 'fdtj_lrtb_2024_11.png',
    meta: 'Diakses: 2026-09-29',
  },
]

export default function MapsPage() {
  const [tab, setTab] = useState(TABS[0].id)
  const [zoom, setZoom] = useState(null) // {src, alt}
  const t = TABS.find((x) => x.id === tab)

  return (
    <div className="page">
      <section className="card">
        <h2>Peta rute resmi per moda</h2>
        <p className="note">
          Asset peta dari situs operator (arsip proyek, akses 2026-09-29/30). Bedakan moda:
          MRT Jakarta ≠ LRT Jakarta ≠ LRT Jabodebek ≠ KRL ≠ TransJakarta.
        </p>
        <div className="tabs tabs-card">
          {TABS.map((x) => (
            <button key={x.id} className={tab === x.id ? 'tab active' : 'tab'} onClick={() => setTab(x.id)}>
              {x.label}
            </button>
          ))}
        </div>

        <h3>{t.title}</h3>
        <p className="note">{t.note}</p>
        <div className="mapbox">
          <img src={`/maps/${t.img}`} alt={`Peta ${t.title}`} loading="lazy" onClick={() => setZoom({ src: t.img, alt: t.title })} />
        </div>
        <p className="meta">{t.meta}</p>

        {t.kor && (
          <>
            <h3 className="sub">Koridor — peta rute resmi per koridor</h3>
            <div className="kor-grid">
              {t.kor.map((k) => (
                <figure key={k.img} className="kor">
                  <img loading="lazy" src={`/maps/${k.img}`} alt={`Peta ${k.cap}`} onClick={() => setZoom({ src: k.img, alt: k.cap })} />
                  <figcaption>{k.cap}</figcaption>
                </figure>
              ))}
            </div>
          </>
        )}
      </section>

      {zoom && (
        <div className="lightbox" role="dialog" aria-modal="true" onClick={() => setZoom(null)}>
          <button className="lb-close" aria-label="Tutup">×</button>
          <img src={`/maps/${zoom.src}`} alt={`Peta ${zoom.alt} (perbesar)`} />
        </div>
      )}
    </div>
  )
}

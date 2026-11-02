import { useEffect, useState } from 'react'

const MAPS = [
  { id: 'integrasi', label: 'Semua moda', tag: 'Terbaru', title: 'Peta Integrasi Jabodetabek', note: 'Jaringan antarmoda dalam satu peta, edisi FDTJ v26.08c.', img: 'fdtj_integrasi_2026_08c.png', meta: 'FDTJ · versi 26.08c · diakses 29 September 2026' },
  { id: 'krl', label: 'KRL', title: 'KRL Commuter Line', note: 'Peta resmi KAI Commuter untuk jaringan Jabodetabek dan Merak. Stasiun Karet ditandai nonaktif.', img: 'krl_area0.png', meta: 'KAI Commuter · diakses 30 September 2026' },
  { id: 'tj', label: 'TransJakarta', title: 'TransJakarta', note: 'Peta integrasi resmi serta peta rute untuk 14 koridor utama.', img: 'tj_integrasi.jpg', meta: 'TransJakarta · edisi 2025–2026', kor: Array.from({ length: 14 }, (_, index) => ({ img: `tj_kor${index + 1}.jpg`, cap: `Koridor ${index + 1}` })) },
  { id: 'mrt', label: 'MRT Jakarta', title: 'MRT Jakarta', note: 'Lin Utara–Selatan, 13 stasiun dari Lebak Bulus hingga Bundaran HI.', img: 'fdtj_mrt_2026_01.png', meta: 'FDTJ · edisi Januari 2026' },
  { id: 'lrtj', label: 'LRT Jakarta', tag: 'Peta lama', title: 'LRT Jakarta', note: 'Peta ini masih menampilkan fase 1A. Untuk ekstensi hingga Manggarai, gunakan Peta Integrasi.', img: 'fdtj_lrtj_2024_11.png', meta: 'FDTJ · edisi November 2024 · jaringan terkini ada di Peta Integrasi' },
  { id: 'lrtb', label: 'LRT Jabodebek', title: 'LRT Jabodebek', note: 'Lin Cibubur dan Lin Bekasi, menghubungkan Dukuh Atas BNI dengan Harjamukti dan Jatimulya.', img: 'fdtj_lrtb_2024_11.png', meta: 'FDTJ · 18 stasiun · edisi November 2024' },
]

export default function MapsPage() {
  const [tab, setTab] = useState(MAPS[0].id)
  const [zoom, setZoom] = useState(null)
  const selected = MAPS.find((item) => item.id === tab)

  useEffect(() => {
    const close = (event) => event.key === 'Escape' && setZoom(null)
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [])

  return (
    <div className="page maps-page">
      <div className="map-atlas">
        <aside className="map-catalog">
          <div className="catalog-intro"><span className="section-kicker">Pilih jaringan</span><h2>Atlas moda</h2><p>Gunakan peta integrasi untuk melihat titik perpindahan antarmoda.</p></div>
          <nav aria-label="Daftar peta moda">{MAPS.map((item) => (
            <button key={item.id} className={tab === item.id ? 'map-catalog-item active' : 'map-catalog-item'} onClick={() => setTab(item.id)}>
              <span>{item.label}</span>{item.tag && <small>{item.tag}</small>}<b aria-hidden>→</b>
            </button>
          ))}</nav>
          <div className="catalog-note"><span aria-hidden>i</span><p>Nama dan hak penamaan stasiun dapat berubah. Tanggal versi selalu ditampilkan bersama peta.</p></div>
        </aside>

        <section className="map-viewer">
          <div className="map-viewer-head">
            <div><span className="section-kicker">Peta resmi</span><h2>{selected.title}</h2><p>{selected.note}</p></div>
            <button className="btn map-expand" onClick={() => setZoom({ src: selected.img, alt: selected.title })}>Perbesar <span aria-hidden>↗</span></button>
          </div>
          <button className="map-canvas" onClick={() => setZoom({ src: selected.img, alt: selected.title })} aria-label={`Perbesar peta ${selected.title}`}>
            <img src={`/maps/${selected.img}`} alt={`Peta ${selected.title}`} loading="lazy" />
          </button>
          <div className="map-meta"><span className={selected.tag === 'Peta lama' ? 'label-pill warning' : 'label-pill actual'}>{selected.tag === 'Peta lama' ? 'Arsip' : 'Terverifikasi'}</span><span>{selected.meta}</span></div>
        </section>
      </div>

      {selected.kor && (
        <section className="corridor-section">
          <div className="corridor-heading"><div><span className="section-kicker">Rincian jaringan</span><h2>Peta per koridor</h2></div><p>Pilih gambar untuk melihat rute dan daftar pemberhentian lebih jelas.</p></div>
          <div className="kor-grid">{selected.kor.map((corridor) => <figure key={corridor.img} className="kor"><button onClick={() => setZoom({ src: corridor.img, alt: corridor.cap })}><img loading="lazy" src={`/maps/${corridor.img}`} alt={`Peta ${corridor.cap}`} /></button><figcaption><span>{corridor.cap}</span><b aria-hidden>↗</b></figcaption></figure>)}</div>
        </section>
      )}

      {zoom && <div className="lightbox" role="dialog" aria-modal="true" aria-label={`Peta ${zoom.alt} diperbesar`} onClick={() => setZoom(null)}><button className="lb-close" aria-label="Tutup">×</button><img src={`/maps/${zoom.src}`} alt={`Peta ${zoom.alt} diperbesar`} onClick={(event) => event.stopPropagation()} /></div>}
    </div>
  )
}

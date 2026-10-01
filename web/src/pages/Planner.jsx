import { useEffect, useRef, useState } from 'react'
import {
  MapContainer, TileLayer, Polyline, CircleMarker, Tooltip, useMap,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { searchStops, findRoute } from '../api.js'
import { MODE_COLORS, WALK_COLOR, fmtTime, dispName } from '../lib.js'

const MODES = ['MRT', 'KRL', 'LRT', 'BRT']
const PREFS = [
  ['tercepat', 'Tercepat'],
  ['termurah', 'Termurah'],
  ['min_transfers', 'Min. transfer'],
  ['longgar', 'Longgar'],
]

// ---------- input stasiun dengan autocomplete ----------
function StopInput({ label, stop, onPick, mode, onModeChange, placeholder }) {
  const [text, setText] = useState(stop ? dispName(stop) : '')
  const [open, setOpen] = useState(false)
  const [cands, setCands] = useState([])
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)
  const box = useRef(null)
  const reqId = useRef(0)

  useEffect(() => { if (stop) setText(dispName(stop)) }, [stop])

  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  // cari dgn penjaga respons basi (query lebih baru menang)
  const doSearch = async (t, m) => {
    const id = ++reqId.current
    setBusy(true)
    try {
      const r = await searchStops(t, m || undefined, 7)
      if (id === reqId.current) setCands(r.candidates)
    } catch { if (id === reqId.current) setCands([]) }
    finally { if (id === reqId.current) setBusy(false) }
  }

  const onChange = (e) => {
    const t = e.target.value
    setText(t)
    if (stop) onPick(null)
    setOpen(true)
    clearTimeout(timer.current)
    setCands([])  // buang kandidat query lama — jangan tampilkan hasil basi
    if (!t.trim()) return
    timer.current = setTimeout(() => doSearch(t.trim(), mode), 250)
  }

  const onFocus = () => {
    setOpen(true)
    // buka dropdown dgn teks ada tapi kandidat kosong (mis. pasca-query lama
    // dibuang) -> cari ulang
    if (text.trim() && cands.length === 0 && !busy) doSearch(text.trim(), mode)
  }

  return (
    <div className="stopbox" ref={box}>
      <label className="stop-label">{label}</label>
      <div className="stop-row">
        <input
          className="stop-input"
          value={text}
          placeholder={placeholder}
          onChange={onChange}
          onFocus={onFocus}
          aria-label={`${label} — nama stasiun/halte`}
        />
        <select
          className="mode-select"
          value={mode || ''}
          onChange={(e) => onModeChange(e.target.value || null)}
          title="Batasi pencarian per moda (opsional)"
        >
          <option value="">Semua moda</option>
          {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      {stop && (
        <div className="stop-picked">
          <span className="mode-badge" style={badgeStyle(stop.mode)}>{stop.mode}</span>
          {dispName(stop)}
          <button type="button" className="clear-btn" title="Hapus pilihan" onClick={() => { onPick(null); setText('') }}>×</button>
        </div>
      )}
      {open && (
        <ul className="cand">
          {busy && <li className="cand-busy">mencari…</li>}
          {!busy && cands.length === 0 && <li className="cand-busy">tidak ada kecocokan</li>}
          {cands.map((c) => (
            <li key={c.stop_id}>
              <button type="button" onClick={() => { onPick(c); setOpen(false) }}>
                <span className="mode-badge" style={badgeStyle(c.mode)}>{c.mode}</span>
                <span className="cand-name">{c.display || c.name}</span>
                {c.aliases && c.aliases.length > 0 && (
                  <span
                    className="cand-alias"
                    title={`juga dikenal: ${c.aliases.join(', ')}`}
                  >
                    juga dikenal: {c.aliases[0]}
                  </span>
                )}
                <span className="cand-score">{c.score}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function badgeStyle(mode) {
  const c = MODE_COLORS[mode] || '#5c6672'
  return { background: `${c}1a`, color: c }
}

// ---------- peta rute ----------
function FitBounds({ points }) {
  const map = useMap()
  useEffect(() => {
    if (points.length > 0) {
      map.fitBounds(L.latLngBounds(points), { padding: [40, 40] })
    }
  }, [points, map])
  return null
}

function RouteMap({ result }) {
  const pts = result.segments.flatMap((s) => [
    [s.from.lat, s.from.lon],
    [s.to.lat, s.to.lon],
  ])
  return (
    <div className="routemap">
      <MapContainer
        center={[-6.25, 106.83]}
        zoom={11}
        scrollWheelZoom
        style={{ height: '430px', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {result.segments.map((s, i) => (
          <Polyline
            key={i}
            positions={[[s.from.lat, s.from.lon], [s.to.lat, s.to.lon]]}
            pathOptions={{
              color: s.type === 'walk' ? WALK_COLOR : (MODE_COLORS[s.mode] || '#333'),
              weight: s.type === 'walk' ? 3 : 5,
              dashArray: s.type === 'walk' ? '6 8' : undefined,
              opacity: 0.9,
            }}
          />
        ))}
        <CircleMarker
          center={[result.origin.lat, result.origin.lon]}
          radius={9}
          pathOptions={{ color: '#0f62fe', fillColor: '#0f62fe', fillOpacity: 1 }}
        >
          <Tooltip permanent direction="top" offset={[0, -10]}>A · {dispName(result.origin)}</Tooltip>
        </CircleMarker>
        <CircleMarker
          center={[result.dest.lat, result.dest.lon]}
          radius={9}
          pathOptions={{ color: '#da1e28', fillColor: '#da1e28', fillOpacity: 1 }}
        >
          <Tooltip permanent direction="top" offset={[0, -10]}>B · {dispName(result.dest)}</Tooltip>
        </CircleMarker>
        <FitBounds points={pts} />
      </MapContainer>
      <div className="legend">
        {Object.entries(MODE_COLORS).map(([m, c]) => (
          <span key={m} className="legend-item"><i style={{ background: c }} />{m}</span>
        ))}
        <span className="legend-item"><i style={{ background: WALK_COLOR }} />jalan kaki</span>
      </div>
    </div>
  )
}

// ---------- halaman ----------
export default function Planner() {
  const [origin, setOrigin] = useState(null)
  const [dest, setDest] = useState(null)
  const [oMode, setOMode] = useState(null)
  const [dMode, setDMode] = useState(null)
  const [prefer, setPrefer] = useState('tercepat')
  const [depTime, setDepTime] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const lastReq = useRef(null)

  const run = async (o = origin, d = dest, pref = prefer, dep = depTime) => {
    if (!o || !d) return
    setBusy(true)
    setError(null)
    lastReq.current = { o, d, pref, dep }
    try {
      const r = await findRoute({ origin: dispName(o), dest: dispName(d), prefer: pref, origin_mode: oMode, dest_mode: dMode, dep_time: dep })
      setResult(r)
    } catch (e) {
      setError(e.message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  // indeks segmen ride → anotasi kepadatan (urutan ride dipertahankan API)
  const crowdFor = (seg) => {
    if (seg.type !== 'ride' || !result?.crowding?.segments) return null
    const idx = result.segments.filter((s) => s.type === 'ride').indexOf(seg)
    return result.crowding.segments[idx] || null
  }

  // pilih kandidat saat hasil ambigu → langsung cari ulang
  const pickAmbiguous = (side, stop) => {
    if (side === 'origin') setOrigin(stop)
    else setDest(stop)
    const req = lastReq.current
    if (!req) return
    const o = side === 'origin' ? stop : req.o
    const d = side === 'dest' ? stop : req.d
    setBusy(true)
    findRoute({ origin: dispName(o), dest: dispName(d), prefer: req.pref, origin_mode: oMode, dest_mode: dMode, dep_time: req.dep })
      .then(setResult)
      .catch((e) => { setError(e.message); setResult(null) })
      .finally(() => setBusy(false))
  }

  const canRun = origin && dest && !busy

  return (
    <div className="page">
      <section className="card">
        <h2>Cari rute A → B</h2>
        <div className="planner-grid">
          <StopInput label="Dari" stop={origin} onPick={setOrigin} mode={oMode} onModeChange={setOMode} placeholder="cth: Manggarai, Lebak Bulus, Monas…" />
          <StopInput label="Ke" stop={dest} onPick={setDest} mode={dMode} onModeChange={setDMode} placeholder="cth: Bogor, Dukuh Atas, Bundaran HI…" />
          <div className="pref-row">
            <label className="stop-label">Preferensi</label>
            <div className="stop-row">
              <select className="mode-select pref-select" value={prefer} onChange={(e) => setPrefer(e.target.value)}>
                {PREFS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <input
                type="time"
                className="mode-select pref-select"
                value={depTime}
                onChange={(e) => setDepTime(e.target.value)}
                title="Jam keberangkatan (untuk estimasi kepadatan per segmen; kosong = sekarang)"
                aria-label="Jam keberangkatan (opsional)"
              />
              <button className="btn primary" disabled={!canRun} onClick={() => run()}>
                {busy ? 'Mencari…' : 'Cari rute'}
              </button>
            </div>
          </div>
        </div>
        {error && <p className="error">Gagal: {error}</p>}
      </section>

      {result?.status === 'ok' && (
        <>
          <section className="card">
            <div className="summary">
              <div className="sum-item big">
                <span className="sum-val">{fmtTime(result.time_sec)}</span>
                <span className="sum-lbl">total waktu <em>(proksi)</em></span>
              </div>
              <div className="sum-item">
                <span className="sum-val">Rp{result.fare.toLocaleString('id-ID')}</span>
                <span className="sum-lbl">tarif min.</span>
              </div>
              <div className="sum-item">
                <span className="sum-val">{result.transfers}</span>
                <span className="sum-lbl">transfer</span>
              </div>
              <div className="sum-item">
                <span className="sum-val" style={{ fontSize: '15px', lineHeight: '28px' }}>
                  {dispName(result.origin)} → {dispName(result.dest)}
                </span>
                <span className="sum-lbl">{result.preference}</span>
              </div>
            </div>

            <ol className="timeline">
              {result.segments.map((s, i) => (
                <li key={i} className="seg">
                  <span
                    className="seg-dot"
                    style={{ background: s.type === 'walk' ? WALK_COLOR : (MODE_COLORS[s.mode] || '#333') }}
                  />
                  {s.type === 'walk' ? (
                    <div className="seg-body">
                      <span className="seg-kind">Jalan kaki</span>
                      <span className="seg-route">{dispName(s.from)} → {dispName(s.to)}</span>
                      <span className="seg-time">±{fmtTime(s.walk_sec)}</span>
                    </div>
                  ) : (
                    <div className="seg-body">
                      <span className="seg-kind">
                        <span className="mode-badge" style={badgeStyle(s.mode)}>{s.mode}</span>
                        {s.corridor && <b className="seg-corridor">{s.corridor}</b>}
                        {s.line}
                      </span>
                      <span className="seg-route">{dispName(s.from)} → {dispName(s.to)}</span>
                      <span className="seg-time">
                        {fmtTime(s.travel_sec)}{s.wait_sec > 0 ? ` + tunggu ±${fmtTime(s.wait_sec)}` : ''}
                      </span>
                      {(() => {
                        const c = crowdFor(s)
                        return c ? (
                          <span
                            className={`crowd-badge crowd-${c.category}`}
                            title={`Estimasi kepadatan saat naik (${c.board_time}) — model crowding-v1, label proksi, kepercayaan ${c.confidence}; bukan pengukuran`}
                          >
                            {c.category} · naik {c.board_time} <em>(proksi)</em>
                          </span>
                        ) : null
                      })()}
                    </div>
                  )}
                </li>
              ))}
            </ol>
            <p className="note">{result.disclaimer}</p>
            {result.crowding?.segments?.length > 0 && (
              <p className="note small">
                Kepadatan per segmen = estimasi model crowding-v1 (label
                proksi — pola dari jendela sibuk &amp; rasio akhir pekan
                terdokumentasi; bukan pengukuran). Acuan keberangkatan:
                {result.crowding.reference_time}.
              </p>
            )}
          </section>

          <section className="card">
            <h2>Peta rute</h2>
            <RouteMap result={result} />
            <p className="note small">
              Garis = koneksi antar-stasiun (geometri data, bukan track eksak). Data: OSM/GTFS via database proyek.
            </p>
          </section>
        </>
      )}

      {result?.status === 'ambiguous' && (
        <section className="card">
          <h2>Pilih stasiun yang dimaksud</h2>
          {Object.entries(result.candidates).map(([side, cands]) => (
            <div key={side} className="ambig">
              <p className="ambig-label">{side === 'origin' ? 'Dari' : 'Ke'}:</p>
              <div className="chips">
                {cands.map((c) => (
                  <button key={c.stop_id} className="chip" onClick={() => pickAmbiguous(side, c)}>
                    <span className="mode-badge" style={badgeStyle(c.mode)}>{c.mode}</span>
                    {c.display || c.name}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}

      {result?.status === 'no_route' && (
        <section className="card">
          <h2>Tidak ada rute</h2>
          <p>
            {dispName(result.origin)} dan {dispName(result.dest)} tidak terhubung dalam jaringan yang dimuat
            ({result.message}). Coba nama lain atau moda berbeda.
          </p>
        </section>
      )}
    </div>
  )
}

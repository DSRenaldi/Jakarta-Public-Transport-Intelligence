import { useEffect, useRef, useState } from 'react'
import {
  MapContainer, TileLayer, Polyline, CircleMarker, Tooltip, useMap,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { searchStops, findRoute } from '../api.js'
import { MODE_COLORS, WALK_COLOR, fmtTime } from '../lib.js'

const MODES = ['MRT', 'KRL', 'LRT', 'BRT']
const PREFS = [
  ['tercepat', 'Tercepat'],
  ['termurah', 'Termurah'],
  ['min_transfers', 'Min. transfer'],
  ['longgar', 'Longgar'],
]

// ---------- input stasiun dengan autocomplete ----------
function StopInput({ label, stop, onPick, mode, onModeChange, placeholder }) {
  const [text, setText] = useState(stop ? stop.name : '')
  const [open, setOpen] = useState(false)
  const [cands, setCands] = useState([])
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)
  const box = useRef(null)

  useEffect(() => { if (stop) setText(stop.name) }, [stop])

  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const onChange = (e) => {
    const t = e.target.value
    setText(t)
    if (stop) onPick(null)
    setOpen(true)
    clearTimeout(timer.current)
    if (t.trim().length < 1) { setCands([]); return }
    timer.current = setTimeout(async () => {
      setBusy(true)
      try {
        const r = await searchStops(t.trim(), mode || undefined, 7)
        setCands(r.candidates)
      } catch { setCands([]) }
      finally { setBusy(false) }
    }, 250)
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
          onFocus={() => setOpen(true)}
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
          {stop.name}
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
                <span className="cand-name">{c.name}</span>
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
          <Tooltip permanent direction="top" offset={[0, -10]}>A · {result.origin.name}</Tooltip>
        </CircleMarker>
        <CircleMarker
          center={[result.dest.lat, result.dest.lon]}
          radius={9}
          pathOptions={{ color: '#da1e28', fillColor: '#da1e28', fillOpacity: 1 }}
        >
          <Tooltip permanent direction="top" offset={[0, -10]}>B · {result.dest.name}</Tooltip>
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
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const lastReq = useRef(null)

  const run = async (o = origin, d = dest, pref = prefer) => {
    if (!o || !d) return
    setBusy(true)
    setError(null)
    lastReq.current = { o, d, pref }
    try {
      const r = await findRoute({ origin: o.name, dest: d.name, prefer: pref, origin_mode: oMode, dest_mode: dMode })
      setResult(r)
    } catch (e) {
      setError(e.message)
      setResult(null)
    } finally {
      setBusy(false)
    }
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
    findRoute({ origin: o.name, dest: d.name, prefer: req.pref, origin_mode: oMode, dest_mode: dMode })
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
                  {result.origin.name} → {result.dest.name}
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
                      <span className="seg-route">{s.from.name} → {s.to.name}</span>
                      <span className="seg-time">±{fmtTime(s.walk_sec)}</span>
                    </div>
                  ) : (
                    <div className="seg-body">
                      <span className="seg-kind">
                        <span className="mode-badge" style={badgeStyle(s.mode)}>{s.mode}</span>
                        {s.corridor && <b className="seg-corridor">{s.corridor}</b>}
                        {s.line}
                      </span>
                      <span className="seg-route">{s.from.name} → {s.to.name}</span>
                      <span className="seg-time">
                        {fmtTime(s.travel_sec)}{s.wait_sec > 0 ? ` + tunggu ±${fmtTime(s.wait_sec)}` : ''}
                      </span>
                    </div>
                  )}
                </li>
              ))}
            </ol>
            <p className="note">{result.disclaimer}</p>
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
                    {c.name}
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
            {result.origin.name} dan {result.dest.name} tidak terhubung dalam jaringan yang dimuat
            ({result.message}). Coba nama lain atau moda berbeda.
          </p>
        </section>
      )}
    </div>
  )
}

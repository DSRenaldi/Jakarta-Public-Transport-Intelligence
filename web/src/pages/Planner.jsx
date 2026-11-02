import { useEffect, useMemo, useRef, useState } from 'react'
import {
  MapContainer, TileLayer, Polyline, CircleMarker, Marker, Popup, Tooltip, useMap,
} from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { searchStops, findRoute } from '../api.js'
import { MODE_COLORS, WALK_COLOR, fmtTime, dispName } from '../lib.js'
import { buildRouteMapData } from '../route-map.js'
import { buildRouteDetailData } from '../route-detail.js'

const MODES = ['MRT', 'KRL', 'LRT', 'BRT']
const PREFS = [
  ['tercepat', 'Tercepat', 'Waktu perjalanan paling singkat'],
  ['termurah', 'Termurah', 'Biaya minimum yang tersedia'],
  ['min_transfers', 'Minim transit', 'Lebih sedikit pergantian layanan'],
  ['longgar', 'Lebih longgar', 'Memprioritaskan pola yang lebih nyaman'],
]

function StopInput({ label, stop, onPick, mode, onModeChange, placeholder }) {
  const [text, setText] = useState(stop ? dispName(stop) : '')
  const [open, setOpen] = useState(false)
  const [cands, setCands] = useState([])
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)
  const box = useRef(null)
  const reqId = useRef(0)

  useEffect(() => {
    const close = (event) => { if (box.current && !box.current.contains(event.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const doSearch = async (query, selectedMode) => {
    const id = ++reqId.current
    setBusy(true)
    try {
      const response = await searchStops(query, selectedMode || undefined, 7)
      if (id === reqId.current) setCands(response.candidates)
    } catch { if (id === reqId.current) setCands([]) }
    finally { if (id === reqId.current) setBusy(false) }
  }

  const onChange = (event) => {
    const next = event.target.value
    setText(next)
    if (stop) onPick(null)
    setOpen(true)
    clearTimeout(timer.current)
    setCands([])
    if (next.trim()) timer.current = setTimeout(() => doSearch(next.trim(), mode), 250)
  }

  return (
    <div className="stopbox" ref={box}>
      <label className="field-label">{label}</label>
      <div className="stop-control">
        <span className={`place-marker ${label === 'Dari' ? 'origin' : 'destination'}`} aria-hidden />
        <input
          className="stop-input"
          value={stop ? dispName(stop) : text}
          placeholder={placeholder}
          onChange={onChange}
          onFocus={() => {
            setOpen(true)
            if (text.trim() && cands.length === 0 && !busy) doSearch(text.trim(), mode)
          }}
          aria-label={`${label} — nama stasiun atau halte`}
        />
        <select className="mode-select inline-mode" value={mode || ''} onChange={(event) => onModeChange(event.target.value || null)} aria-label={`Batasi moda untuk ${label.toLowerCase()}`}>
          <option value="">Semua moda</option>
          {MODES.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </div>
      {stop && (
        <div className="stop-picked">
          <span className="mode-badge" style={badgeStyle(stop.mode)}>{stop.mode}</span>
          <span>{dispName(stop)}</span>
          <button type="button" className="clear-btn" aria-label={`Hapus ${label.toLowerCase()}`} onClick={() => { onPick(null); setText('') }}>×</button>
        </div>
      )}
      {open && text.trim() && (
        <ul className="cand">
          {busy && <li className="cand-busy">Mencari titik terdekat…</li>}
          {!busy && cands.length === 0 && <li className="cand-busy">Belum ada kecocokan. Coba nama yang lebih pendek.</li>}
          {cands.map((candidate) => (
            <li key={candidate.stop_id}>
              <button type="button" onClick={() => { onPick(candidate); setText(dispName(candidate)); setOpen(false) }}>
                <span className="mode-badge" style={badgeStyle(candidate.mode)}>{candidate.mode}</span>
                <span className="cand-name">{candidate.display || candidate.name}</span>
                {candidate.aliases?.length > 0 && <span className="cand-alias">{candidate.aliases[0]}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function badgeStyle(mode) {
  const color = MODE_COLORS[mode] || '#536578'
  return { background: `${color}16`, color, borderColor: `${color}35` }
}

function RouteLeg({ leg, index }) {
  const isRide = leg.type === 'ride'
  const color = isRide ? (MODE_COLORS[leg.mode] || '#0B1F33') : WALK_COLOR
  const passedStops = isRide ? (leg.passedStops || []) : (leg.via || [])
  const stopCount = passedStops.length
  const canExpand = isRide ? stopCount > 1 : stopCount > 0
  const startLabel = isRide ? 'Naik di' : 'Mulai berjalan dari'
  const endLabel = isRide ? 'Turun di' : 'Sampai di'
  const crowdLabel = leg.crowd?.category?.replaceAll('_', ' ')

  return (
    <li className={`seg seg-${leg.type}`}>
      <span className="seg-dot" style={{ '--leg-color': color }} aria-hidden />
      <article className="seg-body">
        <div className="seg-head">
          <span className="seg-kind">
            {isRide ? (
              <>
                <span className="mode-badge" style={badgeStyle(leg.mode)}>{leg.mode}</span>
                {leg.corridor && <b className="seg-corridor">{leg.corridor}</b>}
                <strong>{leg.line || 'Layanan angkutan'}</strong>
              </>
            ) : <><span className="walk-symbol" aria-hidden>↟</span><strong>Berjalan untuk transit</strong></>}
          </span>
          <span className="seg-time">
            {isRide
              ? <>{fmtTime(leg.travel_sec)}{leg.wait_sec > 0 && <small>tunggu ±{fmtTime(leg.wait_sec)}</small>}</>
              : <>±{fmtTime(leg.walk_sec)}</>}
          </span>
        </div>

        <div className="seg-route" aria-label={`${startLabel} ${dispName(leg.from)}, ${endLabel} ${dispName(leg.to)}`}>
          <span><small>{startLabel}</small><strong>{dispName(leg.from)}</strong></span>
          <i aria-hidden>→</i>
          <span><small>{endLabel}</small><strong>{dispName(leg.to)}</strong></span>
        </div>

        <div className="seg-meta">
          {isRide && <span>{stopCount === 1 ? 'Langsung · 1 pemberhentian' : `${stopCount} pemberhentian`}</span>}
          {leg.crowd && <span className={`crowd-badge crowd-${leg.crowd.category}`}>{crowdLabel} · perkiraan saat naik {leg.crowd.board_time}</span>}
        </div>

        {canExpand && (
          <details className="stop-details">
            <summary>
              <span className="summary-closed">{isRide ? `Lihat ${stopCount} pemberhentian` : `Lihat ${stopCount} titik yang dilewati`}</span>
              <span className="summary-open">{isRide ? 'Sembunyikan pemberhentian' : 'Sembunyikan titik yang dilewati'}</span>
              <span className="detail-chevron" aria-hidden>⌄</span>
            </summary>
            <ol className="passed-stop-list" aria-label={isRide ? `Pemberhentian pada leg ${index + 1}` : `Titik berjalan kaki pada leg ${index + 1}`}>
              {passedStops.map((stop, stopIndex) => {
                const isDestination = isRide && stopIndex === passedStops.length - 1
                return (
                  <li key={`${stop.stop_id || dispName(stop)}-${stopIndex}`} className={isDestination ? 'passed-stop destination' : 'passed-stop'}>
                    <span className="passed-stop-node" aria-hidden />
                    <span className="passed-stop-copy">
                      <strong>{dispName(stop)}</strong>
                      <small>{isDestination ? 'Turun di sini' : (isRide ? 'Dilewati' : 'Jalur berjalan kaki')}</small>
                    </span>
                  </li>
                )
              })}
            </ol>
          </details>
        )}
      </article>
    </li>
  )
}

function FitBounds({ points }) {
  const map = useMap()
  useEffect(() => {
    if (points.length === 0) return undefined
    let frame
    const fit = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        map.invalidateSize()
        map.fitBounds(L.latLngBounds(points), { padding: [88, 76] })
      })
    }
    fit()
    window.addEventListener('resize', fit)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', fit)
    }
  }, [points, map])
  return null
}

function transferIcon(point) {
  const fromColor = MODE_COLORS[point.fromMode] || '#536578'
  const toColor = MODE_COLORS[point.toMode] || '#536578'
  const label = String(point.label).replace(/[^0-9AB]/g, '')
  const iconAnchor = point.phase === 'exit' ? [31, 18] : point.phase === 'entry' ? [5, 18] : [18, 18]
  return L.divIcon({
    className: `transfer-div-icon transfer-icon-${point.phase}`,
    html: `<span class="transfer-pin" style="--transfer-from:${fromColor};--transfer-to:${toColor}"><b>${label}</b></span>`,
    iconSize: [36, 36],
    iconAnchor,
    popupAnchor: [0, -19],
  })
}

function JourneyMap({ result }) {
  const segments = result?.status === 'ok' ? result.segments : []
  const points = useMemo(
    () => (result?.status === 'ok' ? result.segments : []).flatMap((segment) => [[segment.from.lat, segment.from.lon], [segment.to.lat, segment.to.lon]]),
    [result],
  )
  const mapData = useMemo(() => buildRouteMapData(result), [result])
  return (
    <div className="journey-map">
      <MapContainer center={[-6.24, 106.84]} zoom={11} scrollWheelZoom style={{ height: '100%', width: '100%' }}>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {segments.map((segment, index) => (
          <Polyline
            key={`${segment.from.stop_id}-${segment.to.stop_id}-${index}`}
            positions={[[segment.from.lat, segment.from.lon], [segment.to.lat, segment.to.lon]]}
            pathOptions={{
              color: segment.type === 'walk' ? WALK_COLOR : (MODE_COLORS[segment.mode] || '#0B1F33'),
              weight: segment.type === 'walk' ? 3 : 6,
              dashArray: segment.type === 'walk' ? '6 8' : undefined,
              opacity: 0.92,
            }}
          />
        ))}
        {result?.status === 'ok' && (
          <>
            {mapData.waypoints.map((stop) => (
              <CircleMarker
                key={`walk-${stop.stop_id}`}
                center={[stop.lat, stop.lon]}
                radius={5}
                pathOptions={{ color: '#fff', weight: 2, fillColor: WALK_COLOR, fillOpacity: 0.95 }}
              >
                <Tooltip direction="top" offset={[0, -6]}>Lewati &middot; {dispName(stop)}</Tooltip>
              </CircleMarker>
            ))}
            {mapData.transfers.map((point) => (
              <Marker key={`${point.event}-${point.phase}-${point.stop.stop_id}`} position={[point.stop.lat, point.stop.lon]} icon={transferIcon(point)} zIndexOffset={700}>
                <Tooltip
                  permanent
                  className="transfer-map-label"
                  direction={point.phase === 'entry' ? 'bottom' : 'top'}
                  offset={[0, point.phase === 'entry' ? 18 : -18]}
                >
                  {point.label} &middot; {dispName(point.stop)}
                </Tooltip>
                <Popup className="transfer-map-popup">
                  <div className="transfer-popup-content">
                    <span>{point.title}</span>
                    <strong>{dispName(point.stop)}</strong>
                    <p>{point.instruction}</p>
                    {point.walkingSeconds > 0 && <small>Jalan kaki antar titik &plusmn;{fmtTime(point.walkingSeconds)}</small>}
                  </div>
                </Popup>
              </Marker>
            ))}
            <CircleMarker center={[result.origin.lat, result.origin.lon]} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: '#1769E0', fillOpacity: 1 }}>
              <Tooltip permanent className="endpoint-map-label" direction="left" offset={[-10, 0]}>Dari · {dispName(result.origin)}</Tooltip>
            </CircleMarker>
            <CircleMarker center={[result.dest.lat, result.dest.lon]} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: '#D84A3A', fillOpacity: 1 }}>
              <Tooltip permanent className="endpoint-map-label" direction="right" offset={[10, 0]}>Ke · {dispName(result.dest)}</Tooltip>
            </CircleMarker>
            <FitBounds points={points} />
          </>
        )}
      </MapContainer>
      {!result && (
        <div className="map-empty-card">
          <span className="map-empty-icon" aria-hidden>⌁</span>
          <strong>Jaringan Jabodetabek</strong>
          <p>Pilih titik asal dan tujuan. Rute akan digambar di peta ini.</p>
        </div>
      )}
      {result && mapData.transferCount > 0 && (
        <div className="map-transfer-count" aria-label={`${mapData.transferCount} kali perpindahan layanan`}>
          <strong>{mapData.transferCount}</strong>
          <span>perpindahan</span>
        </div>
      )}
      <div className="map-legend">
        {Object.entries(MODE_COLORS).map(([mode, color]) => <span key={mode}><i style={{ background: color }} />{mode}</span>)}
        <span><i style={{ background: WALK_COLOR }} />Jalan kaki</span>
        {result && mapData.transferCount > 0 && <span><b className="transfer-legend-pin">1</b>Titik transfer</span>}
      </div>
    </div>
  )
}

export default function Planner() {
  const [origin, setOrigin] = useState(null)
  const [dest, setDest] = useState(null)
  const [originMode, setOriginMode] = useState(null)
  const [destMode, setDestMode] = useState(null)
  const [prefer, setPrefer] = useState('tercepat')
  const [depTime, setDepTime] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const lastReq = useRef(null)
  const routeLegs = useMemo(() => buildRouteDetailData(result), [result])

  const run = async (nextOrigin = origin, nextDest = dest, nextPrefer = prefer, nextTime = depTime) => {
    if (!nextOrigin || !nextDest) return
    setBusy(true)
    setError(null)
    lastReq.current = { origin: nextOrigin, dest: nextDest, prefer: nextPrefer, depTime: nextTime }
    try {
      const response = await findRoute({
        origin: dispName(nextOrigin), dest: dispName(nextDest), prefer: nextPrefer,
        origin_mode: originMode, dest_mode: destMode, dep_time: nextTime,
      })
      setResult(response)
    } catch (requestError) {
      setError(requestError.message)
      setResult(null)
    } finally { setBusy(false) }
  }

  const swap = () => {
    setOrigin(dest); setDest(origin)
    setOriginMode(destMode); setDestMode(originMode)
    setResult(null); setError(null)
  }

  const pickAmbiguous = (side, stop) => {
    if (side === 'origin') setOrigin(stop); else setDest(stop)
    const request = lastReq.current
    if (!request) return
    run(side === 'origin' ? stop : request.origin, side === 'dest' ? stop : request.dest, request.prefer, request.depTime)
  }

  return (
    <div className="page journey-page">
      <div className="journey-workspace">
        <section className="journey-form-panel" aria-label="Form pencarian perjalanan">
          <div className="section-intro"><span className="section-kicker">Perjalanan baru</span><h2>Dari mana Anda berangkat?</h2><p>Pilih stasiun atau halte. Anda dapat membatasi hasil berdasarkan moda.</p></div>
          <div className="place-fields">
            <StopInput label="Dari" stop={origin} onPick={setOrigin} mode={originMode} onModeChange={setOriginMode} placeholder="Manggarai, Lebak Bulus…" />
            <button className="swap-button" onClick={swap} disabled={!origin && !dest} aria-label="Tukar asal dan tujuan">⇅</button>
            <StopInput label="Ke" stop={dest} onPick={setDest} mode={destMode} onModeChange={setDestMode} placeholder="Bogor, Dukuh Atas…" />
          </div>

          <fieldset className="preference-fieldset">
            <legend>Prioritas perjalanan</legend>
            <div className="preference-grid">
              {PREFS.map(([value, label, description]) => (
                <button key={value} type="button" className={prefer === value ? 'preference-option active' : 'preference-option'} onClick={() => setPrefer(value)} title={description}>
                  <span className="preference-radio" aria-hidden />{label}
                </button>
              ))}
            </div>
          </fieldset>

          <label className="departure-field"><span className="field-label">Waktu berangkat</span><input type="time" value={depTime} onChange={(event) => setDepTime(event.target.value)} /><small>Kosongkan untuk menggunakan waktu sekarang.</small></label>
          {error && <p className="error">Rute belum dapat dihitung: {error}</p>}
          <button className="btn primary journey-submit" disabled={!origin || !dest || busy} onClick={() => run()}>{busy ? 'Menghitung perjalanan…' : 'Lihat pilihan perjalanan'}</button>
        </section>

        <section className="journey-map-panel" aria-label="Peta perjalanan"><JourneyMap result={result?.status === 'ok' ? result : null} /></section>
      </div>

      {result?.status === 'ok' && (
        <section className="journey-result card">
          <div className="result-heading">
            <div><span className="section-kicker">Pilihan {result.preference}</span><h2>{dispName(result.origin)} <span aria-hidden>→</span> {dispName(result.dest)}</h2></div>
            <span className="label-pill proxy">Waktu proksi</span>
          </div>
          <div className="route-metrics">
            <div className="primary-metric"><strong>{fmtTime(result.time_sec)}</strong><span>Total perjalanan</span></div>
            <div><strong>Rp{result.fare.toLocaleString('id-ID')}</strong><span>Tarif minimum</span></div>
            <div><strong>{result.transfers}</strong><span>Pergantian layanan</span></div>
          </div>
          <ol className="timeline">
            {routeLegs.map((leg, index) => (
              <RouteLeg
                key={`${result.origin.stop_id}-${result.dest.stop_id}-${leg.type}-${leg.from.stop_id}-${leg.to.stop_id}-${index}`}
                leg={leg}
                index={index}
              />
            ))}
          </ol>
          <details className="method-details"><summary>Bagaimana estimasi ini dihitung?</summary><p>{result.disclaimer}</p>{result.crowding?.segments?.length > 0 && <p>Kepadatan menggunakan pola jam sibuk dan rasio akhir pekan. Ini bukan pengukuran langsung di dalam kendaraan.</p>}</details>
        </section>
      )}

      {result?.status === 'ambiguous' && (
        <section className="card decision-card"><span className="section-kicker">Perlu konfirmasi</span><h2>Pilih titik yang Anda maksud</h2><p className="note">Beberapa stasiun atau halte memiliki nama yang mirip.</p>
          {Object.entries(result.candidates).map(([side, candidates]) => (
            <div key={side} className="ambig"><p className="field-label">{side === 'origin' ? 'Dari' : 'Ke'}</p><div className="chips">{candidates.map((candidate) => <button key={candidate.stop_id} className="chip" onClick={() => pickAmbiguous(side, candidate)}><span className="mode-badge" style={badgeStyle(candidate.mode)}>{candidate.mode}</span>{candidate.display || candidate.name}</button>)}</div></div>
          ))}
        </section>
      )}

      {result?.status === 'no_route' && <section className="card decision-card"><span className="section-kicker">Belum terhubung</span><h2>Rute tidak ditemukan</h2><p>Coba titik lain atau hapus pembatas moda pada kolom asal dan tujuan.</p></section>}
    </div>
  )
}

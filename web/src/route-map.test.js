import assert from 'node:assert/strict'
import test from 'node:test'
import { buildRouteMapData } from './route-map.js'

const stop = (stop_id, name, mode, lat) => ({ stop_id, name, mode, lat, lon: 106.82 + lat / 100 })

test('transfer berjalan kaki mempertahankan titik turun, titik naik, dan waypoint', () => {
  const setiabudi = stop('MRT_setiabudi', 'Setiabudi Astra', 'MRT', -6.209)
  const dukuhAtas = stop('MRT_dukuh', 'Dukuh Atas BNI', 'MRT', -6.201)
  const hub = stop('BRT_hub', 'Transport Hub Dukuh Atas', 'BRT', -6.202)
  const sudirman = stop('KRL_sudirman', 'Sudirman', 'KRL', -6.203)
  const tambun = stop('KRL_tambun', 'Tambun', 'KRL', -6.259)
  const result = {
    origin: setiabudi,
    dest: tambun,
    itinerary: [
      { type: 'ride', mode: 'MRT', line_id: 'MRT_NS', route_id: 'out', line: 'Line 1', from: setiabudi, to: dukuhAtas },
      { type: 'walk', from: dukuhAtas, to: sudirman, via: [hub], walk_sec: 200 },
      { type: 'ride', mode: 'KRL', line_id: 'KRL_C', route_id: 'in', line: 'Lin Cikarang', from: sudirman, to: tambun },
    ],
  }

  const mapData = buildRouteMapData(result)
  assert.equal(mapData.transferCount, 1)
  assert.deepEqual(mapData.transfers.map((point) => [point.label, point.stop.stop_id]), [
    ['1A', 'MRT_dukuh'],
    ['1B', 'KRL_sudirman'],
  ])
  assert.deepEqual(mapData.waypoints.map((point) => point.stop_id), ['BRT_hub'])
  assert.equal(mapData.transfers[0].kind, 'mode')
})

test('pindah jalur pada moda yang sama menghasilkan satu marker', () => {
  const origin = stop('KRL_a', 'Stasiun A', 'KRL', -6.1)
  const interchange = stop('KRL_x', 'Manggarai', 'KRL', -6.2)
  const dest = stop('KRL_b', 'Stasiun B', 'KRL', -6.3)
  const result = {
    origin,
    dest,
    itinerary: [
      { type: 'ride', mode: 'KRL', line_id: 'KRL_BOGOR', route_id: 'out', line: 'Lin Bogor', from: origin, to: interchange },
      { type: 'ride', mode: 'KRL', line_id: 'KRL_CIKARANG', route_id: 'out', line: 'Lin Cikarang', from: interchange, to: dest },
    ],
  }

  const mapData = buildRouteMapData(result)
  assert.equal(mapData.transferCount, 1)
  assert.equal(mapData.transfers.length, 1)
  assert.equal(mapData.transfers[0].label, '1')
  assert.equal(mapData.transfers[0].kind, 'line')
})

test('logika tidak bergantung pada pasangan moda tertentu', () => {
  const origin = stop('MRT_a', 'MRT A', 'MRT', -6.1)
  const mrtExit = stop('MRT_b', 'MRT B', 'MRT', -6.2)
  const brtEntry = stop('BRT_a', 'Halte A', 'BRT', -6.21)
  const lrtEntry = stop('LRT_a', 'LRT A', 'LRT', -6.31)
  const dest = stop('LRT_b', 'LRT B', 'LRT', -6.4)
  const result = {
    origin,
    dest,
    itinerary: [
      { type: 'ride', mode: 'MRT', line_id: 'MRT', route_id: '1', from: origin, to: mrtExit },
      { type: 'walk', from: mrtExit, to: brtEntry, walk_sec: 120 },
      { type: 'ride', mode: 'BRT', line_id: 'BRT_1', route_id: '1', from: brtEntry, to: brtEntry },
      { type: 'walk', from: brtEntry, to: lrtEntry, walk_sec: 180 },
      { type: 'ride', mode: 'LRT', line_id: 'LRT_1', route_id: '1', from: lrtEntry, to: dest },
    ],
  }

  const mapData = buildRouteMapData(result)
  assert.equal(mapData.transferCount, 2)
  assert.deepEqual(mapData.transfers.map((point) => point.label), ['1A', '1B', '2A', '2B'])
  assert.deepEqual(mapData.transfers.map((point) => point.kind), ['mode', 'mode', 'mode', 'mode'])
})

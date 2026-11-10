import assert from 'node:assert/strict'
import test from 'node:test'
import { buildRouteDetailData } from './route-detail.js'

const stop = (stop_id, name, mode) => ({ stop_id, name, mode, lat: -6.2, lon: 106.8 })

test('mengelompokkan edge satu layanan dan mempertahankan urutan pemberhentian', () => {
  const sudirman = stop('KRL_sudirman', 'Sudirman', 'KRL')
  const manggarai = stop('KRL_manggarai', 'Manggarai', 'KRL')
  const bekasi = stop('KRL_bekasi', 'Bekasi', 'KRL')
  const tambun = stop('KRL_tambun', 'Tambun', 'KRL')
  const segments = [
    [sudirman, manggarai],
    [manggarai, bekasi],
    [bekasi, tambun],
  ].map(([from, to]) => ({
    type: 'ride', mode: 'KRL', line_id: 'KRL_C', route_id: 'out', line: 'Lin Cikarang',
    from, to, travel_sec: 300, wait_sec: 0, fare: 0,
  }))
  const result = {
    status: 'ok', segments,
    itinerary: [{ ...segments[0], to: tambun, edge_count: 3, travel_sec: 900 }],
    crowding: { segments: [
      { category: 'sedang', board_time: '13:51' },
      { category: 'padat', board_time: '13:56' },
      { category: 'padat', board_time: '14:02' },
    ] },
  }

  const legs = buildRouteDetailData(result)
  assert.equal(legs.length, 1)
  assert.equal(legs[0].edgeCount, 3)
  assert.deepEqual(legs[0].passedStops.map((item) => item.name), ['Manggarai', 'Bekasi', 'Tambun'])
  assert.deepEqual(legs[0].crowd, { category: 'sedang', board_time: '13:51' })
})

test('perpindahan berjalan kaki memisahkan dua leg kendaraan', () => {
  const setiabudi = stop('MRT_setiabudi', 'Setiabudi Astra', 'MRT')
  const dukuhAtas = stop('MRT_dukuh', 'Dukuh Atas BNI', 'MRT')
  const hub = stop('BRT_hub', 'Transport Hub Dukuh Atas', 'BRT')
  const sudirman = stop('KRL_sudirman', 'Sudirman', 'KRL')
  const tambun = stop('KRL_tambun', 'Tambun', 'KRL')
  const result = {
    status: 'ok',
    segments: [
      { type: 'ride', mode: 'MRT', line_id: 'MRT_NS', route_id: 'out', from: setiabudi, to: dukuhAtas, travel_sec: 120, wait_sec: 60 },
      { type: 'walk', from: dukuhAtas, to: hub, walk_sec: 90 },
      { type: 'walk', from: hub, to: sudirman, walk_sec: 90 },
      { type: 'ride', mode: 'KRL', line_id: 'KRL_C', route_id: 'out', from: sudirman, to: tambun, travel_sec: 2400, wait_sec: 300 },
    ],
  }

  const legs = buildRouteDetailData(result)
  assert.equal(legs.length, 3)
  assert.deepEqual(legs.map((leg) => leg.type), ['ride', 'walk', 'ride'])
  assert.deepEqual(legs[1].via.map((item) => item.name), ['Transport Hub Dukuh Atas'])
  assert.deepEqual(legs[0].passedStops.map((item) => item.name), ['Dukuh Atas BNI'])
  assert.deepEqual(legs[2].passedStops.map((item) => item.name), ['Tambun'])
})

test('perubahan jalur tetap menjadi leg terpisah meski modanya sama', () => {
  const a = stop('KRL_a', 'A', 'KRL')
  const x = stop('KRL_x', 'Manggarai', 'KRL')
  const b = stop('KRL_b', 'B', 'KRL')
  const result = {
    status: 'ok',
    segments: [
      { type: 'ride', mode: 'KRL', line_id: 'BOGOR', route_id: 'out', from: a, to: x, travel_sec: 300, wait_sec: 0 },
      { type: 'ride', mode: 'KRL', line_id: 'CIKARANG', route_id: 'out', from: x, to: b, travel_sec: 400, wait_sec: 60 },
    ],
  }

  const legs = buildRouteDetailData(result)
  assert.equal(legs.length, 2)
  assert.equal(legs[0].to.name, 'Manggarai')
  assert.equal(legs[1].from.name, 'Manggarai')
})

test('perubahan pola internal pada jalur yang sama bukan transit', () => {
  const sudirman = stop('KRL_sudirman', 'Sudirman', 'KRL')
  const matraman = stop('KRL_matraman', 'Matraman', 'KRL')
  const cikarang = stop('KRL_cikarang', 'Cikarang', 'KRL')
  const result = {
    status: 'ok',
    segments: [
      { type: 'ride', mode: 'KRL', line_id: 'KRL_C', route_id: 'in', from: sudirman, to: matraman, travel_sec: 840, wait_sec: 300 },
      { type: 'ride', mode: 'KRL', line_id: 'KRL_C', route_id: 'out', from: matraman, to: cikarang, travel_sec: 3240, wait_sec: 0 },
    ],
  }

  const legs = buildRouteDetailData(result)
  assert.equal(legs.length, 1)
  assert.equal(legs[0].from.name, 'Sudirman')
  assert.equal(legs[0].to.name, 'Cikarang')
  assert.deepEqual(legs[0].passedStops.map((item) => item.name), ['Matraman', 'Cikarang'])
})

test('layanan sama tetap dipisah pada batas tujuan antara', () => {
  const a = stop('KRL_a', 'Depok', 'KRL')
  const b = stop('KRL_b', 'Senayan', 'KRL')
  const c = stop('KRL_c', 'Tambun', 'KRL')
  const result = {
    status: 'ok',
    segments: [
      { type: 'ride', mode: 'KRL', line_id: 'KRL_TEST', from: a, to: b, travel_sec: 300, wait_sec: 0, journey_leg: 1 },
      { type: 'ride', mode: 'KRL', line_id: 'KRL_TEST', from: b, to: c, travel_sec: 400, wait_sec: 0, journey_leg: 2 },
    ],
  }
  const legs = buildRouteDetailData(result)
  assert.equal(legs.length, 2)
  assert.deepEqual(legs.map((leg) => leg.journey_leg), [1, 2])
})

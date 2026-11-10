import assert from 'node:assert/strict'
import test from 'node:test'
import { pickPrefillCandidate, resolvedJourneyPrefill } from './journey-prefill.js'

const mrt = { stop_id: 'MRT_senayan', name: 'Senayan', display: 'Senayan Mastercard', mode: 'MRT' }
const brt = { stop_id: 'BRT_senayan', name: 'Senayan', display: null, mode: 'BRT' }

test('tombol perjalanan hanya tersedia setelah kedua stop_id teresolusi', () => {
  assert.equal(resolvedJourneyPrefill({
    intent: 'route_planning',
    slots: { origin: 'Depok', dest: 'Senayan' },
  }), null)

  const journey = { origin: { stop_id: 'KRL_depok' }, dest: brt, preference: 'tercepat' }
  assert.deepEqual(resolvedJourneyPrefill({ journey }), {
    ...journey,
    points: [journey.origin, journey.dest],
    waypoints: [],
  })
})

test('prefill mempertahankan semua titik perjalanan berurutan', () => {
  const depok = { stop_id: 'KRL_depok', name: 'Depok', mode: 'KRL' }
  const tambun = { stop_id: 'KRL_tambun', name: 'Tambun', mode: 'KRL' }
  const journey = { origin: depok, dest: tambun, points: [depok, brt, tambun], preference: 'min_transfers' }
  const prefill = resolvedJourneyPrefill({ journey })
  assert.deepEqual(prefill.points.map((point) => point.stop_id), ['KRL_depok', 'BRT_senayan', 'KRL_tambun'])
  assert.deepEqual(prefill.waypoints, [brt])
})

test('prefill tidak membatasi rangkaian panjang atau titik yang berulang', () => {
  const bekasi = { stop_id: 'KRL_bekasi', name: 'Bekasi Timur', mode: 'KRL' }
  const tangerang = { stop_id: 'KRL_tangerang', name: 'Tangerang', mode: 'KRL' }
  const depok = { stop_id: 'KRL_depok', name: 'Depok', mode: 'KRL' }
  const journey = {
    origin: bekasi,
    dest: brt,
    points: [bekasi, brt, tangerang, depok, brt],
    preference: 'tercepat',
  }
  const prefill = resolvedJourneyPrefill({ journey })
  assert.deepEqual(prefill.points.map((point) => point.stop_id), [
    'KRL_bekasi', 'BRT_senayan', 'KRL_tangerang', 'KRL_depok', 'BRT_senayan',
  ])
  assert.deepEqual(prefill.waypoints.map((point) => point.stop_id), [
    'BRT_senayan', 'KRL_tangerang', 'KRL_depok',
  ])
})

test('prefill memilih stop_id hasil chatbot walaupun nama lintas moda sama', () => {
  const response = { candidates: [mrt, brt] }
  assert.equal(pickPrefillCandidate(response, brt), brt)
})

test('moda menjadi fallback bila stop_id tidak ditemukan', () => {
  const response = { candidates: [mrt, brt] }
  const target = { stop_id: 'BRT_lama', name: 'Senayan', mode: 'BRT' }
  assert.equal(pickPrefillCandidate(response, target), brt)
})

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
  assert.equal(resolvedJourneyPrefill({ journey }), journey)
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

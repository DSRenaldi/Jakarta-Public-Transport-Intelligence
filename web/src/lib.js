// Konstanta & helper bersama (dipakai Planner, Dashboard, dst.)

// Warna garis moda — "bahasa peta lin" (dipakai legend, badge, chart, map).
// KRL = hijau mengikuti brand KAI Commuter; BRT = kuning TransJakarta.
export const MODE_COLORS = {
  MRT: '#1B5FD9',
  KRL: '#0B7A4B',
  LRT: '#0E8A80',
  BRT: '#F2A900',
}

export const WALK_COLOR = '#77817a'

// Nama tampilan stop: nama berhak penamaan (display) bila ada, selain itu
// nama kanonik. Cocok dgn label peta resmi (mis. "Senayan Mastercard").
export function dispName(s) {
  if (!s) return '?'
  return (s.display && s.display !== s.name) ? s.display : s.name
}

export function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec))
  const h = Math.floor(sec / 3600)
  const m = Math.round((sec % 3600) / 60)
  if (h > 0) return m > 0 ? `${h} j ${m} mnt` : `${h} j`
  if (m > 0) return `${m} mnt`
  return `${sec} dtk`
}

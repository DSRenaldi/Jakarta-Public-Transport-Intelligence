// Konstanta & helper bersama (dipakai Planner, Dashboard, dst.)

export const MODE_COLORS = {
  MRT: '#1E88E5',
  KRL: '#0D47A1',
  LRT: '#00897B',
  BRT: '#F9A825',
}

export const WALK_COLOR = '#7d8590'

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

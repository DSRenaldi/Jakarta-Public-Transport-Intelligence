// Klien API JPTI. Di dev, request diproksikan Vite ke FastAPI (:8000).
const BASE = ''

async function api(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch { /* bukan JSON */ }
    throw new Error(detail)
  }
  return res.json()
}

export const getHealth = () => api('/api/health')
export const getMeta = () => api('/api/meta')
export const getLines = (mode) =>
  api(`/api/network/lines${mode ? `?mode=${encodeURIComponent(mode)}` : ''}`)

export const searchStops = (q, mode, limit = 6) => {
  const p = new URLSearchParams({ q, limit: String(limit) })
  if (mode) p.set('mode', mode)
  return api(`/api/stops/search?${p}`)
}

export const findRoute = ({ origin, dest, prefer, origin_mode, dest_mode, dep_time }) =>
  api('/api/route', {
    method: 'POST',
    body: JSON.stringify({ origin, dest, prefer, origin_mode: origin_mode || null, dest_mode: dest_mode || null, dep_time: dep_time || null }),
  })

export const ragQuery = ({ query, top_k, operator, mode, doc_type, label }) =>
  api('/api/rag', {
    method: 'POST',
    body: JSON.stringify({ query, top_k, operator: operator || null, mode: mode || null, doc_type: doc_type || null, label: label || null }),
  })

export const askChat = (message, sessionId, userId) =>
  api('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message,
      session_id: sessionId,
      user_id: userId || null,
    }),
  })

export const getChatStatus = () => api('/api/chat/status')

export const clearChatSession = (sessionId) =>
  api(`/api/chat/session?session_id=${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })

// Persistent user memory (§35) — user_id = UUID opaque buatan klien
export const getMemory = (userId) =>
  api(`/api/memory?user_id=${encodeURIComponent(userId)}`)

export const deleteMemory = (userId, memoryId) =>
  api(`/api/memory/${memoryId}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })

export const deleteAllMemory = (userId) =>
  api(`/api/memory?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })

export const getRidership = (mode, periodType) => {
  const p = new URLSearchParams()
  if (mode) p.set('mode', mode)
  if (periodType) p.set('period_type', periodType)
  const q = p.toString()
  return api(`/api/ridership${q ? `?${q}` : ''}`)
}

import { useEffect, useRef, useState } from 'react'
import { askChat, clearChatSession, deleteAllMemory, deleteMemory, getChatStatus, getMemory } from '../api.js'

const WELCOME = 'Halo! Saya siap membantu merencanakan rute, membandingkan penumpang, memeriksa tarif dan jadwal, atau mencari informasi dari dokumen resmi transportasi Jabodetabek.'
const SUGGESTION_GROUPS = [
  { label: 'Rencanakan', question: 'Bagaimana dari Dukuh Atas ke Lebak Bulus?', hint: 'Rute, waktu, dan perpindahan' },
  { label: 'Cari data', question: 'Berapa jumlah penumpang MRT tahun 2025?', hint: 'Statistik dengan sumber' },
  { label: 'Bandingkan', question: 'Moda apa yang penumpangnya paling banyak?', hint: 'Perbandingan antarmoda' },
  { label: 'Pilih waktu', question: 'Jam berapa perjalanan MRT biasanya paling longgar?', hint: 'Perkiraan pola kepadatan' },
]
const CHAT_HISTORY_KEY = 'jpti_chat_messages_v1'
const INITIAL_MESSAGES = [{ role: 'bot', text: WELCOME }]
const MAX_SAVED_MESSAGES = 100
const INTENT_LABEL = {
  route_planning: 'rute', ridership_statistics: 'penumpang', mode_comparison: 'perbandingan moda',
  station_ranking: 'peringkat stasiun', fare_query: 'tarif', schedule_query: 'jadwal', crowding: 'kepadatan',
  policy_document: 'dokumen', other: 'umum',
}
const MEM_OPT_LABEL = { tercepat: 'rute tercepat', termurah: 'rute termurah', min_transfers: 'rute minim transit', longgar: 'rute lebih longgar' }

function createOpaqueId(prefix) {
  return typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function getStoredId(key, prefix) {
  let id = null
  try { id = localStorage.getItem(key) } catch { /* private mode */ }
  if (!id) {
    id = createOpaqueId(prefix)
    try { localStorage.setItem(key, id) } catch { /* private mode */ }
  }
  return id
}

function loadChatMessages() {
  try {
    const saved = JSON.parse(localStorage.getItem(CHAT_HISTORY_KEY) || 'null')
    if (!Array.isArray(saved) || saved.length === 0) return INITIAL_MESSAGES
    const valid = saved.filter((message) => message && ['user', 'bot'].includes(message.role) && typeof message.text === 'string')
    return valid.length ? valid.slice(-MAX_SAVED_MESSAGES) : INITIAL_MESSAGES
  } catch { return INITIAL_MESSAGES }
}

function memLabel(memory) {
  const value = memory.memory_value?.value
  if (memory.memory_key === 'optimization') return MEM_OPT_LABEL[value] || `rute: ${value}`
  if (memory.memory_key === 'preferred_mode') return `moda favorit: ${value}`
  if (memory.memory_key === 'max_walking_minutes') return `jalan kaki maksimal ${value} menit`
  if (memory.memory_key.startsWith('journey:')) return `rute rutin: ${memory.memory_value.origin} → ${memory.memory_value.dest}`
  return memory.memory_key
}

function Rich({ text }) {
  return <>{(text || '').split('\n').map((line, index) => {
    const isList = line.startsWith('- ')
    const body = isList ? line.slice(2) : line
    const parts = body.split(/\*\*(.+?)\*\*/g)
    return <div key={index} className={isList ? 'chat-li' : undefined}>{isList && <span className="chat-bullet" aria-hidden>•</span>}{parts.map((part, partIndex) => partIndex % 2 ? <strong key={partIndex}>{part}</strong> : part)}</div>
  })}</>
}

export default function ChatPage({ onOpenJourney }) {
  const [messages, setMessages] = useState(loadChatMessages)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [memories, setMemories] = useState([])
  const endRef = useRef(null)
  const sidRef = useRef(getStoredId('jpti_chat_sid', 'sid'))
  const uidRef = useRef(getStoredId('jpti_user_id', 'uid'))

  useEffect(() => { getChatStatus().then(setStatus).catch(() => {}) }, [])
  const refreshMemories = () => getMemory(uidRef.current).then((data) => setMemories(data.memories || [])).catch(() => {})
  useEffect(() => { refreshMemories() }, [])
  useEffect(() => {
    try { localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(messages.slice(-MAX_SAVED_MESSAGES))) } catch { /* storage unavailable */ }
  }, [messages])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, busy])

  const send = async (raw) => {
    const text = (raw ?? input).trim()
    if (!text || busy) return
    setInput(''); setBusy(true); setError(null); setMessages((current) => [...current, { role: 'user', text }])
    try {
      const response = await askChat(text, sidRef.current, uidRef.current)
      setMessages((current) => [...current, { role: 'bot', text: response.reply, ...response }])
      refreshMemories()
    } catch (requestError) { setError(requestError.message) }
    finally { setBusy(false) }
  }

  const removeMemory = async (memory) => {
    try { await deleteMemory(uidRef.current, memory.memory_id); refreshMemories() } catch (requestError) { setError(requestError.message) }
  }
  const clearAllMemories = async () => {
    try { await deleteAllMemory(uidRef.current); refreshMemories() } catch (requestError) { setError(requestError.message) }
  }
  const clearConversation = async () => {
    if (busy || messages.length === 1) return
    try { await clearChatSession(sidRef.current) } catch { /* rotating id is sufficient */ }
    try { localStorage.removeItem(CHAT_HISTORY_KEY); localStorage.removeItem('jpti_chat_sid') } catch { /* private mode */ }
    sidRef.current = getStoredId('jpti_chat_sid', 'sid')
    setInput(''); setError(null); setMessages(INITIAL_MESSAGES)
  }

  const llmOff = status && !status.llm.configured

  return (
    <div className="page assistant-page">
      <div className="assistant-layout">
        <section className="chat-frame" aria-label="Percakapan chat">
          <div className="chat-toolbar">
            <span className="assistant-presence"><span className="system-dot online" /><span><strong>Asisten siap</strong><small>Riwayat tersimpan di perangkat ini</small></span></span>
            <button type="button" className="chat-clear" onClick={clearConversation} disabled={busy || messages.length === 1}>Hapus percakapan</button>
          </div>
          <div className="chat-stream">
            {messages.map((message, index) => (
              <div key={index} className={message.role === 'user' ? 'msg user' : 'msg bot'}>
                <div className="bubble">
                  {message.role === 'user' ? message.text : <Rich text={message.text} />}
                  {message.role === 'bot' && message.intent && <p className="chat-meta">{INTENT_LABEL[message.intent] || message.intent}{message.data_label ? ` · data ${message.data_label}` : ''}{message.latency_ms != null ? ` · ${(message.latency_ms / 1000).toFixed(1)} detik` : ''}{message.cache_status === 'exact_hit' ? ' · dari cache' : message.cache_status === 'semantic_hit' ? ' · dari pertanyaan serupa' : ''}</p>}
                  {message.role === 'bot' && message.sources?.length > 0 && <div className="chat-sources">{message.sources.map((source) => <a key={source.n} className="chat-src" href={source.url || undefined} target={source.url ? '_blank' : undefined} rel="noopener" title={`${source.title || ''} — ${source.source_id || ''}`}>[{source.n}] {source.title}{source.pages?.[0] ? ` · halaman ${source.pages[0]}` : ''}{source.url ? ' ↗' : ''}</a>)}</div>}
                  {message.role === 'bot' && message.intent === 'route_planning' && message.slots?.origin && message.slots?.dest && onOpenJourney && (
                    <button
                      type="button"
                      className="chat-route-action"
                      onClick={() => onOpenJourney({
                        origin: message.slots.origin,
                        dest: message.slots.dest,
                        prefer: message.slots.preference || 'tercepat',
                      })}
                    >
                      <span aria-hidden>↗</span> Buka rute di Perjalanan
                    </button>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="msg bot"><div className="bubble"><span className="typing" aria-label="Asisten sedang menyusun jawaban"><i /><i /><i /></span></div></div>}
            <div ref={endRef} />
          </div>

          {messages.length === 1 && <div className="prompt-grid">{SUGGESTION_GROUPS.map((item) => (
            <button key={item.question} className="prompt-card" onClick={() => send(item.question)} disabled={busy}><span>{item.label}</span><strong>{item.question}</strong><small>{item.hint}</small></button>
          ))}</div>}
          {error && <p className="error chat-error">Pertanyaan belum dapat diproses: {error}</p>}
          <div className="chat-input-row">
            <input className="chat-input" value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && send()} placeholder="Tanyakan rute, tarif, jadwal, atau data…" aria-label="Pesan chat" disabled={busy} maxLength={1000} />
            <button className="btn primary send-button" onClick={() => send()} disabled={busy || !input.trim()}><span>Kirim</span><span aria-hidden>→</span></button>
          </div>
        </section>

        <aside className="assistant-context" aria-label="Konteks dan memori asisten">
          <div className="context-section"><span className="section-kicker">Konteks aktif</span><h2>Preferensi perjalanan</h2><p>Asisten menggunakan preferensi yang Anda minta untuk diingat. Memori dapat dihapus kapan saja.</p></div>
          {memories.length > 0 ? (
            <div className="memory-list">
              {memories.map((memory) => <div key={memory.memory_id} className="memory-item"><span className="memory-glyph" aria-hidden>◇</span><span><strong>{memLabel(memory)}</strong><small>Digunakan untuk rekomendasi berikutnya</small></span><button className="mem-x" aria-label={`Hapus memori ${memLabel(memory)}`} onClick={() => removeMemory(memory)}>×</button></div>)}
              <button className="text-button danger" onClick={clearAllMemories}>Hapus semua memori</button>
            </div>
          ) : <div className="empty-context"><span aria-hidden>◇</span><p>Belum ada preferensi yang disimpan.</p><small>Coba katakan: “Ingat saya lebih suka rute minim transit.”</small></div>}
          <div className="trust-card"><span className="trust-icon" aria-hidden>✓</span><div><strong>Jawaban dapat ditelusuri</strong><p>Statistik berasal dari database. Kebijakan dan dokumen menyertakan sumber.</p></div></div>
          <details className="system-details"><summary>Status sistem</summary>{status ? <p>Model intent {Math.round((status.intent_model?.accuracy_holdout ?? 0) * 100)}% · penyusun jawaban {status.llm.model}{llmOff ? ' · mode template' : ''}</p> : <p>Status belum tersedia.</p>}</details>
        </aside>
      </div>
    </div>
  )
}

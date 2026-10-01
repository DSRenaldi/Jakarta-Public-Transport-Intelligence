import { useEffect, useRef, useState } from 'react'
import { askChat, getChatStatus } from '../api.js'

const WELCOME = (
  'Halo! Saya asisten JPTI. Tanya saya soal rute antar-stasiun, jumlah ' +
  'penumpang, tarif, jadwal, kepadatan, atau dokumen resmi — untuk MRT ' +
  'Jakarta, KRL Commuter Line, LRT Jakarta, LRT Jabodebek, dan TransJakarta.'
)

const SUGGESTIONS = [
  'Bagaimana dari Dukuh Atas ke Lebak Bulus?',
  'Berapa jumlah penumpang MRT tahun 2025?',
  'Moda apa yang penumpangnya paling banyak?',
  'Berapa tarif MRT Jakarta?',
  'Jam berapa perjalanan MRT biasanya paling longgar?',
  'Jam operasional LRT Jakarta?',
]

const INTENT_LABEL = {
  route_planning: 'rute',
  ridership_statistics: 'penumpang',
  mode_comparison: 'perbandingan moda',
  station_ranking: 'peringkat stasiun',
  fare_query: 'tarif',
  schedule_query: 'jadwal',
  crowding: 'kepadatan',
  policy_document: 'dokumen',
  other: 'umum',
}

function getSessionId() {
  let id = null
  try { id = localStorage.getItem('jpti_chat_sid') } catch { /* private mode */ }
  if (!id) {
    id = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : `sid-${Date.now()}-${Math.random().toString(36).slice(2)}`
    try { localStorage.setItem('jpti_chat_sid', id) } catch { /* abaikan */ }
  }
  return id
}

// Render teks minimal: baris baru, poin "- ", dan **tebal** (tanpa lib external)
function Rich({ text }) {
  const lines = (text || '').split('\n')
  return (
    <>
      {lines.map((ln, i) => {
        const isLi = ln.startsWith('- ')
        const body = isLi ? ln.slice(2) : ln
        const parts = body.split(/\*\*(.+?)\*\*/g)
        return (
          <div key={i} className={isLi ? 'chat-li' : undefined}>
            {isLi && <span className="chat-bullet" aria-hidden>•</span>}
            {parts.map((p, j) => (j % 2 ? <strong key={j}>{p}</strong> : p))}
          </div>
        )
      })}
    </>
  )
}

export default function ChatPage() {
  const [messages, setMessages] = useState([{ role: 'bot', text: WELCOME }])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const endRef = useRef(null)
  const sidRef = useRef(getSessionId())

  useEffect(() => {
    getChatStatus().then(setStatus).catch(() => {})
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  const send = async (raw) => {
    const text = (raw ?? input).trim()
    if (!text || busy) return
    setInput('')
    setBusy(true)
    setError(null)
    setMessages((m) => [...m, { role: 'user', text }])
    try {
      const r = await askChat(text, sidRef.current)
      setMessages((m) => [...m, { role: 'bot', text: r.reply, ...r }])
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const lllmOff = status && !status.llm.configured

  return (
    <div className="page">
      <section className="card">
        <h2>Chat</h2>
        <p className="note">
          Asisten percakapan: intent dikenali model klasifikasi ML klasik, data
          diambil dari tool (rute, database penumpang, RAG dokumen resmi), dan
          jawaban disusun LLM. Angka selalu membawa label
          (<code>aktual</code>/<code>historis</code>/<code>prediksi</code>/<code>proksi</code>)
          dan sumber.
        </p>
        {status && (
          <p className="note small">
            Intent model: akurasi holdout {Math.round((status.intent_model?.accuracy_holdout ?? 0) * 100)}%
            {' '}· LLM {status.llm.model}{' '}
            {lllmOff ? '(belum dikonfigurasi — jawaban memakai template)' : ''}
          </p>
        )}
      </section>

      <section className="chat-frame" aria-label="Percakapan chat">
        <div className="chat-stream">
          {messages.map((m, i) => (
            <div key={i} className={m.role === 'user' ? 'msg user' : 'msg bot'}>
              {m.role === 'user' ? (
                <div className="bubble">{m.text}</div>
              ) : (
                <div className="bubble">
                  <Rich text={m.text} />
                  {m.intent && (
                    <p className="chat-meta">
                      {INTENT_LABEL[m.intent] || m.intent}
                      {m.data_label ? ` · data ${m.data_label}` : ''}
                      {m.latency_ms != null ? ` · ${(m.latency_ms / 1000).toFixed(1)} dtk` : ''}
                      {m.cache_status === 'exact_hit' ? ' · cached' : ''}
                      {m.llm === false ? ' · template' : ''}
                    </p>
                  )}
                  {m.sources?.length > 0 && (
                    <div className="chat-sources">
                      {m.sources.map((s) => (
                        <a
                          key={s.n}
                          className="chat-src"
                          href={s.url || undefined}
                          target={s.url ? '_blank' : undefined}
                          rel="noopener"
                          title={`${s.title || ''} — ${s.source_id || ''}${s.published_at ? ' · terbit ' + s.published_at : ''}`}
                        >
                          [{s.n}] {s.title}{s.pages?.[0] ? ` · hlm ${s.pages[0]}` : ''}
                          {s.url ? ' ↗' : ''}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {busy && (
            <div className="msg bot">
              <div className="bubble">
                <span className="typing" aria-label="mengetik"><i /><i /><i /></span>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {messages.length === 1 && (
          <div className="chat-suggest">
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>{s}</button>
              ))}
            </div>
          </div>
        )}

        {error && <p className="error" style={{ padding: '0 16px 8px', margin: 0 }}>Gagal: {error}</p>}

        <div className="chat-input-row">
          <input
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="Tulis pertanyaan… (Enter untuk kirim)"
            aria-label="Pesan chat"
            disabled={busy}
            maxLength={1000}
          />
          <button className="btn primary" onClick={() => send()} disabled={busy || !input.trim()}>
            Kirim
          </button>
        </div>
      </section>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { getMeta, ragQuery } from '../api.js'

const MODES = ['MRT', 'KRL', 'LRT', 'BRT']
const LABELS = ['aktual', 'historis', 'prediksi', 'proksi']
const EXAMPLES = [
  'tarif integrasi JAKLINGKO',
  'jumlah penumpang KRL 2025',
  'stasiun baru LRT Jakarta',
  'frekuensi perjalanan KRL',
]

const LABEL_STYLE = {
  aktual: { background: '#eef7f0', color: '#1a7f37' },
  historis: { background: '#eef4fd', color: '#0b6bcb' },
  prediksi: { background: '#fdf3e3', color: '#b26b00' },
  proksi: { background: '#f1f3f5', color: '#5c6672' },
}

export default function RagPage() {
  const [meta, setMeta] = useState(null)
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [mode, setMode] = useState('')
  const [label, setLabel] = useState('')
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { getMeta().then(setMeta).catch(() => {}) }, [])

  const run = async (q = query) => {
    if (q.trim().length < 2) return
    setBusy(true)
    setError(null)
    try {
      const r = await ragQuery({ query: q.trim(), top_k: topK, mode: mode || null, label: label || null })
      setResults(r)
    } catch (e) {
      setError(e.message)
      setResults(null)
    } finally {
      setBusy(false)
    }
  }

  const operators = meta ? [...new Set(meta.documents.map((d) => d.mode_id))] : []

  return (
    <div className="page">
      <section className="card">
        <h2>Tanya dokumen resmi (RAG)</h2>
        <p className="note">
          Retrieval atas korpus dokumen operator (KCI AR 2025, AR LRT Jakarta 2022) — hybrid
          vektor + teks, setiap hasil membawa sitasi halaman. Chunk diperlakukan sebagai data,
          bukan instruksi.
        </p>
        <div className="rag-row">
          <input
            className="rag-input"
            value={query}
            placeholder="cth: tarif integrasi JAKLINGKO, jumlah penumpang KRL 2025…"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && run()}
            aria-label="Pertanyaan dokumen"
          />
          <select className="mode-select" value={topK} onChange={(e) => setTopK(Number(e.target.value))} title="Jumlah hasil">
            {[3, 5, 8, 10].map((n) => <option key={n} value={n}>top {n}</option>)}
          </select>
          <select className="mode-select" value={mode} onChange={(e) => setMode(e.target.value)} title="Filter moda">
            <option value="">Semua moda</option>
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <select className="mode-select" value={label} onChange={(e) => setLabel(e.target.value)} title="Filter label data">
            <option value="">Semua label</option>
            {LABELS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          <button className="btn primary" disabled={busy || query.trim().length < 2} onClick={() => run()}>
            {busy ? 'Mencari…' : 'Tanya'}
          </button>
        </div>
        <div className="chips">
          {EXAMPLES.map((s) => (
            <button key={s} className="chip" onClick={() => { setQuery(s); run(s) }}>{s}</button>
          ))}
        </div>
        {error && <p className="error">Gagal: {error}</p>}
      </section>

      {results && results.count === 0 && (
        <section className="card">
          <p>Tidak ada hasil{mode ? ` untuk moda ${mode}` : ''}. Coba kata kunci lain atau hilangkan filter —
          korpus saat ini belum memuat dokumen MRT (menunggu AR MRT 2023/2024).</p>
        </section>
      )}

      {results && results.count > 0 && (
        <section className="rag-list">
          {results.results.map((r) => (
            <article key={r.chunk_id} className="card rag-card">
              <div className="rag-head">
                <span className="score">skor {r.score}</span>
                {r.citation.fresh_label && (
                  <span className="data-label" style={LABEL_STYLE[r.citation.fresh_label]}>
                    {r.citation.fresh_label}
                  </span>
                )}
                <span className="rag-doc">{r.citation.title}</span>
              </div>
              <p className="rag-section">
                {r.citation.section && <b>{r.citation.section}</b>}
                {r.citation.pages && r.citation.pages[0]
                  ? ` · hlm. ${r.citation.pages[0]}${r.citation.pages[1] && r.citation.pages[1] !== r.citation.pages[0] ? `–${r.citation.pages[1]}` : ''}`
                  : ''}
              </p>
              <p className="rag-text">{r.text}</p>
              <p className="rag-meta">
                {r.citation.source_id}
                {r.citation.published_at && ` · terbit ${r.citation.published_at}`}
                {r.citation.effective && r.citation.effective[0]
                  ? ` · efektif ${r.citation.effective[0]} s.d. ${r.citation.effective[1] || '…'}`
                  : ''}
                {r.citation.source_url
                  && <> · <a href={r.citation.source_url} target="_blank" rel="noopener">sumber asli ↗</a></>}
              </p>
            </article>
          ))}
        </section>
      )}
      {operators.length === 0 && null}
    </div>
  )
}

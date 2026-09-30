# -*- coding: utf-8 -*-
"""Fase 3 RAG — retrieval hybrid: semantik (cosine) + full-text (tsvector
indonesian + pg_trgm) + filter metadata, digabung dengan Reciprocal Rank
Fusion (RRF). Hasil selalu membawa citation (judul, bagian, halaman,
sumber, label freshness).

Merujuk context.md §10.4.

Jalankan:  .venv\\Scripts\\python pipelines\\rag_query.py "pertanyaan" [--top 5]
           [--mode MRT] [--operator KRL_COMMUTER] [--type annual_report]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RRF_K = 60  # konstanta standar RRF
FULLTEXT_CANDIDATES = 50
VECTOR_CANDIDATES = 50


class Embedder:
    """Singleton model embedding (model sama dengan ingest)."""

    _model = None

    @classmethod
    def get(cls):
        if cls._model is None:
            from fastembed import TextEmbedding
            cls._model = TextEmbedding(MODEL_NAME)
        return cls._model

    @classmethod
    def embed_one(cls, text: str) -> np.ndarray:
        return np.asarray(next(cls.get().embed([text])), dtype=np.float64)


def _load_chunks(cur) -> tuple[list[dict], np.ndarray]:
    """Muat seluruh chunk (skala MVP: ribuan chunk, full-scan aman)."""
    cur.execute("""
        SELECT c.chunk_id, c.document_id, c.seq, c.section_title,
               c.page_number, c.page_end, c.text, c.embedding,
               d.title, d.source_url, d.source_id, d.published_at,
               d.effective_from, d.effective_until, d.fresh_label,
               d.document_type, d.operator_id, d.mode_id
        FROM document_chunks c
        JOIN documents d ON d.document_id = c.document_id
        ORDER BY c.chunk_id
    """)
    rows = cur.fetchall()
    meta = []
    vecs = []
    for r in rows:
        meta.append(dict(zip(
            ["chunk_id", "document_id", "seq", "section_title", "page_number",
             "page_end", "text", "embedding", "title", "source_url", "source_id",
             "published_at", "effective_from", "effective_until", "fresh_label",
             "document_type", "operator_id", "mode_id"], r)))
        if r[7]:
            vecs.append(np.asarray(r[7], dtype=np.float64))
    mat = np.vstack(vecs) if vecs else np.empty((0, 0))
    return meta, mat


def _cosine_rank(qvec: np.ndarray, mat: np.ndarray, idx: list[int]) -> list[int]:
    if len(idx) == 0:
        return []
    m = mat[idx]
    qn = qvec / (np.linalg.norm(qvec) + 1e-12)
    mn = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-12)
    scores = mn @ qn
    order = np.argsort(-scores)
    return [idx[i] for i in order[:VECTOR_CANDIDATES]]


def _text_rank(conn, cur, query: str, where_sql: str, filter_params: tuple) -> list[str]:
    """Ranking full-text: ts_rank (indonesian, plainto_tsquery) + fallback pg_trgm.
    where_sql = ' WHERE ...' (sudah ber- WHERE) atau ' WHERE 1=1'.
    Return daftar chunk_id terurut."""
    # plainto_tsquery = robust utk teks bebas (angka/tahun, operator tsquery tak
    # memecahkan syntax). to_tsquery sengaja tidak dipakai (gagal pada digit).
    tsq = None
    try:
        cur.execute("SELECT plainto_tsquery('indonesian', %s)", (query,))
        row = cur.fetchone()
        if row and str(row[0]).strip("{}").strip():
            tsq = row[0]
    except Exception:
        conn.rollback()  # reset transaksi ter-kecualikan
        tsq = None

    ranked: dict[str, float] = {}
    from_join = (
        "FROM document_chunks c "
        "JOIN documents d ON d.document_id = c.document_id "
        + where_sql
    )
    if tsq is not None:
        sql = (
            "SELECT c.chunk_id, "
            "coalesce(ts_rank(c.tsv, %s), 0) + coalesce(similarity(c.text, %s), 0) * 2.0 AS sc "
            + from_join + " AND c.tsv @@ %s "
            "ORDER BY sc DESC LIMIT %s"
        )
        cur.execute(sql, (*filter_params, tsq, query, tsq, FULLTEXT_CANDIDATES))
    else:
        sql = (
            "SELECT c.chunk_id, similarity(c.text, %s) AS sc "
            + from_join + " AND similarity(c.text, %s) > 0 "
            "ORDER BY sc DESC LIMIT %s"
        )
        cur.execute(sql, (*filter_params, query, query, FULLTEXT_CANDIDATES))
    for chunk_id, sc in cur.fetchall():
        if sc and sc > 0:
            ranked[str(chunk_id)] = float(sc)
    return [k for k, _ in sorted(ranked.items(), key=lambda kv: -kv[1])]


def rrf_fuse(rankings: list[list[int | str]], k: int = RRF_K) -> dict:
    """Gabung beberapa ranking (1-based) menjadi skor RRF per dokumen."""
    scores: dict = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def rag_search(query: str, top_k: int = 5,
               operator: str | None = None, mode: str | None = None,
               doc_type: str | None = None, fresh_label: str | None = None,
               conn=None) -> list[dict]:
    """Retrieval hybrid + RRF. Return top_k hasil dengan citation."""
    own = conn is None
    conn = conn or connect()
    cur = conn.cursor()

    clauses, params = [], []
    if operator:
        clauses.append(" d.operator_id = %s"); params.append(operator)
    if mode:
        clauses.append(" d.mode_id = %s"); params.append(mode)
    if doc_type:
        clauses.append(" d.document_type = %s"); params.append(doc_type)
    if fresh_label:
        clauses.append(" d.fresh_label = %s"); params.append(fresh_label)
    filter_sql = (" AND ".join(clauses) + " AND") if clauses else ""
    # filter_sql dipakai di _text_rank sebagai "... AND " — susun ulang rapi
    filter_for_text = " WHERE " + (" AND ".join(clauses)) if clauses else " WHERE 1=1"

    meta, mat = _load_chunks(cur)
    idx = list(range(len(meta)))
    if clauses:
        # filter sisi Python utk kanal vektor (skala MVP)
        keep = []
        for i, m in enumerate(meta):
            if operator and m["operator_id"] != operator:
                continue
            if mode and m["mode_id"] != mode:
                continue
            if doc_type and m["document_type"] != doc_type:
                continue
            if fresh_label and m["fresh_label"] != fresh_label:
                continue
            keep.append(i)
        idx = keep

    qvec = Embedder.embed_one(query)
    vec_rank_idx = _cosine_rank(qvec, mat, idx)
    vec_rank = [meta[i]["chunk_id"] for i in vec_rank_idx]
    text_rank = _text_rank(conn, cur, query, filter_for_text, tuple(params))

    scores = rrf_fuse([vec_rank, text_rank])
    top = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]

    by_id = {m["chunk_id"]: m for m in meta}
    results = []
    for chunk_id, score in top:
        m = by_id[chunk_id]
        results.append(dict(
            score=round(score, 6),
            chunk_id=m["chunk_id"],
            document_id=m["document_id"],
            citation=dict(
                title=m["title"],
                section=m["section_title"],
                pages=(m["page_number"], m["page_end"]),
                source_url=m["source_url"],
                source_id=m["source_id"],
                published_at=str(m["published_at"]) if m["published_at"] else None,
                effective=(str(m["effective_from"]) if m["effective_from"] else None,
                           str(m["effective_until"]) if m["effective_until"] else None),
                fresh_label=m["fresh_label"],
                document_type=m["document_type"],
            ),
            text=m["text"][:1200],
        ))
    if own:
        conn.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--operator")
    ap.add_argument("--mode")
    ap.add_argument("--type", dest="doc_type")
    ap.add_argument("--label")
    args = ap.parse_args()

    results = rag_search(args.query, top_k=args.top, operator=args.operator,
                         mode=args.mode, doc_type=args.doc_type,
                         fresh_label=args.label)
    if not results:
        print("Tidak ada hasil.")
        return
    for i, r in enumerate(results, 1):
        c = r["citation"]
        pages = f"hlm {c['pages'][0]}" + (f"–{c['pages'][1]}"
                                          if c["pages"][1] and c["pages"][1] != c["pages"][0] else "")
        print(f"--- [{i}] {r['document_id']}  (RRF={r['score']:.5f})")
        print(f"    {c['title']} — {c['section'] or '(tanpa judul bagian)'} — {pages}")
        print(f"    sumber: {c['source_url']}  [{c['fresh_label']}, "
              f"valid {c['effective'][0]} s.d. {c['effective'][1]}]")
        print("    " + " ".join(r["text"].split())[:400])
        print()


if __name__ == "__main__":
    main()

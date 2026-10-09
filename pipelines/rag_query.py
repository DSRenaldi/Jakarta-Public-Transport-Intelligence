# -*- coding: utf-8 -*-
"""Retrieval RAG hybrid yang aman untuk korpus JPTI.

Kanal semantik (cosine) dan full-text/trigram digabung dengan RRF, lalu setiap
kandidat melewati pagar relevansi. Retriever dapat abstain ketika korpus tidak
memiliki cakupan atau ketika passage yang ditemukan tidak cukup mendukung.
"""
import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RETRIEVER_VERSION = "rag-v2"
RRF_K = 60
FULLTEXT_CANDIDATES = 50
VECTOR_CANDIDATES = 50
MAX_TOP_K = 10

# Ambang awal dikalibrasi pada korpus aktif. Filter operator adalah pagar utama;
# embedding saja tidak boleh membuat dokumen moda lain terlihat relevan.
MIN_VECTOR_SCORE = 0.38
MIN_STRONG_VECTOR_SCORE = 0.68
MIN_QUERY_COVERAGE = 0.34
MIN_RELEVANCE_SCORE = 0.45

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "apa", "apakah", "bagaimana", "berapa", "kapan", "siapa", "mengapa",
    "yang", "dan", "atau", "dari", "untuk", "pada", "dalam", "dengan",
    "tentang", "adalah", "itu", "ini", "di", "ke", "sebuah", "saja", "tolong",
    "jelaskan", "mengenai", "tahun", "saat", "sekarang", "terbaru",
    "mrt", "lrt", "krl", "brt", "kai", "commuter", "line", "jakarta",
    "jabodebek", "jabodetabek", "transjakarta", "pt",
}

_INDEX_LOCK = threading.Lock()
_INDEX_CACHE: dict = {
    "signature": None,
    "loaded_at": 0.0,
    "meta": [],
    "mat": np.empty((0, 0)),
}
INDEX_CACHE_TTL_SEC = 300


class Embedder:
    """Singleton model embedding yang sama dengan pipeline ingest."""

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


def infer_query_filters(query: str) -> dict:
    """Turunkan scope konservatif dari penyebutan eksplisit pengguna."""
    q = query.casefold()
    operator = None
    mode = None
    if "lrt jabodebek" in q or "jabodebek" in q:
        operator, mode = "LRT_JABODEBEK", "LRT"
    elif "lrt jakarta" in q:
        operator, mode = "LRT_JAKARTA", "LRT"
    elif re.search(r"\bmrt\b", q) or "mass rapid transit" in q:
        operator, mode = "MRT_JAKARTA", "MRT"
    elif re.search(r"\b(?:krl|kci)\b", q) or "kai commuter" in q \
            or "commuter line" in q:
        operator, mode = "KRL_COMMUTER", "KRL"
    elif "transjakarta" in q or "trans jakarta" in q \
            or "busway" in q or re.search(r"\bbrt\b", q):
        operator, mode = "TRANSJAKARTA", "BRT"

    doc_type = None
    if "laporan tahunan" in q or "annual report" in q:
        doc_type = "annual_report"
    elif "laporan keberlanjutan" in q or "sustainability report" in q:
        doc_type = "sustainability_report"
    elif any(v in q for v in ("kebijakan", "peraturan", "ketentuan")):
        doc_type = "policy"
    elif any(v in q for v in ("barang bawaan", "panduan penumpang",
                              "aksesibilitas", "fasilitas stasiun")):
        doc_type = "guide"
    elif any(v in q for v in ("siaran pers", "pengumuman layanan",
                              "perubahan layanan", "status layanan")):
        doc_type = "press_release"
    return {"operator": operator, "mode": mode, "doc_type": doc_type}


def _corpus_signature(cur) -> tuple:
    cur.execute("""
        SELECT (SELECT count(*) FROM document_chunks),
               (SELECT coalesce(max(created_at)::text, '')
                  FROM document_chunks),
               (SELECT coalesce(string_agg(document_id || ':' ||
                                           checksum_sha256,
                                           '|' ORDER BY document_id), '')
                  FROM documents)
    """)
    return tuple(cur.fetchone())


def _load_chunks_uncached(cur) -> tuple[list[dict], np.ndarray]:
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
    fields = [
        "chunk_id", "document_id", "seq", "section_title", "page_number",
        "page_end", "text", "embedding", "title", "source_url",
        "source_id", "published_at", "effective_from", "effective_until",
        "fresh_label", "document_type", "operator_id", "mode_id",
    ]
    meta, vecs = [], []
    for row in cur.fetchall():
        if not row[7]:
            continue
        meta.append(dict(zip(fields, row)))
        vecs.append(np.asarray(row[7], dtype=np.float64))
    mat = np.vstack(vecs) if vecs else np.empty((0, 0))
    return meta, mat


def _load_chunks(cur) -> tuple[list[dict], np.ndarray]:
    """Cache indeks proses; fingerprint membuat ingest baru terlihat otomatis."""
    signature = _corpus_signature(cur)
    now = time.monotonic()
    with _INDEX_LOCK:
        if (_INDEX_CACHE["signature"] == signature
                and now - _INDEX_CACHE["loaded_at"] < INDEX_CACHE_TTL_SEC):
            return _INDEX_CACHE["meta"], _INDEX_CACHE["mat"]
        meta, mat = _load_chunks_uncached(cur)
        _INDEX_CACHE.update(signature=signature, loaded_at=now,
                            meta=meta, mat=mat)
        return meta, mat


def _cosine_rank(qvec: np.ndarray, mat: np.ndarray,
                 idx: list[int]) -> list[tuple[int, float]]:
    if not idx or mat.size == 0:
        return []
    selected = mat[idx]
    qn = qvec / (np.linalg.norm(qvec) + 1e-12)
    mn = selected / (np.linalg.norm(selected, axis=1, keepdims=True) + 1e-12)
    scores = mn @ qn
    order = np.argsort(-scores)
    return [(idx[i], float(scores[i])) for i in order[:VECTOR_CANDIDATES]]


def _text_rank(conn, cur, query: str, where_sql: str,
               filter_params: tuple) -> list[tuple[str, float]]:
    """Full-text dengan metadata dokumen serta fallback trigram."""
    try:
        cur.execute("SELECT plainto_tsquery('indonesian', %s)", (query,))
        row = cur.fetchone()
        tsq = row[0] if row and str(row[0]).strip("{}").strip() else None
    except Exception:
        conn.rollback()
        tsq = None

    from_join = (
        "FROM document_chunks c "
        "JOIN documents d ON d.document_id = c.document_id " + where_sql
    )
    if tsq is not None:
        searchable = (
            "(c.tsv || to_tsvector('indonesian', coalesce(d.title,'') || "
            "' ' || coalesce(d.document_id,'') || ' ' || "
            "coalesce(d.source_id,'') || ' ' || "
            "coalesce(d.operator_id,'') || ' ' || coalesce(d.mode_id,'')))"
        )
        sql = (
            "SELECT c.chunk_id, coalesce(ts_rank(" + searchable + ", %s), 0) "
            "+ coalesce(similarity(c.text, %s), 0) * 2.0 AS sc "
            + from_join + " AND " + searchable + " @@ %s "
            "ORDER BY sc DESC LIMIT %s"
        )
        cur.execute(sql, (tsq, query, *filter_params, tsq,
                          FULLTEXT_CANDIDATES))
    else:
        sql = (
            "SELECT c.chunk_id, similarity(c.text, %s) AS sc "
            + from_join + " AND similarity(c.text, %s) > 0 "
            "ORDER BY sc DESC LIMIT %s"
        )
        cur.execute(sql, (query, *filter_params, query,
                          FULLTEXT_CANDIDATES))
    return [(str(chunk_id), float(score)) for chunk_id, score in cur.fetchall()
            if score and score > 0]


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def _query_terms(query: str) -> list[str]:
    return list(dict.fromkeys(
        token.casefold() for token in _TOKEN_RE.findall(query)
        if len(token) >= 3 and token.casefold() not in _STOPWORDS
    ))


def _coverage(query: str, meta: dict) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    hay = " ".join([meta.get("title") or "",
                    meta.get("section_title") or "",
                    meta.get("text") or ""]).casefold()
    return sum(1 for term in terms if term in hay) / len(terms)


def _phrase_coverage(query: str, meta: dict) -> float:
    terms = [term for term in _query_terms(query) if not term.isdigit()]
    phrases = [f"{left} {right}" for left, right in zip(terms, terms[1:])]
    if not phrases:
        return 0.0
    hay = " ".join([meta.get("title") or "",
                    meta.get("section_title") or "",
                    meta.get("text") or ""]).casefold()
    return sum(1 for phrase in phrases if phrase in hay) / len(phrases)


def _year_compatible(query: str, meta: dict) -> bool:
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", query))
    if not years:
        return True
    hay = " ".join([meta.get("title") or "", meta.get("text") or ""])
    return bool(years & set(re.findall(r"\b(?:19|20)\d{2}\b", hay)))


def _candidate_is_relevant(vector_score: float, coverage: float,
                           lexical_hit: bool, relevance: float,
                           year_ok: bool) -> bool:
    if not year_ok or vector_score < MIN_VECTOR_SCORE:
        return False
    if not (lexical_hit or coverage >= MIN_QUERY_COVERAGE) \
            and vector_score < MIN_STRONG_VECTOR_SCORE:
        return False
    return relevance >= MIN_RELEVANCE_SCORE


def rag_retrieve(query: str, top_k: int = 5,
                 operator: str | None = None, mode: str | None = None,
                 doc_type: str | None = None,
                 fresh_label: str | None = None,
                 conn=None, infer_filters: bool = True) -> dict:
    """Cari passage dan kembalikan status ``ok`` atau alasan abstain."""
    query = (query or "").strip()
    if len(query) < 2:
        return {"status": "invalid_query", "results": [], "filters": {},
                "retriever_version": RETRIEVER_VERSION}
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    inferred = infer_query_filters(query) if infer_filters else {}
    operator = operator or inferred.get("operator")
    mode = mode or inferred.get("mode")
    doc_type = doc_type or inferred.get("doc_type")

    own = conn is None
    conn = conn or connect()
    cur = conn.cursor()
    clauses, params = [], []
    for column, value in (("operator_id", operator), ("mode_id", mode),
                          ("document_type", doc_type),
                          ("fresh_label", fresh_label)):
        if value:
            clauses.append(f" d.{column} = %s")
            params.append(value)
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else " WHERE 1=1"

    meta, mat = _load_chunks(cur)
    idx = []
    for i, item in enumerate(meta):
        if operator and item["operator_id"] != operator:
            continue
        if mode and item["mode_id"] != mode:
            continue
        if doc_type and item["document_type"] != doc_type:
            continue
        if fresh_label and item["fresh_label"] != fresh_label:
            continue
        idx.append(i)

    filters = {key: value for key, value in {
        "operator": operator, "mode": mode, "doc_type": doc_type,
        "fresh_label": fresh_label,
    }.items() if value}
    if not idx:
        if own:
            conn.close()
        return {"status": "no_coverage", "results": [], "filters": filters,
                "retriever_version": RETRIEVER_VERSION,
                "note": "Korpus belum memiliki dokumen untuk scope pertanyaan."}

    qvec = Embedder.embed_one(query)
    vec_pairs = _cosine_rank(qvec, mat, idx)
    vec_rank = [meta[i]["chunk_id"] for i, _ in vec_pairs]
    vector_scores = {meta[i]["chunk_id"]: score for i, score in vec_pairs}
    lexical_query = " ".join(_query_terms(query)) or query
    text_pairs = _text_rank(conn, cur, lexical_query, where_sql, tuple(params))
    text_rank = [chunk_id for chunk_id, _ in text_pairs]
    text_scores = dict(text_pairs)
    max_text_score = max(text_scores.values(), default=1.0)
    # Kandidat leksikal yang tidak masuk top-N vektor tetap membutuhkan skor
    # cosine untuk pagar relevansi. Tanpa ini, exact passage dapat terbuang
    # hanya karena embedding lebih menyukai passage yang lebih umum.
    index_by_id = {item["chunk_id"]: i for i, item in enumerate(meta)}
    qnorm = np.linalg.norm(qvec) + 1e-12
    for chunk_id in text_rank:
        if chunk_id in vector_scores:
            continue
        vector = mat[index_by_id[chunk_id]]
        vector_scores[chunk_id] = float(
            vector @ qvec / ((np.linalg.norm(vector) + 1e-12) * qnorm)
        )
    rrf_scores = rrf_fuse([vec_rank, text_rank])
    by_id = {item["chunk_id"]: item for item in meta}

    candidates = []
    for chunk_id, rrf_score in rrf_scores.items():
        item = by_id[chunk_id]
        vector_score = vector_scores.get(chunk_id, 0.0)
        coverage = _coverage(query, item)
        lexical_hit = chunk_id in text_scores
        lexical_score = text_scores.get(chunk_id, 0.0) / max_text_score
        phrase_coverage = _phrase_coverage(query, item)
        relevance = (0.55 * max(0.0, vector_score)
                     + 0.15 * coverage
                     + 0.15 * lexical_score
                     + 0.15 * phrase_coverage)
        if _candidate_is_relevant(vector_score, coverage, lexical_hit,
                                  relevance, _year_compatible(query, item)):
            candidates.append((chunk_id, relevance, rrf_score, vector_score,
                               coverage, lexical_hit, lexical_score,
                               phrase_coverage))
    candidates.sort(key=lambda value: (-value[1], -value[2], -value[3]))

    results = []
    for (chunk_id, relevance, rrf_score, vector_score, coverage,
         lexical_hit, lexical_score, phrase_coverage) in candidates[:top_k]:
        item = by_id[chunk_id]
        results.append({
            "score": round(relevance, 4),
            "retrieval": {
                "vector_score": round(vector_score, 4),
                "query_coverage": round(coverage, 4),
                "phrase_coverage": round(phrase_coverage, 4),
                "lexical_hit": lexical_hit,
                "lexical_score": round(lexical_score, 4),
                "rrf_score": round(rrf_score, 6),
                "version": RETRIEVER_VERSION,
            },
            "chunk_id": item["chunk_id"],
            "document_id": item["document_id"],
            "citation": {
                "title": item["title"], "section": item["section_title"],
                "pages": (item["page_number"], item["page_end"]),
                "source_url": item["source_url"],
                "source_id": item["source_id"],
                "published_at": (str(item["published_at"])
                                 if item["published_at"] else None),
                "effective": (
                    str(item["effective_from"])
                    if item["effective_from"] else None,
                    str(item["effective_until"])
                    if item["effective_until"] else None,
                ),
                "fresh_label": item["fresh_label"],
                "document_type": item["document_type"],
            },
            "text": item["text"][:1200],
        })
    if own:
        conn.close()
    return {
        "status": "ok" if results else "no_relevant_result",
        "results": results,
        "filters": filters,
        "retriever_version": RETRIEVER_VERSION,
        "note": (None if results else
                 "Tidak ada potongan dokumen yang cukup relevan untuk dijawab."),
    }


def rag_search(query: str, top_k: int = 5,
               operator: str | None = None, mode: str | None = None,
               doc_type: str | None = None, fresh_label: str | None = None,
               conn=None) -> list[dict]:
    """API kompatibel: kembalikan daftar passage yang lolos pagar relevansi."""
    return rag_retrieve(
        query, top_k=top_k, operator=operator, mode=mode,
        doc_type=doc_type, fresh_label=fresh_label, conn=conn,
    )["results"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--operator")
    parser.add_argument("--mode")
    parser.add_argument("--type", dest="doc_type")
    parser.add_argument("--label")
    args = parser.parse_args()
    payload = rag_retrieve(
        args.query, top_k=args.top, operator=args.operator, mode=args.mode,
        doc_type=args.doc_type, fresh_label=args.label,
    )
    if not payload["results"]:
        print(f"Tidak ada hasil ({payload['status']}): {payload.get('note')}")
        print("Filter:", json.dumps(payload["filters"], ensure_ascii=False))
        return
    for index, result in enumerate(payload["results"], start=1):
        citation = result["citation"]
        pages = f"hlm {citation['pages'][0]}"
        if citation["pages"][1] != citation["pages"][0]:
            pages += f"–{citation['pages'][1]}"
        print(f"--- [{index}] {result['document_id']} "
              f"(relevansi={result['score']:.3f})")
        print(f"    {citation['title']} — {citation['section'] or '-'} — {pages}")
        print(f"    sumber: {citation['source_url']} [{citation['fresh_label']}]")
        print("    " + " ".join(result["text"].split())[:400])
        print()


if __name__ == "__main__":
    main()

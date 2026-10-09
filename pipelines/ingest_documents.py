# -*- coding: utf-8 -*-
"""Fase 3 RAG — ingest dokumen: PDF → chunk semantik → embedding → Postgres.

Merujuk context.md §10.2 (pipeline) & §10.3 (metadata minimum).

Langkah:
  1. checksum SHA-256 salinan mentah
  2. ekstrak teks per halaman (pypdf)
  3. bersihkan header/footer berulang + nomor halaman
  4. chunking semantik (judul bagian + paragraf, batas karakter)
  5. metadata §10.3 (bahasa terdeteksi otomatis)
  6. embedding fastembed (paraphrase-multilingual-MiniLM-L12-v2, 384 dim)
  7. simpan documents + document_chunks (migration 0005) + ingest_runs

Idempoten: dokumen dengan checksum sama dilewati; checksum berbeda → diganti.

Jalankan:  .venv\\Scripts\\python pipelines\\ingest_documents.py [--only DOC_ID]
"""
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
PIPELINE_VERSION = "rag-ingest-v2"
MAX_CHUNK_CHARS = 1800          # ~450 token
CHUNK_OVERLAP_CHARS = 220       # konteks pada batas chunk
MIN_DOC_CHARS = 5000            # di bawah ini = PDF kemungkinan tanpa text layer
PARA_SOFT_LIMIT = 1200          # batas paragraf saat PDF tanpa baris kosong

RE_PAGE_NUM = re.compile(r"^\s*(?:-?\s*)\d{1,4}\s*(?:-?\s*)$")
RE_NUM_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s+([A-ZÁÉÍÓÚa-z]{2,80})$")
RE_CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9 &\-–/]{2,58}$")

HEADING_HINTS = {
    "laporan", "report", "ikhtisar", "highlight", "profil", "profile",
    "kinerja", "performance", "operasi", "operation", "layanan", "service",
    "keuangan", "financial", "tata kelola", "governance", "risiko", "risk",
    "keselamatan", "safety", "keberlanjutan", "sustainability", "segmen",
    "segment", "pendahuluan", "introduction", "manajemen", "management",
    "sarana", "prasarana", "infrastruktur", "infrastructure",
}

ID_WORDS = {"yang", "dan", "adalah", "pada", "untuk", "dengan", "dari", "dalam",
            "ini", "itu", "kami", "perusahaan", "tersebut", "dapat", "juga", "bahwa"}
EN_WORDS = {"the", "and", "is", "of", "to", "in", "we", "our", "company", "are",
            "was", "for", "this", "that", "with", "as", "it", "be", "by"}

# ---------- korpus standar (dokumen AR yang tersedia & utuh) ----------

# =====================================================================
# A6 (30 Sep 2026) — koreksi artefak glyph ekstraksi PDF, SPESIFIK DOKUMEN.
#
# LRTJ-AR-2022 diekstrak dengan font CFF (DiariaSansPro) yang ToUnicode
# CMap-nya rusak: glyph huruf "s" dipetakan ke ANGKA (1, 2, 3, 4, 9 —
# beda font beda angka; bukti: kata "perusahaan" muncul sebagai
# peru1ahaan/peru2ahaan/peru3ahaan/peru4ahaan/peru9ahaan). Scan penuh
# 1.202 chunk (30 Sep 2026): 222 token unik ber-digit-dalam-kata, SEMUA
# artefak "s"; satu-satunya pengecualian legit = akronim P4GN.
# Koreksi: ganti digit di dalam token (huruf di kedua sisi) dengan "s",
# token di-whitelist dipertahankan. Dibatasi utk LRTJ-AR-2022 (KCI-AR-2025
# bersih; dokumen masa depan mungkin punya digit tengah kata yang sah).
#
# SISA (disengaja TIDAK diperbaiki — berisiko merusak data sah):
#   * digit AKHIR kata: campuran artefak ("Shareholder1"=Shareholders,
#     "Tuga1"=Tugas) dgn token sah ("Rp1", "IDR4", "K3", "SMK3", "B3",
#     "S1", "S2", "Covid19") — bentuk token identik, tak bisa dipisah
#     tanpa whitelist rapuh; mengorbankan angka keuangan = tak layak.
#   * digit AWAL kata: campuran artefak ("3ecara"=Secara, "9ebelumnya")
#     dgn pemisah-hilang ("6Tata"=6. Tata) & ordinal/angka sah ("1st",
#     "8km", "50jt").
#   * Verifikasi 30 Sep 2026: eval retrieval tetap 100% (10/10, MRR 1.0)
#     — sisa artefak tidak memblok retrieval, hanya noise ejaan ringan.
# =====================================================================
RE_GLYPH_TOKEN = re.compile(r"\b[A-Za-z]+[0-9]+[A-Za-z]+\b")
GLYPH_PROTECT = {"P4GN"}  # akronim sah (hasil scan 30 Sep 2026)


def fix_glyph_s2digit(text: str) -> str:
    """Pulihkan glyph 's' yang terekstrak sebagai digit (LRTJ-AR-2022)."""
    def _fix(m):
        tok = m.group(0)
        return tok if tok in GLYPH_PROTECT else re.sub(r"[0-9]", "s", tok)
    return RE_GLYPH_TOKEN.sub(_fix, text)


CORPUS = [
    dict(
        document_id="KCI-AR-2025",
        rel_path="data/raw/krl/annual_report_2025.pdf",
        operator_id="KRL_COMMUTER", mode_id="KRL",
        document_type="annual_report",
        title="Annual Report KAI Commuter 2025",
        source_url="https://www.kci.id/files/download/annual_report/Annual%20Report%202025.pdf",
        source_id="SRC-KRL-02",
        published_at=None,                       # tanggal rilis AR belum terverifikasi
        effective_from=date(2025, 1, 1), effective_until=date(2025, 12, 31),
        data_version="AR2025", fresh_label="historis",
        extra={"coverage_period": "FY2025"},
    ),
    dict(
        document_id="LRTJ-AR-2022",
        rel_path="data/raw/lrt_jakarta/annual_report_2022.pdf",
        operator_id="LRT_JAKARTA", mode_id="LRT",
        document_type="annual_report",
        title="Annual Report PT LRT Jakarta 2022",
        source_url="https://appcdn2.lrtjakarta.co.id/storage/2024/2/annual_2022.pdf",
        source_id="SRC-LRTJ-04",
        published_at=None,
        effective_from=date(2022, 1, 1), effective_until=date(2022, 12, 31),
        data_version="AR2022", fresh_label="historis",
        extra={"coverage_period": "FY2022"},
        text_fixes=fix_glyph_s2digit,   # A6: artefak glyph s->digit (lihat di atas)
    ),
]

SOURCES = {
    "SRC-KRL-02": ("Annual Report KAI Commuter 2015-2025",
                   "https://www.kci.id/informasi-publik/laporan-tahunan",
                   "pdf_extract", "live"),
    "SRC-LRTJ-04": ("Laporan Tahunan (AR) LRT Jakarta 2018-2022",
                    "https://www.lrtjakarta.co.id/annual_report",
                    "pdf_extract", "live"),
}


# ---------- 1. ekstrak & bersihkan ----------

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for ch in iter(lambda: fh.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def extract_pages(path: Path) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return [(pg.extract_text() or "") for pg in reader.pages]


def norm_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def clean_pages(pages: list[str]) -> list[str]:
    """Hapus header/footer berulang & nomor halaman (heuristik frekuensi)."""
    n = len(pages)
    counts: dict[str, int] = {}
    lines_per_page: list[list[str]] = []
    for txt in pages:
        lines = [norm_line(l) for l in txt.splitlines()]
        lines_per_page.append(lines)
        for l in lines[:3] + lines[-3:]:
            if 3 <= len(l) <= 60:
                counts[l] = counts.get(l, 0) + 1
    headerish = {l for l, c in counts.items() if c >= max(3, n * 0.3)}

    out = []
    for lines in lines_per_page:
        keep = []
        for i, l in enumerate(lines):
            if RE_PAGE_NUM.match(l):
                continue
            if l in headerish and (i < 3 or i >= len(lines) - 3):
                continue
            keep.append(l)
        out.append("\n".join(keep))
    return out


def detect_language(sample: str) -> str:
    words = {w for w in re.findall(r"[a-z]+", sample.lower()) if len(w) > 2}
    id_hits = len(words & ID_WORDS)
    en_hits = len(words & EN_WORDS)
    return "id" if id_hits >= en_hits else "en"


# ---------- 2. chunking semantik ----------

def is_heading(line: str) -> bool:
    l = line.strip()
    if not l or len(l) > 80 or l.endswith((".", ",", ":", ";")):
        return False
    if RE_CAPS_HEADING.match(l):
        lowered = l.casefold()
        return (not any(ch.isdigit() for ch in l)
                and any(hint in lowered for hint in HEADING_HINTS))
    m = RE_NUM_HEADING.match(l)
    return bool(m) and len(l) <= 80


def split_paragraphs(text: str) -> list[tuple[str, int]]:
    """Pisahkan paragraf dari teks halaman.
    Return: daftar (paragraf, nomor_halaman) — halaman 1-based dilewatkan pemanggil.
    PDF pypdf sering tanpa baris kosong; jatuh pada batas karakter."""
    paras: list[str] = []
    buf = ""
    for raw in text.splitlines():
        l = norm_line(raw)
        if not l:
            if buf:
                paras.append(buf)
                buf = ""
            continue
        if is_heading(l):
            if buf:
                paras.append(buf)
                buf = ""
            paras.append(f"@@HEADING@@ {l}")
            continue
        if buf and len(buf) + len(l) > PARA_SOFT_LIMIT:
            paras.append(buf)
            buf = l
        else:
            buf = (buf + " " + l) if buf else l
    if buf:
        paras.append(buf)
    return [p for p in paras if p.strip()]


def chunk_document(pages: list[str]) -> list[dict]:
    """Gabung paragraf per bagian semantik jadi chunk (batas MAX_CHUNK_CHARS)."""
    chunks: list[dict] = []
    section = ""
    buf_text = ""
    buf_pages: list[int] = []

    def flush(keep_overlap: bool = False):
        nonlocal buf_text, buf_pages
        t = buf_text.strip()
        if t:
            chunks.append(dict(section_title=section, text=t,
                               page_number=buf_pages[0], page_end=buf_pages[-1]))
        if keep_overlap and t:
            tail = t[-CHUNK_OVERLAP_CHARS:]
            first_space = tail.find(" ")
            if first_space >= 0:
                tail = tail[first_space + 1:]
            buf_text = tail.strip()
            buf_pages = [buf_pages[-1]] if buf_pages else []
        else:
            buf_text, buf_pages = "", []

    for pno, page in enumerate(pages, start=1):
        for para in split_paragraphs(page):
            if para.startswith("@@HEADING@@ "):
                flush(keep_overlap=False)
                section = para[len("@@HEADING@@ "):].strip()
                continue
            if len(buf_text) + len(para) + 1 > MAX_CHUNK_CHARS:
                flush(keep_overlap=True)
            buf_text = (buf_text + "\n" + para) if buf_text else para
            buf_pages.append(pno)
    flush(keep_overlap=False)

    result = []
    for i, c in enumerate(chunks):
        result.append(dict(
            chunk_id=f"DOC::{i:04d}",   # diakhiri pemanggil (ganti prefix DOC)
            seq=i,
            section_title=(c["section_title"] or None),
            page_number=c["page_number"],
            page_end=c["page_end"],
            text=c["text"],
            token_count=max(1, len(c["text"]) // 4),
        ))
    return result


# ---------- 3. simpan ----------

def upsert_sources(cur) -> None:
    for sid, (name, url, method, status) in SOURCES.items():
        cur.execute("""
            INSERT INTO data_sources(source_id, name, url, access_method, status, verified_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO NOTHING
        """, (sid, name, url, method, status, date.today()))


def existing_checksum(cur, doc_id: str) -> str | None:
    cur.execute("SELECT checksum_sha256 FROM documents WHERE document_id = %s", (doc_id,))
    row = cur.fetchone()
    return row[0] if row else None


def save_document(conn, cur, doc: dict, path: Path, checksum: str,
                  language: str, page_count: int, chunks: list[dict]) -> None:
    model_dim = None
    extra = {
        **doc.get("extra", {}),
        "ingest_pipeline_version": PIPELINE_VERSION,
        "embedding_model": MODEL_NAME,
        "max_chunk_chars": MAX_CHUNK_CHARS,
        "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
    }
    cur.execute("""
        INSERT INTO documents(
            document_id, operator_id, mode_id, document_type, title, source_url,
            source_id, published_at, effective_from, effective_until, retrieved_at,
            data_version, language, fresh_label, file_path, checksum_sha256,
            file_size_bytes, page_count, extra, notes
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (document_id) DO UPDATE SET
            operator_id = EXCLUDED.operator_id,
            mode_id = EXCLUDED.mode_id,
            document_type = EXCLUDED.document_type,
            title = EXCLUDED.title,
            source_url = EXCLUDED.source_url,
            source_id = EXCLUDED.source_id,
            published_at = EXCLUDED.published_at,
            effective_from = EXCLUDED.effective_from,
            effective_until = EXCLUDED.effective_until,
            data_version = EXCLUDED.data_version,
            language = EXCLUDED.language,
            fresh_label = EXCLUDED.fresh_label,
            file_path = EXCLUDED.file_path,
            checksum_sha256 = EXCLUDED.checksum_sha256,
            page_count = EXCLUDED.page_count,
            file_size_bytes = EXCLUDED.file_size_bytes,
            retrieved_at = now(),
            extra = EXCLUDED.extra
    """, (
        doc["document_id"], doc["operator_id"], doc["mode_id"], doc["document_type"],
        doc["title"], doc["source_url"], doc["source_id"], doc["published_at"],
        doc["effective_from"], doc["effective_until"], doc["data_version"],
        language, doc["fresh_label"], doc["rel_path"], checksum,
        path.stat().st_size, page_count, json.dumps(extra, ensure_ascii=False),
        None,
    ))
    cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc["document_id"],))

    rows = []
    for c in chunks:
        vec = c["embedding"]
        model_dim = len(vec)
        # list Python langsung → psycopg3 adaptasi ke array (binary protocol).
        # CATATAN: literal string utk float8[] wajib kurung kurawal '{...}'
        # (kurung siku '[...]' hanya untuk dimensi; itu sintaks pgvector).
        rows.append((f"{doc['document_id']}::{c['seq']:04d}", doc["document_id"],
                     c["seq"], c["section_title"], c["page_number"], c["page_end"],
                     c["text"], c["token_count"], vec))
    BATCH = 500
    for i in range(0, len(rows), BATCH):
        cur.executemany("""
            INSERT INTO document_chunks(
                chunk_id, document_id, seq, section_title, page_number, page_end,
                text, token_count, embedding
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows[i:i + BATCH])

    cur.execute("""
        INSERT INTO ingest_runs(pipeline, rows_affected, notes)
        VALUES ('ingest_documents', %s, %s)
    """, (len(rows), f"{doc['document_id']} language={language} "
                     f"pages={page_count} dim={model_dim} sha256={checksum[:12]}..."))
    conn.commit()


def ingest_one(doc: dict, force: bool = False) -> bool:
    path = ROOT / doc["rel_path"]
    if not path.exists():
        print(f"[{doc['document_id']}] FILE TIDAK ADA: {path}")
        return False
    checksum = sha256(path)
    print(f"[{doc['document_id']}] {path.name} ({path.stat().st_size/1e6:.1f} MB) sha256={checksum[:12]}...")

    conn = connect()
    cur = conn.cursor()
    upsert_sources(cur)
    conn.commit()  # sumber harus bertahan walau proses berlanjut lama
    prev = existing_checksum(cur, doc["document_id"])
    if prev == checksum and not force:
        cur.execute("SELECT count(*) FROM document_chunks WHERE document_id=%s",
                    (doc["document_id"],))
        n = cur.fetchone()[0]
        conn.close()
        print(f"[{doc['document_id']}] checksum sama (sudah di-ingest, {n} chunk) — lewati")
        return True
    if force and prev == checksum:
        print(f"[{doc['document_id']}] --force: checksum sama, proses ulang (pipeline berubah)")
    if prev and prev != checksum:
        print(f"[{doc['document_id']}] checksum BERUBAH ({prev[:12]}... → {checksum[:12]}...) — ganti")
    conn.close()  # sumber sudah commit; koneksi baru dibuka lagi saat save

    print(f"[{doc['document_id']}] ekstrak teks...")
    t0 = time.time()
    pages = extract_pages(path)
    pages = clean_pages(pages)
    fix = doc.get("text_fixes")
    if fix:
        pages = [fix(p) for p in pages]
    total_chars = sum(len(p) for p in pages)
    print(f"[{doc['document_id']}] {len(pages)} halaman, {total_chars:,} karakter "
          f"({time.time()-t0:.0f}s)")
    if total_chars < MIN_DOC_CHARS:
        print(f"[{doc['document_id']}] GAGAL: teks terlalu sedikit — "
              f"PDF kemungkinan tanpa text layer (butuh OCR). TIDAK di-ingest.")
        return False

    lang = detect_language(" ".join(pages[:8])[:6000])
    print(f"[{doc['document_id']}] chunking semantik...")
    t0 = time.time()
    chunks = chunk_document(pages)
    print(f"[{doc['document_id']}] {len(chunks)} chunk ({time.time()-t0:.0f}s), bahasa={lang}")

    print(f"[{doc['document_id']}] embedding ({MODEL_NAME})...")
    from fastembed import TextEmbedding
    model = TextEmbedding(MODEL_NAME)
    prefix = f"{doc['title']}\n{doc['operator_id']} {doc['mode_id']}\n"
    texts = [prefix
             + (c["section_title"] + "\n" if c["section_title"] else "")
             + c["text"] for c in chunks]
    t0 = time.time()
    vecs = model.embed(texts, batch_size=32)
    for c, v in zip(chunks, vecs):
        c["embedding"] = list(map(float, v))
    print(f"[{doc['document_id']}] embedding selesai ({time.time()-t0:.0f}s)")

    conn = connect()
    cur = conn.cursor()
    save_document(conn, cur, doc, path, checksum, lang, len(pages), chunks)
    conn.close()
    print(f"[{doc['document_id']}] SELESAI: {len(chunks)} chunk tersimpan")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="proses satu document_id saja (mis. KCI-AR-2025)")
    ap.add_argument("--force", action="store_true",
                    help="abaikan pemeriksaan checksum (mis. perubahan pipeline text_fixes)")
    args = ap.parse_args()
    docs = [d for d in CORPUS if not args.only or d["document_id"] == args.only]
    if not docs:
        print(f"document_id tidak dikenal: {args.only}")
        sys.exit(1)
    ok = 0
    for d in docs:
        if ingest_one(d, force=args.force):
            ok += 1
    print(f"\nHASIL: {ok}/{len(docs)} dokumen di-ingest")
    sys.exit(0 if ok == len(docs) else 2)


if __name__ == "__main__":
    main()

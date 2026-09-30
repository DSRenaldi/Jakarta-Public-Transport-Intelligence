# -*- coding: utf-8 -*-
"""Fase 3 RAG — evaluasi kualitas retrieval (hit@k & MRR).

Soal faktual: setiap soal punya dokumen yang diharapkan menaungi jawabannya.
Metrik:
  - hit@k (k = 1, 3, 5): dokumen harapan muncul di posisi <= k
  - MRR: reciprocal rank hasil benar pertama

Jalankan:  .venv\\Scripts\\python pipelines\\eval_retrieval.py
Hasil juga disimpan ke .work/eval_retrieval_results.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rag_query import rag_search  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (soal, document_id yang diharapkan, catatan)
QUERIES = [
    ("jumlah penumpang LRT Jakarta tahun 2022", "LRTJ-AR-2022", "ridership moda"),
    ("total pendapatan LRT Jakarta 2022", "LRTJ-AR-2022", "keuangan"),
    ("jumlah penumpang KRL Jabodetabek 2025", "KCI-AR-2025", "ridership moda"),
    ("pendapatan KAI Commuter tahun 2025", "KCI-AR-2025", "keuangan"),
    ("efisiensi biaya operasi KAI Commuter 2025", "KCI-AR-2025", "operasional"),
    ("jumlah kereta/armada LRT Jakarta", "LRTJ-AR-2022", "sarana"),
    ("kebijakan tarif KRL Jabodetabek", "KCI-AR-2025", "kebijakan"),
    ("revenue KAI Commuter 2025", "KCI-AR-2025", "bahasa Inggris"),
    ("jumlah stasiun LRT Jakarta", "LRTJ-AR-2022", "prasarana"),
    ("keselamatan dan kecelakaan LRT Jakarta 2022", "LRTJ-AR-2022", "K3"),
]


def main():
    print(f"Evaluasi retrieval — {len(QUERIES)} soal\n")
    rows = []
    hits = {1: 0, 3: 0, 5: 0}
    rr_sum = 0.0

    for i, (q, expected, note) in enumerate(QUERIES, 1):
        results = rag_search(q, top_k=5)
        rank = None
        for j, r in enumerate(results, 1):
            if r["document_id"] == expected:
                rank = j
                break
        for k in (1, 3, 5):
            if rank is not None and rank <= k:
                hits[k] += 1
        if rank is not None:
            rr_sum += 1.0 / rank
        top1 = results[0] if results else None
        rows.append(dict(
            no=i, query=q, expected=expected, note=note,
            rank=rank,
            top1=(top1["document_id"] + " :: " + (top1["citation"]["section"] or "")
                  if top1 else None),
        ))
        status = f"OK   pos {rank}" if rank else "GAGAL"
        preview = " ".join(top1["text"].split())[:120] if top1 else ""
        section = top1["citation"]["section"] or "-" if top1 else ""
        print(f"[{status:>7}] {q}  -> harap {expected}")
        if top1:
            print(f"          top1: {top1['document_id']} | {section} | {preview}")

    n = len(QUERIES)
    mrr = rr_sum / n
    print("\n===== METRIK =====")
    for k in (1, 3, 5):
        print(f"hit@{k}: {hits[k]}/{n} = {hits[k]/n:.0%}")
    print(f"MRR:   {mrr:.3f}")

    out = ROOT / ".work" / "eval_retrieval_results.json"
    out.write_text(json.dumps(
        dict(metriks=dict(hit_at_1=round(hits[1]/n, 3), hit_at_3=round(hits[3]/n, 3),
                          hit_at_5=round(hits[5]/n, 3), mrr=round(mrr, 3)),
             hasil=rows),
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetail: {out}")
    sys.exit(0)


if __name__ == "__main__":
    main()

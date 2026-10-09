# -*- coding: utf-8 -*-
"""Evaluasi passage-level dan kemampuan abstain retriever RAG.

Berbeda dari evaluasi lama, sebuah hasil tidak dianggap benar hanya karena
berasal dari dokumen yang tepat. Passage harus memuat bukti yang sudah diberi
label. Pertanyaan tanpa cakupan juga wajib ditolak.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rag_query import rag_retrieve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POSITIVE_CASES = [
    {
        "query": "jumlah penumpang LRT Jakarta tahun 2022",
        "evidence": ["685.249", "penumpang"],
    },
    {
        "query": "rincian penumpang LRT Jakarta per bulan pada 2022",
        "evidence": ["januari", "desember", "685.249"],
    },
    {
        "query": "jumlah penumpang KRL atau KAI Commuter tahun 2025",
        "evidence": ["400.997.610", "volume penumpang"],
    },
    {
        "query": "pendapatan KAI Commuter pada tahun 2025",
        "evidence": ["rp3,92 triliun", "pendapatan"],
    },
    {
        "query": "berapa jumlah stasiun LRT Jakarta pada 2022",
        "evidence": ["jumlah stasiun lrt", "6 stasiun"],
    },
    {
        "query": "kapan tarif integrasi JakLingko diresmikan menurut laporan LRT Jakarta 2022",
        "evidence": ["7 oktober 2022", "tarif integrasi"],
    },
    {
        "query": "apa saja isi laporan tahunan KCI 2025",
        "evidence": ["profil perusahaan",
                     "analisis dan pembahasan manajemen"],
    },
]

NEGATIVE_CASES = [
    "apa kebijakan barang bawaan MRT Jakarta",
    "bagaimana fasilitas aksesibilitas Stasiun Dukuh Atas",
    "bagaimana status layanan LRT Jabodebek",
    "apa kebijakan terbaru TransJakarta",
    "resep nasi goreng sederhana",
]


def _evidence_rank(results: list[dict], evidence: list[str]) -> int | None:
    wanted = [" ".join(value.casefold().split()) for value in evidence]
    for rank, result in enumerate(results, start=1):
        text = " ".join(result["text"].casefold().split())
        if all(value in text for value in wanted):
            return rank
    return None


def main() -> None:
    rows = []
    positive_hits = 0
    reciprocal_sum = 0.0
    print("Evaluasi retrieval passage-level\n")
    for case in POSITIVE_CASES:
        payload = rag_retrieve(case["query"], top_k=5)
        rank = _evidence_rank(payload["results"], case["evidence"])
        passed = rank is not None
        positive_hits += int(passed)
        reciprocal_sum += 1.0 / rank if rank else 0.0
        rows.append({"type": "positive", **case, "status": payload["status"],
                     "evidence_rank": rank, "passed": passed})
        print(f"[{'PASS' if passed else 'FAIL'}] {case['query']} "
              f"-> evidence rank {rank}")

    negative_passes = 0
    print("\nEvaluasi abstention\n")
    for query in NEGATIVE_CASES:
        payload = rag_retrieve(query, top_k=5)
        passed = not payload["results"] and payload["status"] in {
            "no_coverage", "no_relevant_result",
        }
        negative_passes += int(passed)
        rows.append({"type": "negative", "query": query,
                     "status": payload["status"], "result_count":
                     len(payload["results"]), "passed": passed})
        print(f"[{'PASS' if passed else 'FAIL'}] {query} "
              f"-> {payload['status']} ({len(payload['results'])} hasil)")

    n_pos = len(POSITIVE_CASES)
    n_neg = len(NEGATIVE_CASES)
    metrics = {
        "passage_hit_at_5": round(positive_hits / n_pos, 3),
        "passage_mrr": round(reciprocal_sum / n_pos, 3),
        "abstention_accuracy": round(negative_passes / n_neg, 3),
        "false_acceptance_rate": round((n_neg - negative_passes) / n_neg, 3),
    }
    print("\n===== METRIK =====")
    for key, value in metrics.items():
        print(f"{key}: {value:.3f}")

    output = ROOT / ".work" / "eval_retrieval_results.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"metrics": metrics, "results": rows},
                                 ensure_ascii=False, indent=2),
                      encoding="utf-8")
    passed = positive_hits == n_pos and negative_passes == n_neg
    print(f"\nQuality gate: {'PASS' if passed else 'FAIL'}")
    print(f"Detail: {output}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

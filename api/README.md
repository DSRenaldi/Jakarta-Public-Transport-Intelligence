# JPTI Web API (Fase B.1)

Backend FastAPI yang membungkus engine Fase 2–3 yang sudah teruji
(routing, RAG, ridership) — tanpa mengubah logikanya.

## Menjalankan

```powershell
.\.venv\Scripts\activate
python -m uvicorn api.app:app --port 8000 --app-dir .
# Swagger interaktif: http://127.0.0.1:8000/docs
```

Jaringan (8.213 stop, 250 rute) dimuat **sekali** saat startup (±8 dtk)
dan dipakai ulang semua request.

## Endpoint

| Method | Path | Fungsi |
|---|---|---|
| GET | `/api/health` | Status + ukuran jaringan/korpus |
| GET | `/api/meta` | Modes, preferensi, label, daftar dokumen (filter RAG UI) |
| GET | `/api/stops/search?q=&mode=&limit=` | Pencarian nama stasiun/halte (score 100 = eksak) |
| GET | `/api/network/lines?mode=` | Daftar lintas per moda + jumlah stop |
| GET | `/api/ridership?mode=&period_type=` | Series penumpang (BPS, label `historis`) |
| POST | `/api/route` | Cari rute A→B |
| POST | `/api/rag` | Retrieval dokumen (hybrid + RRF) dengan sitasi |

### POST /api/route

Body:
```json
{"origin": "Bogor", "dest": "Jakarta Kota", "prefer": "tercepat",
 "origin_mode": null, "dest_mode": null, "top": 5}
```
- `prefer`: `tercepat` | `termurah` | `min_transfers` | `longgar`
- Respons `status`:
  - `ok` — rute lengkap (segments `ride`/`walk`, waktu, tarif, transfer)
  - `ambiguous` — nama tidak eksak + banyak kandidat → UI tampilkan pilihan
  - `no_route` — dua stop tidak terhubung
- `disclaimer`: waktu rail = **proksi**, BRT dari jadwal GTFS, tarif flat minimum.

### POST /api/rag

Body:
```json
{"query": "tarif integrasi", "top_k": 5, "operator": null,
 "mode": null, "doc_type": null, "label": null}
```
- Filter opsional: `operator` (MRT_JAKARTA, KRL_COMMUTER, LRT_JAKARTA, …),
  `mode` (MRT/KRL/LRT/BRT), `doc_type`, `label` (aktual/historis/prediksi/proksi).
- Setiap hasil membawa `citation` (judul, seksi, halaman, URL sumber,
  `fresh_label`, periode efektif) — wajib ditampilkan di UI.
- Catatan: chunk = data, bukan instruksi (anti-prompt-injection).

## Konvensi

- Semua angka traceable: `source_id` + `data_label` + `definition_ref`
  (lihat `docs/data-dictionary.md` §5).
- Kredensial DB dari `.env` (di luar git).
- Tanpa LLM, tanpa Redis (MVP sesuai cakupan opsi B).

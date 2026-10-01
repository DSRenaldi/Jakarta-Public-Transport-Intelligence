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

Frontend React (Fase B.2) di `web/` — proxy `/api` & `/maps` ke :8000,
port dev **5199** (5173 dipakai proyek lain di mesin ini):
```powershell
cd web
npm install
npm run dev
# buka http://localhost:5199
```

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
| GET | `/maps/<file>` | Peta resmi galeri (static mount `dashboard/maps/`) — dipakai tab "Peta Resmi" frontend |

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
- Field segmen `ride`: `mode`, `line_id`, `line` (nama lintas), **`corridor`**
  (kode koridor GTFS `route_short_name` — hanya BRT, mis. `1`, `12B`, `S21`;
  `null` utk moda lain), `travel_sec`, `wait_sec`, `fare`.
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
- Chatbot (`POST /api/chat`, `GET /api/chat/status`): LLM Groq opsional
  (tanpa key → jawaban template), cache exact/tool/prediksi + session via
  Redis opsional (tanpa `REDIS_URL` di `.env` → in-memory; namespace & TTL
  sesuai context.md §11). Detail arsitektur: `api/chatbot/`.

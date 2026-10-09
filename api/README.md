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
| POST | `/api/chat` | Percakapan chatbot dengan context per `session_id` |
| DELETE | `/api/chat/session?session_id=` | Hapus history dan context session chat |
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
  `null` utk moda lain), `travel_sec`, `wait_sec`, `fare`, `time_method`, dan
  `source_id`.
- `itinerary` adalah langkah pengguna yang dibentuk deterministik dari seluruh
  segmen berurutan. Ride berurutan pada layanan yang sama digabung; rangkaian
  transfer jalan kaki menyimpan titik antara pada `via`.
- `route_metrics` membedakan `service_change_count`, `mode_change_count`,
  `walking_transfer_count`, dan nilai internal `routing_transfer_score`.
  Field kompatibilitas `transfers` berarti pergantian layanan yang dapat
  dijelaskan kepada pengguna, bukan skor penalti internal Dijkstra.
- `sources` memuat provenance jaringan, tarif minimum, serta metodologi
  perhitungan JPTI untuk audit internal/API. Routing tidak menggunakan RAG
  untuk mencari sumber. Chatbot tidak menampilkan field ini sebagai sitasi
  atau kartu referensi pada jawaban rute.
- `time_display` adalah format publik jam/menit; `time_sec` tetap tersedia
  sebagai metadata mesin tetapi tidak ditampilkan chatbot.
- `disclaimer`: waktu rail = **proksi**, BRT dari jadwal GTFS, tarif flat minimum.

### POST /api/rag

Body:
```json
{"query": "tarif integrasi", "top_k": 5, "operator": null,
 "mode": null, "doc_type": null, "label": null}
```
- Respons membawa `status`: `ok`, `no_coverage`, atau `no_relevant_result`.
  Jika filter tidak diberikan, retriever menginferensikan operator/moda dan
  jenis dokumen yang disebut eksplisit dalam pertanyaan. LRT Jakarta dan LRT
  Jabodebek selalu dipisahkan.
- Retriever menerapkan ambang relevansi passage. Korpus yang tidak memiliki
  sumber sesuai akan menghasilkan nol hasil, bukan potongan dokumen terdekat.
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
- Klarifikasi rute disimpan terstruktur di session. Balasan nomor/nama kandidat
  langsung dipetakan ke `stop_id`, mempertahankan asal/tujuan sebelumnya, lalu
  menjalankan routing kembali. Ejaan pencarian `Priok` dan `Priuk` dianggap
  setara tanpa mengubah nama resmi yang ditampilkan.
- Frontend menyimpan maksimal 100 pesan chat terakhir di `localStorage`,
  mempertahankan tab Chat setelah refresh, dan menyediakan tombol **Hapus
  chat**. Tombol tersebut mereset session backend, merotasi `session_id`, dan
  tidak menghapus persistent user memory yang dikelola terpisah.

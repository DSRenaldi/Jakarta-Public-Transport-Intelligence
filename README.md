# JPTI — Jakarta Public Transport Intelligence

Platform analisis transportasi umum Jabodetabek yang menggabungkan dashboard historis, pencarian rute multimoda, analisis kepadatan, peta jaringan, dan chatbot berbasis RAG.

JPTI membedakan sumber sesuai jenis pertanyaannya: data numerik berasal dari database atau tool analitik, dokumen dijawab melalui RAG, rute dihitung oleh routing engine, dan kepadatan diberi label `aktual`, `historis`, `prediksi`, atau `proksi` sesuai ketersediaan data.

## Fitur

- Dashboard penumpang bulanan lintas moda.
- Peta jaringan dan peta resmi MRT, LRT, KRL, dan TransJakarta.
- Perencana perjalanan multimoda untuk MRT Jakarta, KRL Commuter Line, LRT Jakarta, LRT Jabodebek, dan TransJakarta.
- Visualisasi titik naik/turun serta perpindahan moda, jalur, dan layanan.
- Timeline perjalanan yang mengelompokkan perjalanan per layanan.
- Expand detail untuk melihat stasiun, halte, atau terminal yang dilewati.
- Estimasi waktu, tarif minimum, jumlah pergantian layanan, dan kepadatan berbasis proksi.
- Chatbot dengan intent classifier, tool routing/analitik, RAG, fallback template, dan optional Groq LLM.
- Exact cache, tool-result cache, session cache, semantic cache, serta Redis sebagai hot cache opsional.
- Persistent memory pengguna dengan kontrol lihat, ubah, dan hapus.

## Preview

Artefak yang dapat langsung dilihat di repository:

- [Dashboard historis](dashboard/index.html)
- [Galeri peta jaringan](dashboard/network_map.html)
- [Peta jaringan interaktif](dashboard/network_map_interaktif.html)
- [Dokumentasi API interaktif](http://127.0.0.1:8000/docs) setelah API dijalankan secara lokal

Untuk preview penuh dengan pencarian rute dan chatbot, jalankan API dan frontend mengikuti langkah di bawah. Repository ini belum menyediakan deployment demo publik.

## Status proyek

JPTI berada pada tahap **MVP development**. Komponen routing multimoda, dashboard, RAG inti, chatbot, cache, persistent memory, dan frontend React sudah tersedia untuk penggunaan lokal. Integrasi production seperti autentikasi pengguna, deployment publik, monitoring, data real-time, dan load factor per segmen masih berada di luar cakupan MVP.

## Arsitektur singkat

```text
React + Vite (web/)
        │  /api dan /maps
        ▼
FastAPI (api/)
   ├── routing engine dan network graph
   ├── analytics: ridership, tarif, jadwal, crowding
   ├── chatbot: intent → tools/RAG → formatter/LLM
   └── cache/session/memory layer
        │
        ├── PostgreSQL + PostGIS  (sumber data terstruktur kanonik)
        ├── Redis                 (cache dan session opsional)
        └── file/object data      (raw data, korpus, dan aset peta)
```

## Struktur repository

| Direktori | Isi |
|---|---|
| `api/` | FastAPI, endpoint, chatbot, cache, session, dan memory |
| `web/` | Frontend React + Vite |
| `pipelines/` | Ingest data, routing, crowding, RAG, dashboard, dan export peta |
| `db/migrations/` | Migrasi PostgreSQL/PostGIS 0001–0009 |
| `dashboard/` | Dashboard HTML dan galeri peta resmi |
| `docs/` | Data dictionary, source registry, metodologi, dan rencana |
| `tests/` | Pengujian integrasi/grounding/RAG/crowding |
| `data/` | Data mentah dan hasil olahan; sebagian tidak disertakan di Git |

## Persyaratan

- Python 3.10 atau lebih baru.
- Node.js dan npm.
- PostgreSQL dengan ekstensi PostGIS.
- Redis 7 atau kompatibel, opsional untuk pengembangan.
- Data jaringan dan korpus yang sudah di-ingest ke database.

## Menjalankan secara lokal

### 1. Siapkan environment Python

PowerShell Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Siapkan konfigurasi database

Buat file `.env` di root repository. Jangan commit file ini.

```dotenv
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=jpti
PGPASSWORD=ganti-password-dev
PGDATABASE=transum_jakarta

# Opsional: tanpa nilai ini cache memakai in-memory backend.
REDIS_URL=redis://127.0.0.1:6379/0

# Opsional: tanpa key chatbot memakai fallback template.
GROQ_API_KEY=
GROQ_MODEL=

# Opsional, default aktif.
SEMANTIC_CACHE=1
```

Pastikan database dan PostGIS tersedia, lalu jalankan migrasi:

```powershell
python pipelines/migrate.py
```

Migrasi hanya membuat atau memperbarui struktur database. Database baru belum berisi seluruh jaringan dan korpus. Untuk mengisi atau memperbarui data, gunakan pipeline di `pipelines/` dengan urutan umum berikut:

```text
GTFS TransJakarta  → ingest_gtfs.py
Data rail          → ingest_rail.py
Hub transfer       → build_transfers.py
Dokumen RAG        → ingest_documents.py
Export peta        → export_map.py (setelah data jaringan tersedia)
```

Setiap pipeline membutuhkan artefak sumber dan konfigurasi yang sesuai; jangan menganggap data publik otomatis terunduh hanya dengan menjalankan API. Sumber, periode, lisensi, lokasi artefak, dan status data dijelaskan di `docs/source-registry.md` serta `docs/data-dictionary.md`.

### 3. Jalankan API

Dari root repository:

```powershell
python -m uvicorn api.app:app --port 8000 --app-dir .
```

API tersedia di `http://127.0.0.1:8000`.

- Swagger: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/api/health`

### 4. Jalankan frontend

Terminal kedua:

```powershell
cd web
npm ci
npm run dev
```

Buka `http://localhost:5199`. Vite mem-proxy `/api` dan `/maps` ke API pada port 8000.

## Endpoint penting

| Method | Endpoint | Kegunaan |
|---|---|---|
| `GET` | `/api/health` | Status API, jaringan, dan korpus |
| `GET` | `/api/meta` | Metadata moda, preferensi, dan dokumen |
| `GET` | `/api/stops/search` | Pencarian stasiun/halte |
| `GET` | `/api/ridership` | Data penumpang historis |
| `POST` | `/api/route` | Routing multimoda A ke B |
| `POST` | `/api/rag` | Retrieval dokumen bersitasi |
| `POST` | `/api/chat` | Chatbot dengan context session |
| `DELETE` | `/api/chat/session` | Menghapus context percakapan |
| `GET/POST/PATCH/DELETE` | `/api/memory` | Persistent memory pengguna |

Dokumentasi endpoint yang lebih lengkap tersedia di [api/README.md](api/README.md).

## Perintah pengujian

Frontend:

```powershell
cd web
npm test
npm run lint
npm run build
```

Backend dan pipeline:

```powershell
pytest -q
python pipelines/test_routes.py
```

Sebagian pengujian membutuhkan PostgreSQL, data jaringan, atau environment yang sesuai. Jika dependency infrastrukturnya tidak tersedia, jalankan pengujian frontend dan unit test yang tidak membutuhkan database terlebih dahulu.

## Docker Compose (opsional)

`docker-compose.yml` menyediakan PostgreSQL/PostGIS, Redis, dan API untuk lingkungan development. Konfigurasi tersebut masih berstatus draft dan membutuhkan data ingest setelah database dibuat.

```powershell
docker compose up --build
```

Frontend tetap dijalankan dari `web/`, atau hasil `npm run build` dapat disajikan oleh web server terpisah.

## Catatan data dan batasan

- Dataset OD lengkap dan load factor per segmen belum tersedia terbuka untuk semua moda.
- Estimasi waktu rail dan kepadatan dapat berstatus `proksi`, bukan pengukuran real-time.
- Status layanan, tarif, jadwal, dan angka penumpang harus dibaca bersama periode serta sumbernya.
- RAG digunakan untuk dokumen; RAG bukan sumber angka rute, tarif, atau kepadatan ketika tool terstruktur tersedia.
- Redis bukan sumber data kanonik dan aplikasi memiliki fallback in-memory untuk development.
- LLM bersifat opsional; tanpa `GROQ_API_KEY`, chatbot tetap dapat menggunakan formatter/template deterministik.

## Dokumentasi lanjutan

- [Data dictionary](docs/data-dictionary.md)
- [Source registry](docs/source-registry.md)
- [API README](api/README.md)
- [Web README](web/README.md)
- [Project context](context.md)

## Kontribusi dan issue

Pull request dan issue dipersilakan untuk perbaikan data, bug, dokumentasi, aksesibilitas, dan kualitas routing. Saat melaporkan masalah, sertakan:

- langkah untuk mereproduksi;
- moda, stasiun/halte, dan arah perjalanan yang digunakan;
- periode atau timestamp data jika terkait angka;
- pesan error atau screenshot yang relevan;
- informasi apakah masalah terjadi pada API, frontend, pipeline, RAG, atau cache.

Sebelum membuat pull request, jalankan pengujian yang relevan dan jelaskan dependency eksternal yang diperlukan.

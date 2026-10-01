# JPTI — image API (FastAPI + chatbot)
#
# DRAFT — BELUM DIUJI (1 Okt 2026): mesin dev tidak punya Docker.
# Jalankan bersama docker-compose.yml (postgres + redis + api) atau:
#   docker build -t jpti-api .
#   docker run --env-file .env -p 8000:8000 jpti-api
#
# Catatan produksi:
# - .env berisi kredensial — lebih baik DI-MOUNT sebagai volume/secret
#   daripada di-COPY ke image (compose sudah memount read-only).
# - Postgres target HARUS punya ekstensi PostGIS (geometri stops/lines).
# - Migrations db/migrations/*.sql dijalankan otomatis saat startup.

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl utk HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Kode: API + helper DB/pipeline + migrations + aset peta statis (/maps)
COPY api/ ./api/
COPY pipelines/ ./pipelines/
COPY db/ ./db/
COPY dashboard/ ./dashboard/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# migrations → uvicorn (app membaca .env dari WORKDIR)
CMD ["sh", "-c", "python pipelines/migrate.py && exec python -m uvicorn api.app:app --host 0.0.0.0 --port 8000"]

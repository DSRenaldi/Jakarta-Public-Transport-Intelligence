# -*- coding: utf-8 -*-
"""Buat manifest artefak raw (sha256, ukuran, sumber, status) di data/raw/MANIFEST.md."""
import hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
raw = root / "data" / "raw"

status_map = {
    "krl/jadwal_gapeka_jabodetabek_update_feb2026.pdf": ("SRC-KRL-03 (kci.id)", "OK - PDF 13 hlm valid"),
    "krl/annual_report_2025.pdf": ("SRC-KRL-02 (kci.id)", "OK - PDF 550 hlm valid"),
    "lrt_jakarta/annual_report_2022.pdf": ("SRC-LRTJ-04 (lrtjakarta.co.id)", "OK - PDF 366 hlm valid"),
    "mrt/annual_report_2024_wayback.pdf": ("SRC-MRT-02 (Wayback 14-06-2026)", "CHECK - terpotong 5.24 MB (CDX asli 3.980.657 B); gagal parse PDF; unduh ulang + verifikasi digest"),
    "mrt/annual_report_2023_wayback.pdf": ("SRC-MRT-02 (Wayback 14-06-2026)", "CHECK - terpotong (CDX asli 4.256.521 B); unduh ulang + verifikasi digest"),
    "mrt/data_jumlah_penumpang_mrt.csv": ("SRC-MRT-01 (satudata.jakarta.go.id)", "OK - 42 baris bulanan Jan 2023-Jun 2026"),
    "transjakarta/gtfs_transjakarta_2026-07-27.zip": ("SRC-TJ-02 (gtfs.transjakarta.co.id, CC BY 4.0)", "OK - 13 file GTFS (frequencies + fares hadir)"),
}

lines = [
    "# Manifest Artefak Raw - JPTI",
    "",
    "- **Proyek:** Jakarta Public Transport Intelligence (JPTI)",
    "- **Fase:** 1 (Fondasi data dan dashboard historis)",
    "- **Diambil:** 29 September 2026",
    "",
    "| File | Ukuran | SHA-256 (16) | Sumber | Status |",
    "|---|---|---|---|---|",
]

for p in sorted(raw.rglob("*")):
    if not p.is_file() or p.name == ".gitkeep":
        continue
    rel = p.relative_to(raw).as_posix()
    if rel.startswith("bps/") and (rel.endswith(".csv") or rel.endswith("_metadata.json")):
        continue  # hasil pipeline, dicatat di dokumen lain
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    src, st = status_map.get(rel, ("-", "-"))
    lines.append(f"| `{rel}` | {p.stat().st_size:,} B | `{h}` | {src} | {st} |")

lines += [
    "",
    "## Catatan kualitas",
    "",
    "- `mrt/data_jumlah_penumpang_mrt.csv`: Jan-Mar 2023 anomali rendah (1,09 jt / 0,53 jt / 0,96 jt vs tren ~3 jt); Jul 2025 = Jun 2025 (4.419.821, dugaan duplikat). Definisi berbeda dari BPS (Apr 2026: SDI 4.347.308 vs BPS 3.879.260) - simpan terpisah per source_id.",
    "- `bps/*_monthly_passengers.csv`: hanya tahun 2026 (tabel dinamis BPS; permintaan RSC 2023-2025 menjawab `not-available`).",
    "- Dataset harian 2023 TransJakarta (SRC-TJ-04): resource rusak (`download: \"http://-\"`) - file tidak tersedia.",
    "",
    "## Respons mentah BPS",
    "",
    "Respons React Server Action `getDataTable` tersimpan di `bps/rsc_raw/` (6 file).",
]

(root / "data" / "raw" / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")
print("OK: data/raw/MANIFEST.md")

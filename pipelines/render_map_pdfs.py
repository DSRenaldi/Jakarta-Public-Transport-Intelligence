# -*- coding: utf-8 -*-
"""Render PDF peta ke PNG + buat MANIFEST.json (sumber, versi, checksum).

Asset resmi/peta per moda di data/raw/maps/. Jalankan setelah unduh.
"""
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "data" / "raw" / "maps"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# nama file -> (judul, sumber, versi/periode, catatan)
ASSETS = {
    "fdtj_integrasi_2026_08c.pdf": ("Peta Integrasi Transportasi Umum Jakarta",
                                     "https://transportforjakarta.or.id/peta",
                                     "v26.08c (Agu 2026)",
                                     "Change log: +stasiun LRT Jakarta s.d. Manggarai; Stasiun KRL Karet dinonaktifkan"),
    "fdtj_integrasi_2026_08c.jpg": ("Peta Integrasi (preview JPG)",
                                     "https://transportforjakarta.or.id/peta",
                                     "v26.08c (Agu 2026)", "preview 1024x724"),
    "krl_area0.png": ("Peta Rute Jabodetabek & Merak",
                       "https://www.kci.id/perjalanan-krl/peta-rute (API /api/krl/routemap)",
                       "terkini (diakses 2026-09-30)",
                       "Resmi KAI Commuter; stasiun Karet digarisabai (nonaktif)"),
    "krl_area2.png": ("Peta Rute KCI area 2",
                       "https://www.kci.id/perjalanan-krl/peta-rute (API /api/krl/routemap)",
                       "terkini (diakses 2026-09-30)", "area non-Jabodetabek (luar cakupan)"),
    "krl_area6.png": ("Peta Rute KCI area 6",
                       "https://www.kci.id/perjalanan-krl/peta-rute (API /api/krl/routemap)",
                       "terkini (diakses 2026-09-30)", "area non-Jabodetabek (luar cakupan)"),
    "krl_area8.png": ("Peta Rute KCI area 8",
                       "https://www.kci.id/perjalanan-krl/peta-rute (API /api/krl/routemap)",
                       "terkini (diakses 2026-09-30)", "area non-Jabodetabek (luar cakupan)"),
    "tj_integrasi.jpg": ("Peta Integrasi TransJakarta",
                          "https://transjakarta.co.id/peta-rute (smk.transjakarta.co.id)",
                          "terkini (diakses 2026-09-30)", "Resmi PT Transportasi Jakarta"),
    "fdtj_mrt_2026_01.pdf": ("Peta Rute MRT Jakarta (kabin)",
                              "https://transportforjakarta.or.id/mrtjakarta",
                              "Jan 2026", "FDTJ; 13 stasiun Lin Utara-Selatan"),
    "fdtj_lrtj_2024_11.pdf": ("Peta Rute LRT Jakarta",
                               "https://transportforjakarta.or.id/lrtjakarta",
                               "Nov 2024",
                               "TERLALU LAMA utk Fase 1B: edisi ini sebelum ekstensi Velodrome-Manggarai (operasional 26 Agu 2026; 11 stasiun)"),
    "fdtj_lrtb_2024_11.pdf": ("Peta Rute LRT Jabodebek",
                               "https://transportforjakarta.or.id/lrtjabodebek",
                               "Nov 2024", "18 stasiun; tak ada perubahan lin sejak 2023"),
    "fdtj_tj_2024_11.pdf": ("Peta Rute TransJakarta (alternatif)",
                             "https://transportforjakarta.or.id/transjakarta",
                             "Nov 2024", "FDTJ; ada juga peta resmi per-rute 2025-2026"),
    "fdtj_krl_2024_11.pdf": ("Peta Rute Commuter Line (alternatif)",
                              "https://transportforjakarta.or.id/commuterline",
                              "Nov 2024", "FDTJ; ada juga peta resmi kci.id (krl_area0.png)"),
}

# koridor TransJakarta resmi (file, kode koridor)
TJ_KOR = {}
for i in range(1, 15):
    f = M / f"tj_kor{i}.jpg"
    if f.exists():
        TJ_KOR[f.name] = f"Koridor {i} TransJakarta"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    manifest = {"diakses": str(date.today()), "file": {}}

    # render PDF -> PNG (halaman 1, 200 DPI)
    for f in sorted(M.glob("*.pdf")):
        out = M / (f.stem + ".png")
        try:
            doc = pymupdf.open(str(f))
            page = doc[0]
            mat = pymupdf.Matrix(200 / 72, 200 / 72)
            pix = page.get_pixmap(matrix=mat)
            pix.save(str(out))
            doc.close()
            print(f"render: {f.name} -> {out.name} ({pix.width}x{pix.height})")
        except Exception as e:
            print(f"GAGAL render {f.name}: {e}")

    # manifest utk semua asset (PDF, PNG, JPG) yang terdaftar
    for name, (judul, sumber, versi, notes) in ASSETS.items():
        p = M / name
        if not p.exists():
            print(f"absen: {name}")
            continue
        manifest["file"][name] = {
            "judul": judul, "sumber": sumber, "versi": versi,
            "catatan": notes, "sha256": sha256(p), "bytes": p.stat().st_size,
        }
    for name, judul in TJ_KOR.items():
        manifest["file"][name] = {
            "judul": judul,
            "sumber": "https://transjakarta.co.id/peta-rute (smk.transjakarta.co.id/aset/berkas/rute/)",
            "versi": "terkini per rute (2025-2026)",
            "catatan": "Peta rute resmi TransJakarta per koridor",
            "sha256": sha256(M / name), "bytes": (M / name).stat().st_size,
        }

    out = M / "MANIFEST.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nmanifest: {out.name} ({len(manifest['file'])} file)")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Verifikasi headless dashboard/network_map.html (galeri peta resmi)."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
URL = "http://localhost:8791/network_map.html"
SHOT = ROOT / ".work" / "map_gallery_check.png"


async def main():
    from playwright.async_api import async_playwright
    errors = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(1000)

        # periksa tiap tab: aktif, gambar termuat (naturalWidth > 0)
        report = []
        tabs = await page.query_selector_all("section.tab")
        for i, _ in enumerate(tabs):
            await page.evaluate(f"show({i})")
            await page.wait_for_timeout(300)
            info = await page.evaluate(f"""(() => {{
                const s = document.querySelector('#tab-{i}');
                const img = s.querySelector('.mapbox img');
                return {{
                    title: s.querySelector('h2').textContent,
                    visible: s.classList.contains('active'),
                    img: img ? img.src.split('/').pop() : null,
                    loaded: img ? img.naturalWidth > 0 : false,
                    w: img ? img.naturalWidth : 0,
                    h: img ? img.naturalHeight : 0,
                    korGrid: s.querySelectorAll('.kor').length,
                }};
            }})()""")
            report.append(info)

        # tab integrasi utk screenshot + test lightbox
        await page.evaluate("show(0)")
        await page.wait_for_timeout(500)
        await page.evaluate("document.querySelector('#tab-0 .mapbox img').click()")
        await page.wait_for_timeout(400)
        zoom_open = await page.evaluate(
            "document.getElementById('zoomer').classList.contains('open')")
        await page.evaluate("document.getElementById('zoomer').classList.remove('open')")
        await page.screenshot(path=str(SHOT))
        await browser.close()

    for r in report:
        status = "OK " if (r["visible"] and r["loaded"]) else "FAIL"
        print(f"[{status}] {r['title']:<22} img={r['img']} {r['w']}x{r['h']}"
              + (f" +{r['korGrid']} koridor" if r["korGrid"] else ""))
    print(f"lightbox: {'OK' if zoom_open else 'FAIL'}")
    print(f"JS errors: {len(errors)}")
    for e in errors:
        print("  !!", e)
    ok = not errors and all(r["loaded"] for r in report) and zoom_open
    print("HASIL:", "OK" if ok else "GAGAL")
    sys.exit(0 if ok else 1)


asyncio.run(main())

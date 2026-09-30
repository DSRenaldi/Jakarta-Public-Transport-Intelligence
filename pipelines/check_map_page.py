# -*- coding: utf-8 -*-
"""Verifikasi headless network_map.html: JS error + jumlah layer + screenshot."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
URL = "http://localhost:8791/network_map.html"
SHOT = ROOT / ".work" / "network_map_check.png"


async def main():
    from playwright.async_api import async_playwright
    errors, console = [], []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: console.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(2500)
        info = await page.evaluate("""() => {
            const map = window.__mapDebug || null;
            return {
                hasMap: typeof L !== 'undefined',
                nFeatures: (typeof geo !== 'undefined') ? geo.features.length : -1,
                layersOnMap: (typeof map !== 'undefined' && map && map._layers)
                    ? Object.keys(map._layers).length : -1,
            };
        }""")
        # cek layer per moda langsung dari state Leaflet
        detail = await page.evaluate("""() => {
            const out = {};
            for (const k of ['MRT','LRT','KRL','BRT']) {
                out['lines_' + k] = byMode[k].getLayers().length;
                out['stops_' + k] = stopsLayer[k].getLayers().length;
            }
            out['xfers'] = xfers.getLayers().length;
            out['countText'] = document.getElementById('count').textContent;
            return out;
        }""")
        await page.screenshot(path=str(SHOT))
        await browser.close()
    print(f"JS pageerror: {len(errors)}")
    for e in errors:
        print("  !!", e)
    print(f"console errors: ", [c for c in console if c.startswith('[error]')])
    print("info:", info)
    print("detail:", detail)
    print(f"screenshot: {SHOT}")
    ok = not errors and info["nFeatures"] == 249 + 208 + 86
    print("HASIL:", "OK" if ok else "GAGAL")
    sys.exit(0 if ok else 1)


asyncio.run(main())

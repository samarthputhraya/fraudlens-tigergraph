"""Render the diagrams in this folder to PNG with headless Chrome (Playwright).

    python docs/diagrams/render.py          # architecture.html -> .png; sequence.mmd -> .svg and .png

architecture.html is laid out by hand (an auto-layout of that many components crosses its own edges); the sequence
diagram is Mermaid. Needs Playwright with Chrome, and network access to cdn.jsdelivr.net for Mermaid 10.9.1.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>body{margin:0;background:#fff;font-family:Inter,Segoe UI,Arial,sans-serif} #out{display:inline-block;padding:24px}</style>
</head><body><div id="out"></div></body></html>"""


def render(page, src: str) -> str:
    return page.evaluate("""async (src) => {
        mermaid.initialize({startOnLoad: false, theme: 'base', securityLevel: 'strict',
          themeVariables: {fontFamily: 'Segoe UI, Arial, sans-serif', fontSize: '15px', primaryColor: '#f7f7f9',
                           primaryBorderColor: '#888', lineColor: '#555'},
          flowchart: {htmlLabels: true, curve: 'basis', nodeSpacing: 28, rankSpacing: 46},
          sequence: {actorMargin: 38, messageMargin: 34, mirrorActors: false, wrap: false}});
        const {svg} = await mermaid.render('d' + Date.now(), src);
        const out = document.getElementById('out');
        out.innerHTML = svg;
        // Mermaid sizes the SVG to its container; give it its natural size so nothing is squeezed
        const el = out.querySelector('svg'), vb = el.viewBox.baseVal;
        el.setAttribute('width', vb.width); el.setAttribute('height', vb.height); el.style.maxWidth = 'none';
        return out.innerHTML;
    }""", src)


def main() -> int:
    names = sys.argv[1:] or ["architecture", "sequence"]
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.set_content(PAGE)
        page.wait_for_function("window.mermaid !== undefined", timeout=30000)
        for name in names:
            if (HERE / f"{name}.html").exists():
                shot = b.new_page(viewport={"width": 1800, "height": 1100}, device_scale_factor=2)
                shot.goto((HERE / f"{name}.html").as_uri())
                shot.locator("#canvas").screenshot(path=str(HERE / f"{name}.png"))
                print(f"{name}: {name}.html -> {name}.png (2x)")
                shot.close()
                continue
            svg = render(page, (HERE / f"{name}.mmd").read_text(encoding="utf-8"))
            (HERE / f"{name}.svg").write_text(svg, encoding="utf-8")
            page.locator("#out").screenshot(path=str(HERE / f"{name}.png"))
            box = page.locator("#out").bounding_box()
            print(f"{name}: {int(box['width'])}x{int(box['height'])} css px -> {name}.svg, {name}.png (2x)")
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

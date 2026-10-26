"""Report export - PNG, PPTX, PDF (docs/TODO.md, fixed 2026-10-22; SPEC.md section 5: "Export (PNG/SVG/
PPTX/PDF, one block per slide)").

Report blocks (`app/api_report.py`'s own flat list - `chart_id`/`chart_title`/`chart_html`/`chart_width`/
`chart_height`/`finding`, in final render order, already pre-sized) needed no restructuring for this - the
real gap was RENDERING. `app/charts.py`'s charts are a genuine SVG-shapes + absolutely-positioned-HTML-
labels hybrid BY DESIGN (that module's own docstrings explain why `foreignObject`/SVG `<text>` are
rejected for fluid width - see `sunburst()`/`chart_label()`), and several chart types are 100% HTML/CSS
with no SVG at all (`theme_rows()`). A faithful render therefore needs a real browser engine, not a
lightweight SVG rasterizer - confirmed by investigation before choosing Playwright (headless Chromium)
over any pure-Python SVG library.

**SVG export is deliberately NOT offered, found during this stage, not assumed from the plan**: the
original plan sketched "SVG kept as a per-block export... just serve the chart_html fragment's SVG
content." Building it revealed this doesn't work honestly - extracting just the `<svg>...</svg>` substring
from a chart's `chart_html` would SILENTLY DROP every absolutely-positioned HTML label div next to it
(the exact thing `app/charts.py`'s own docstrings say those charts need, since SVG `<text>`/`foreignObject`
can't do what those labels need). Shipping that would mean an export that LOOKS like the real chart minus
its own labels - exactly the kind of misleading output this project's own design discipline avoids
elsewhere (the Arc tab, the sub-theme coverage gate). PNG/PPTX/PDF are all screenshot-based instead, so
they are always faithful to whatever the real chart actually renders, hybrid or not.

Each block is rendered in its OWN headless-browser page, wrapped in the exact same CSS custom-property
theme shell `app/charts.py::render()` already uses for its internal `/frame/{id}` design-review gallery
(the `CSS` constant - reused here unchanged, not reinvented), so colors/fonts/spacing match the live
report page exactly.
"""
from __future__ import annotations

import html
import io
from dataclasses import dataclass

from .charts import CSS

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost:wght@300;400;500;600&display=swap">
<style>{css}html,body{{background:#f2f7f6;margin:0}}
.xp-block{{padding:28px;box-sizing:border-box}}
.xp-title{{font-size:22px;font-weight:600;margin-bottom:16px}}
</style></head>
<body>{body}</body></html>"""


@dataclass
class ExportBlock:
    title: str
    html: str
    width: int
    height: int


def _block_html(block: ExportBlock) -> str:
    # The title lives INSIDE the `.v` container, not as a sibling - `.v`'s own `font-family:'Jost'`
    # (see app/charts.py's `CSS`) only cascades to its own descendants; a sibling title fell back to the
    # browser's serif default the first time this was built, confirmed by actually rendering one and
    # looking at it, not assumed fixed.
    return (
        f'<div class="xp-block" style="width:{block.width + 56}px">'
        f'<div class="v" style="width:{block.width}px;min-height:{block.height}px;position:relative">'
        f'<div class="xp-title">{html.escape(block.title)}</div>{block.html}</div></div>'
    )


_FONT_HOSTS = ("https://fonts.googleapis.com/", "https://fonts.gstatic.com/")


def _locked_page(browser, viewport: dict):
    """A page with no JavaScript and no network except the font CSS/files: the charts are plain HTML/SVG,
    so a value that ever slips past esc() cannot run code or reach the server's private network."""
    page = browser.new_page(viewport=viewport, java_script_enabled=False)
    page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(_FONT_HOSTS) else route.abort())
    return page


def _full_page_html(blocks: list[ExportBlock]) -> str:
    body = "".join(_block_html(b) for b in blocks)
    return _PAGE_TEMPLATE.format(css=CSS, body=body)


def render_report_png(blocks: list[ExportBlock]) -> bytes:
    """One tall PNG of the whole report, blocks stacked top to bottom - the intuitive "picture of my
    report" shape, not a separate file per block (that's what PPTX/PDF are for)."""
    from playwright.sync_api import sync_playwright

    if not blocks:
        blocks = [ExportBlock(title="", html="<p>Nothing to export.</p>", width=600, height=80)]
    width = max(b.width for b in blocks) + 56
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _locked_page(browser, {"width": width, "height": 800})
            page.set_content(_full_page_html(blocks), wait_until="networkidle")
            return page.screenshot(full_page=True)
        finally:
            browser.close()


def _render_block_pngs(blocks: list[ExportBlock]) -> list[bytes]:
    """One PNG per block, each its own browser page sized to that block's own width/height - shared by
    `build_pptx`/`build_pdf` below (both need one image per slide/page, not one combined image)."""
    from playwright.sync_api import sync_playwright

    pngs: list[bytes] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for b in blocks:
                page = _locked_page(browser, {"width": b.width + 56, "height": b.height + 100})
                page.set_content(_full_page_html([b]), wait_until="networkidle")
                pngs.append(page.screenshot(full_page=True))
                page.close()
        finally:
            browser.close()
    return pngs


def build_report_pptx(blocks: list[ExportBlock]) -> bytes:
    """One slide per block, in order - SPEC.md's own "one block per slide." Each slide just embeds that
    block's own screenshot (from `_render_block_pngs`), scaled to fit a 16:9 slide without distortion."""
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Emu, Inches

    pngs = _render_block_pngs(blocks)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]
    slide_w, slide_h = prs.slide_width, prs.slide_height

    for png in pngs:
        slide = prs.slides.add_slide(blank_layout)
        img_w, img_h = Image.open(io.BytesIO(png)).size
        scale = min(slide_w / img_w, slide_h / img_h) * 0.95
        w, h = Emu(int(img_w * scale)), Emu(int(img_h * scale))
        left, top = Emu(int((slide_w - w) / 2)), Emu(int((slide_h - h) / 2))
        slide.shapes.add_picture(io.BytesIO(png), left, top, width=w, height=h)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def build_report_pdf(blocks: list[ExportBlock]) -> bytes:
    """One page per block, same "one block per slide" shape as the PPTX above, just as PDF pages instead
    of slides."""
    from PIL import Image
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdfcanvas

    pngs = _render_block_pngs(blocks)
    page_w, page_h = landscape(letter)
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(page_w, page_h))

    for png in pngs:
        img_w, img_h = Image.open(io.BytesIO(png)).size
        scale = min(page_w / img_w, page_h / img_h) * 0.95
        w, h = img_w * scale, img_h * scale
        x, y = (page_w - w) / 2, (page_h - h) / 2
        c.drawImage(ImageReader(io.BytesIO(png)), x, y, width=w, height=h)
        c.showPage()

    c.save()
    return buf.getvalue()

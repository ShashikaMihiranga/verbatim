import html, json, math, random, zlib

from .chart_data import ReportData
from .charts_medium import f_group_mix


def esc(s): return html.escape(str(s))
def fmt(n): return f"{n:,}"

CSS = """
body{margin:0}
.v{--bg:#f2f7f6;--surface:#ffffff;--ink:#12303a;--muted:#546b71;--line:#d3e0df;--accent:#0f6688;--on-accent:#ffffff;
--t1:#3f8a57;--t2:#2680c7;--t3:#26cbd8;--t4:#43b895;--t5:#0f6688;--t6:#a5c94a;--t7:#1eaae4;--other:#8b9a9f;
--neg:#c8503f;--neu:#b3bfc1;--pos:#3f8a57;--on-neg:#ffffff;--on-neu:#12303a;--on-pos:#ffffff;
--ramp:#2680c7;--on-ramp:#ffffff;--dim:.28;
font-family:'Jost',sans-serif;font-size:16px;line-height:1.55;font-weight:400;font-variant-numeric:tabular-nums;color:var(--ink);background:var(--bg);box-sizing:border-box}
.v.dark{--bg:#0c191e;--surface:#12262d;--ink:#e3efee;--muted:#9fb5b8;--line:#25434b;--accent:#5cc8e6;--on-accent:#0c191e;
--neg:#e2705f;--neu:#5b767c;--pos:#5fb37a;--on-neg:#0c191e;--on-neu:#e3efee;--on-pos:#0c191e;--ramp:#5cc8e6;--on-ramp:#0c191e}
.v *{box-sizing:border-box}
.v svg{display:block;overflow:visible}
.v svg text{font-family:'Jost',sans-serif;font-variant-numeric:tabular-nums}
"""

def page(title, w, h, dark, body):
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost:wght@300;400;500;600&amp;display=swap">
<style>{CSS}</style>
</helmet>
<div class="v{' dark' if dark else ''}" style="width:{w}px;height:{h}px;position:relative;">
{body}
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":{w},"height":{h}}}}}'>
class Component extends DCLogic {{
  renderVals() {{ return {{}}; }}
}}
</script>
</body>
</html>
'''

# ---------- design constants and data accessors ----------
# Text colour to print on top of each theme colour token (design, not sample data).
TH_ON = {"t1": "#ffffff", "t2": "#ffffff", "t3": "#12303a", "t4": "#12303a", "t5": "#ffffff",
         "t6": "#12303a", "t7": "#12303a", "other": "#12303a"}
DIM = 0.28  # opacity of unselected themes

# Font sizes aligned to frontend/src/report.css's own scale (the surrounding report page's real text),
# not independently invented per chart - see docs/DECISIONS.md's fluid-charts entry. FS_HDR_TITLE matches
# .rp-standout-title (20px/600) exactly; FS_BODY matches CLAUDE.md's stated "Body 16px/1.55" and
# .rp-summary exactly; the rest sit deliberately between report.css's own existing sizes.
FS_HDR_TITLE = 20
FS_HDR_SUB = 14
FS_BODY = 16
FS_LABEL = 14
FS_LABEL_SM = 13
FS_NUMBER_LG = 32

def rows(data):
    return [(t.name, t.share, t.sentiment, t.count, t.color) for t in data.themes]

def treemap_rows(data):
    """Like rows(data), but every entry with col == "other" is merged into one - so treemap_html never
    draws more than 8 boxes (7 real + 1 merged Other) regardless of how many real themes exist
    upstream (see _theme_color's rank-7+ fallback in app/findings.py). Used ONLY by treemap_html - rows()
    itself, and every other chart that reads data.themes, keep seeing every real theme individually;
    this merge is a treemap-drawing concern, not a data concern."""
    base = rows(data)  # [(name, share, sent, cnt, col), ...]
    others = [r for r in base if r[4] == "other"]
    if len(others) <= 1:
        return base
    real_other = next((r for r in others if r[0] == "Other"), None)  # the genuine noise bucket, if present
    share = round(sum(r[1] for r in others), 1)
    cnt = sum(r[3] for r in others)
    sent = round(sum(r[2] * r[3] for r in others) / cnt, 3) if cnt else 0.0
    name = real_other[0] if real_other else "Other"
    merged = (name, share, sent, cnt, "other")
    return [r for r in base if r[4] != "other"] + [merged]

def subs_of(data, name):
    for t in data.themes:
        if t.name == name:
            return [(c.name, c.share) for c in t.children]
    return []

def bub_of(data):
    return {t.name: t.map_xy for t in data.themes if t.map_xy is not None}

def tones_of(data):
    return {t.name: tuple(t.tones) for t in data.themes}

def tone(s, overall):
    d = s - overall
    if abs(d) < 0.03:
        return "var(--neu)"
    t = min(1, (abs(d) - 0.03) / 0.07)
    p = 45 + 55 * t
    base = "var(--neg)" if d < 0 else "var(--pos)"
    return f"color-mix(in srgb,{base} {p:.0f}%,var(--neu))"

def T(x, y, s, size=14, w=400, fill="var(--ink)", anchor="start", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" dominant-baseline="central" '
            f'style="font-size:{size}px;font-weight:{w};fill:{fill}"{extra}>{esc(s)}</text>')

def hdr(title, sub=None):
    s = f'<div style="font-size:{FS_HDR_TITLE}px;font-weight:600;line-height:1.3">{esc(title)}</div>'
    if sub:
        s += f'<div style="font-size:{FS_HDR_SUB}px;color:var(--muted);margin-top:2px">{esc(sub)}</div>'
    return s

def seg(items, selected, hover=None, small=False):
    fs = 14 if small else 15
    out = f'<div style="display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--surface)">'
    for i, it in enumerate(items):
        if it == selected:
            st = "background:var(--accent);color:var(--on-accent);font-weight:600;"
        elif it == hover:
            st = "background:var(--bg);color:var(--ink);font-weight:500;"
        else:
            st = "color:var(--muted);font-weight:500;"
        bl = "border-left:1px solid var(--line);" if i else ""
        out += f'<div style="padding:8px {14 if small else 18}px;font-size:{fs}px;{bl}{st}">{esc(it)}</div>'
    return out + "</div>"

# ---------- sunburst ----------
def polar(cx, cy, r, a):
    t = math.radians(a)
    return cx + r * math.sin(t), cy - r * math.cos(t)

def wedge(cx, cy, r0, r1, a0, a1):
    x0, y0 = polar(cx, cy, r1, a0); x1, y1 = polar(cx, cy, r1, a1)
    x2, y2 = polar(cx, cy, r0, a1); x3, y3 = polar(cx, cy, r0, a0)
    lg = 1 if a1 - a0 > 180 else 0
    return (f"M{x0:.2f} {y0:.2f}A{r1:.2f} {r1:.2f} 0 {lg} 1 {x1:.2f} {y1:.2f}"
            f"L{x2:.2f} {y2:.2f}A{r0:.2f} {r0:.2f} 0 {lg} 0 {x3:.2f} {y3:.2f}Z")

def arc_label(cx, cy, rm, thick, a0, a1, name, pct, fs, color, W, H, opacity=1):
    """The "does this label fit its wedge" decision below is computed entirely in SVG-coordinate-space
    (cx/cy/rm/thick/a0/a1 are all fixed design-time numbers, not real rendered pixels) - genuinely making
    the chart's WIDTH fluid via viewBox+width:100% doesn't change that space at all, so unlike
    treemap_html's old wrap()/fit_label() (which needed a real target pixel box that no longer exists
    once width became fluid), this fit logic still applies unchanged. Only the OUTPUT changes: a sibling
    HTML label (see chart_label()) instead of an SVG <g><text> group, since SVG text scales with its
    viewBox and this chart's whole point is that labels stay a literal, fixed font-size."""
    mid = (a0 + a1) / 2
    arc = rm * math.radians(a1 - a0)
    lh = fs * 1.2
    wpc = fs * 0.53
    if len(pct) * wpc + 6 > arc:
        return ""
    lines = []
    if name:
        words = name.split()
        maxw = arc - 8
        if max(len(w) for w in words) * wpc <= maxw:
            cur = ""
            for w in words:
                t = (cur + " " + w).strip()
                if len(t) * wpc <= maxw:
                    cur = t
                else:
                    lines.append(cur); cur = w
            lines.append(cur)
            if (len(lines) + 1) * lh > thick - 6:
                lines = []
    n_name = len(lines)
    all_lines = lines + [pct]
    x, y = polar(cx, cy, rm, mid)
    rot = mid if not (90 < mid < 270) else mid + 180
    parts = "".join(
        f'<div style="font-weight:{500 if i < n_name else (600 if n_name else 500)}">{esc(t)}</div>'
        for i, t in enumerate(all_lines))
    op = f"opacity:{opacity};" if opacity != 1 else ""
    return (f'<div style="position:absolute;left:{x / W * 100:.3f}%;top:{y / H * 100:.3f}%;'
            f'transform:translate(-50%,-50%) rotate({rot:.1f}deg);font-size:{fs}px;color:{color};{op}'
            f'text-align:center;line-height:{lh:.1f}px;white-space:nowrap">{parts}</div>')

def sunburst(data, W, H, cx, cy, R, fs_in, fs_out, selected=None, hover=None, external=True, cfs=34, csub=15):
    """Wedge shapes (genuine polar/arc geometry - the one case in this app that truly can't be plain CSS
    boxes) stay in a shapes-only SVG, scaled as one proportional unit via viewBox+width:100% (with
    preserveAspectRatio="none" so a fixed-height/fluid-width container stretches it correctly - matching
    every other rewritten chart's choice). Every label (arc_label()'s in-ring labels, external callout
    text, the center count) is a sibling HTML div instead, positioned by % + rotate - see arc_label()'s
    and chart_label()'s own docstrings for why SVG <text>/<foreignObject> can't be used here at all. The
    connector line/circle for an external callout stay in the SVG (pure geometry); only its text moves
    out. See docs/DECISIONS.md's fluid-charts entry."""
    hole, r1, r2 = 0.36 * R, 0.68 * R, 0.70 * R
    shapes = [f'<svg width="100%" height="100%" viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
              'style="display:block" role="img" aria-label="Two-ring sunburst: themes inside, sub-themes outside">']
    labels = []
    a = 0.0
    ext = []
    for name, share, sent, cnt, col in rows(data):
        span = share * 3.6
        a0, a1 = a, a + span
        a = a1
        op = 1 if selected in (None, name) else DIM
        g = [f'<g style="opacity:{op}">']
        g.append(f'<path d="{wedge(cx, cy, hole, r1, a0, a1)}" style="fill:var(--{col});stroke:var(--surface);stroke-width:3"/>')
        if external and span < 30:
            ext.append((name, share, cnt, col, (a0 + a1) / 2))
        else:
            labels.append(arc_label(cx, cy, (hole + r1) / 2, r1 - hole, a0, a1, name, f"{share}%", fs_in, TH_ON[col], W, H, op))
        aa = a0
        for k, (sn, sp) in enumerate(subs_of(data, name)):
            sspan = sp * 3.6
            mixp = [46, 36, 27][k]
            g.append(f'<path d="{wedge(cx, cy, r2, R, aa, aa + sspan)}" style="fill:color-mix(in srgb,var(--{col}) {mixp}%,var(--surface));stroke:var(--surface);stroke-width:2.5"/>')
            labels.append(arc_label(cx, cy, (r2 + R) / 2, R - r2, aa, aa + sspan, sn, f"{sp:g}%", fs_out, "var(--ink)", W, H, op))
            aa += sspan
        if hover == name:
            g.append(f'<path d="{wedge(cx, cy, hole, R, a0, a1)}" style="fill:none;stroke:var(--ink);stroke-width:2.5"/>')
        g.append("</g>")
        shapes.append("".join(g))
    # external callouts for small themes (desktop)
    if external:
        pos = {t.name: t.callout for t in data.themes if t.callout}
        notes = {t.name: t.note for t in data.themes}
        for name, share, cnt, col, mid in ext:
            op = 1 if selected in (None, name) else DIM
            px, py = polar(cx, cy, R + 2, mid)
            if name in pos:
                ex, ey, lines = pos[name]
                lh = 16
                n = len(lines)
                shapes.append(f'<g style="opacity:{op}"><line x1="{ex + 5}" y1="{ey}" x2="{px:.1f}" y2="{py:.1f}" style="stroke:var(--muted);stroke-width:1"/>'
                               f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" style="fill:var(--{col})"/></g>')
                for i, ln in enumerate(lines):
                    dy = (i - (n - 1) / 2) * lh
                    wt = 600 if i == n - 1 and n > 1 else 500
                    labels.append(chart_label(ex, ey + dy, W, H, ln, 14, wt, "var(--ink)", "end", opacity=op))
            else:  # small theme with no hand-placed callout (real data): label on the wedge's own side
                # Used to always go to the right of the wedge (a design for the sample's "Other" slice);
                # a small real theme on the LEFT half then had its label drawn across the ring.
                left = math.sin(math.radians(mid)) < 0
                dx = -1 if left else 1
                room = (px - 40) if left else (W - px - 40)
                lines = wrap(f"{name} {fmt(cnt)} ({share}%)", max(room, 80), 14) or [f"{name} {fmt(cnt)} ({share}%)"]
                if notes.get(name):
                    lines.append(notes[name])
                top = py - 30 - (len(lines) - 1) * 9
                shapes.append(f'<g style="opacity:{op}"><polyline points="{px:.1f},{py:.1f} {px + 14 * dx:.1f},{py - 30:.1f} {px + 26 * dx:.1f},{py - 30:.1f}" style="fill:none;stroke:var(--muted);stroke-width:1"/>'
                               f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" style="fill:var(--{col})"/></g>')
                for i, ln in enumerate(lines):
                    is_note = bool(notes.get(name)) and i == len(lines) - 1
                    labels.append(chart_label(px + 32 * dx, top + i * 18, W, H, ln, 13 if is_note else 14,
                                              400 if is_note else 600, "var(--muted)" if is_note else "var(--ink)",
                                              "end" if left else "start", opacity=op))
    labels.append(chart_label(cx, cy - csub * 0.9, W, H, fmt(data.answered), cfs, 300, "var(--ink)", "middle"))
    labels.append(chart_label(cx, cy + cfs * 0.45, W, H, "answered", csub, 400, "var(--muted)", "middle"))
    shapes.append("</svg>")
    return f'<div style="position:relative;width:100%;height:{H}px">{"".join(shapes)}{"".join(labels)}</div>'

def theme_rows(data, selected=None, hover=None, mobile=False):
    rh = 38 if mobile else 40
    fs = 14 if mobile else 15
    o = [f'<div style="display:flex;align-items:center;gap:10px;height:30px;padding:0 10px;font-size:13px;font-weight:500;color:var(--muted)">'
         f'<span style="width:12px"></span><span style="flex:1">Theme</span><span style="width:{54 if mobile else 64}px;text-align:right">Answers</span><span style="width:{40 if mobile else 44}px;text-align:right">Share</span></div>']
    for name, share, sent, cnt, col in rows(data):
        sel = name == selected
        dim = selected is not None and not sel
        if sel:
            bg = f"background:color-mix(in srgb,var(--{col}) 14%,var(--surface));"
        elif name == hover:
            bg = "background:var(--bg);"
        else:
            bg = ""
        op = 0.4 if dim else 1
        o.append(f'<div style="display:flex;align-items:center;gap:10px;height:{rh}px;padding:0 10px;border-top:1px solid var(--line);border-radius:{6 if sel else 0}px;{bg}opacity:{op}">'
                 f'<span style="width:12px;height:12px;border-radius:3px;background:var(--{col});flex:none"></span>'
                 f'<span style="flex:1;font-size:{fs}px;font-weight:{600 if sel else 400};line-height:1.2">{esc(name)}</span>'
                 f'<span style="width:{54 if mobile else 64}px;text-align:right;font-size:{fs}px">{fmt(cnt)}</span>'
                 f'<span style="width:{40 if mobile else 44}px;text-align:right;font-size:{fs}px;color:var(--muted)">{share}%</span></div>')
        if sel:
            for k, (sn, sp) in enumerate(subs_of(data, name)):
                mixp = [46, 36, 27][k]
                o.append(f'<div style="display:flex;align-items:center;gap:10px;height:34px;padding:0 10px 0 30px;font-size:{fs - 1}px">'
                         f'<span style="width:10px;height:10px;border-radius:2px;background:color-mix(in srgb,var(--{col}) {mixp + 20}%,var(--surface));flex:none"></span>'
                         f'<span style="flex:1;line-height:1.2">{esc(sn)}</span>'
                         f'<span style="width:{54 if mobile else 64}px;text-align:right">{fmt(round(sp / 100 * data.answered))}</span>'
                         f'<span style="width:{40 if mobile else 44}px;text-align:right;color:var(--muted)">{sp:g}%</span></div>')
    return "".join(o)

def _sunburst_panel(data, cap, selected, hover):
    caption = f'<div style="font-size:14px;font-weight:500;color:var(--muted);margin:0 0 10px">{esc(cap)}</div>' if cap is not None else ""
    return (caption +
            f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:24px;display:flex;gap:24px;height:630px">'
            f'<div style="flex:none">{sunburst(data, 640, 580, 380, 300, 245, 14, 12.5, selected, hover)}</div>'
            f'<div style="flex:1;min-width:0">{theme_rows(data, selected, hover)}</div></div>')

def f_sunburst(data: ReportData):
    # Design-gallery frame: deliberately shows two interaction states side by side. Report pages use
    # sunburst_report below instead, which draws the one real state.
    body = (f'<div style="padding:56px 48px">{hdr("What are the themes?", data.question)}'
            f'<div style="height:24px"></div>'
            + _sunburst_panel(data, f"Default, hover on {data.hover_theme}", None, data.hover_theme)
            + '<div style="height:40px"></div>'
            + _sunburst_panel(data, f"{data.selected_theme} selected, others dimmed", data.selected_theme, None) + "</div>")
    return body, 1180, 1640

def sunburst_report(data: ReportData, selected: str | None = None):
    """One-panel sunburst for a real report: `selected` is outlined and the rest dimmed (a finding's own
    theme), or nothing is dimmed when `selected` is None (the overview's theme tab)."""
    cap = f"{selected} selected, others dimmed" if selected else None
    body = (f'<div style="padding:56px 48px">{hdr("What are the themes?", data.question)}'
            f'<div style="height:24px"></div>' + _sunburst_panel(data, cap, selected, None) + "</div>")
    return body, 1180, 900 if cap else 870

def f_sunburst_m(data: ReportData):
    ot = next((t for t in data.themes if t.color == "other"), None)
    other_line = esc(f"{ot.name} {fmt(ot.count)} ({ot.share}%). {ot.note}.") if ot else ""
    body = (f'<div style="padding:24px 16px">{hdr("What are the themes?")}'
            f'<div style="height:16px"></div>'
            f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:12px 0 0">'
            f'{sunburst(data, 358, 340, 179, 172, 150, 11, 10.5, None, None, False, 24, 12)}'
            f'<div style="padding:0 16px 12px">{theme_rows(data, None, None, True)}'
            f'<div style="margin-top:14px;font-size:13px;color:var(--muted);line-height:1.4">{other_line}</div></div></div></div>')
    return body, 390, 960

# ---------- overview ----------
# Height/width of the treemap embedded as this block's own hero chart, below. Sized to the same content
# width every other frame's own inner SVG uses (1084px = this frame's own 1180px minus its 56px/48px
# padding - see f_treemap/f_diverge/etc.), so it lines up with the stat strip and "What stands out" list
# beneath it rather than picking a new, one-off width. Height is shorter than f_treemap's own standalone
# 580px: here the treemap is a lead-in to the stats below, not the whole block, and 7 themes plus "Other"
# still read clearly at this height (verified against tests/golden/overview.html).
OVERVIEW_TREEMAP_W = 1084
OVERVIEW_TREEMAP_H = 320


def f_overview(data: ReportData, report: bool = False):
    stats = data.overview.stats
    if report:
        # The report always draws the treemap on desktop (BUG-044: the icicle's rotated, mid-word-broken
        # labels read worse than a treemap whose small boxes drop to their % or to no label). Its phone
        # layout is report_medium's icicle variant. `report=True` also adds the Other block's pointer to
        # Inside Other below it and names a block that holds folded real themes (BUG-043).
        chart = treemap_html(data, OVERVIEW_TREEMAP_W, OVERVIEW_TREEMAP_H, other_hint=True, report=True)
    # Same decision function as f_treemap (see _prefers_icicle's own docstring), but called with THIS
    # chart's own, smaller reference size - this hero chart can legitimately need icicle even when the
    # taller standalone "What are the themes?" chart below still has enough room for treemap.
    elif _prefers_icicle(data, OVERVIEW_TREEMAP_W, OVERVIEW_TREEMAP_H):
        chart = icicle_html(data, OVERVIEW_TREEMAP_W, OVERVIEW_TREEMAP_H)
    else:
        chart = treemap_html(data, OVERVIEW_TREEMAP_W, OVERVIEW_TREEMAP_H)
    if report:
        # The report page has its own title, summary and context lines, so its overview is only the
        # treemap under one question; every stat below is already printed elsewhere on that page.
        head = hdr("What are the themes?", "Block area is share of answered. Sub-themes sit inside their theme.")
        return f'<div style="padding:56px 48px">{head}<div style="height:24px"></div>{chart}</div>', 1180, OVERVIEW_TREEMAP_H + 200
    st = '<div style="display:flex;margin-top:36px">'
    for i, (l, n, note) in enumerate(stats):
        bd = "border-left:1px solid var(--line);padding-left:24px;" if i else ""
        st += (f'<div style="flex:1;{bd}padding-right:16px"><div style="font-size:14px;font-weight:500;color:var(--muted)">{esc(l)}</div>'
               f'<div style="font-size:54px;font-weight:300;line-height:1.15;margin:4px 0 6px">{esc(n)}</div>'
               f'<div style="font-size:14px;color:var(--muted);line-height:1.4;min-height:40px">{esc(note)}</div></div>')
    st += "</div>"
    sent = data.overview.insights
    # The report page (app/findings.py's build_report_data) always pairs this chart with its own real,
    # Claude-written "What stands out" list built from actual findings, so it clears data.overview.insights
    # to keep this chart's own baked-in copy from duplicating that heading right above it. Standalone
    # callers (the EV sample page, /api/charts/overview) still pass real insights, so this stays unchanged
    # for them: the heading only disappears when there is genuinely nothing to show under it.
    ws = "".join(f'<div style="padding:20px 0;border-top:1px solid var(--line);font-size:24px;font-weight:300;line-height:1.35">{esc(s)}</div>' for s in sent)
    standout = (f'<div style="margin-top:56px;font-size:22px;font-weight:600;margin-bottom:12px">What stands out</div>'
                f'<div style="border-bottom:1px solid var(--line);max-width:960px">{ws}</div>') if sent else ""
    body = (f'<div style="padding:56px 48px">{hdr("How big, how clean, what's notable".replace("what's","what\'s"), data.question)}'
            f'<div style="height:24px"></div>{chart}'
            f'{st}{standout}</div>')
    return body, 1180, 680 + OVERVIEW_TREEMAP_H + 24

# ---------- rank ----------
# The Themes / Sub-themes switch (BUG-055: it used to be only a drawing). "Sub-themes" shows each theme's
# sub-themes right under that theme. Chart fragments are injected HTML and cannot run scripts, so each
# switch label wraps a hidden radio and `:has()` rules on the chart root do the rest. Fixed class names:
# every copy of the chart on a page wants the same rules, and `:has()` scopes them to their own root.
RANK_CSS = ("<style>.vb-rank-switch label{color:var(--muted);font-weight:500}"
            ".vb-rank-switch label>input{position:absolute;opacity:0;width:1px;height:1px;margin:0}"
            ".vb-rank-switch label:has(input:checked){background:var(--accent);color:var(--on-accent);font-weight:600}"
            ".vb-rank-switch label:has(input:focus-visible){outline:2px solid var(--ink);outline-offset:-3px}"
            ".vb-rank-sub{display:none}.vb-rank:has(input[value=sub]:checked) .vb-rank-sub{display:block}</style>")
# Wider than other charts' name columns: sub-theme names sit indented under their theme's.
RANK_NAME_COL = "clamp(180px,22%,300px)"
RANK_SUB_TIP = "Sub-themes have no tone of their own yet."

def rank_rows(data, mobile=False, selected=None, hover=None):
    o = ""
    # Every theme can have a zero share at once - e.g. the Filters feature (SPEC.md section 5) narrowed to
    # a combination that matches zero rows. `mx = 1` makes every bar's width compute to 0 instead of
    # dividing by zero; a visually empty set of bars, not a crash.
    mx = max((t.share for t in data.themes), default=0) or 1
    for t in data.themes:
        name, share, sent, cnt = t.name, t.share, t.sentiment, t.count
        kids = t.children
        sel = name == selected
        op = DIM if (selected and not sel) else 1
        bg = "background:var(--surface);" if (name == hover or sel) else ""
        ring = "outline:2px solid var(--ink);outline-offset:-2px;" if sel else ""
        if mobile:
            bw = share / mx * 236
            row = (f'<div style="padding:10px 12px;border-radius:8px;{bg}{ring}opacity:{op}">'
                   f'<div style="display:flex;justify-content:space-between;font-size:15px;font-weight:500"><span>{esc(name)}</span>'
                   f'<span style="font-weight:400;color:var(--muted)">{sent:+.2f}</span></div>'
                   f'<div style="display:flex;align-items:center;gap:10px;margin-top:6px"><div style="width:{bw:.0f}px;height:22px;border-radius:3px;background:{tone(sent, data.overall_sentiment)};flex:none"></div>'
                   f'<div style="line-height:1.15"><div style="font-size:16px;font-weight:600">{share}%</div><div style="font-size:12px;color:var(--muted)">{fmt(cnt)}</div></div></div></div>')
            subs = "".join(
                f'<div style="padding:6px 12px 6px 32px;opacity:{op}"><div style="font-size:14px">{esc(c.name)}</div>'
                f'<div style="display:flex;align-items:center;gap:10px;margin-top:4px"><div style="width:{c.share / mx * 236:.0f}px;height:14px;border-radius:3px;background:var(--neu);flex:none"></div>'
                f'<div style="font-size:14px;font-weight:600">{c.share}%</div></div></div>' for c in kids)
        else:
            pct = share / mx * 100
            # Bar width is a % of its own flex:1 wrapper (not a px number computed against a fixed
            # design width) so the bar genuinely lengthens as the row itself widens - the two side
            # columns use flex-basis: clamp() rather than a bare px so they get a little breathing
            # room on a wide screen without ever shrinking below a readable minimum. Font sizes are
            # untouched literal px - only the layout reflows, matching docs/DECISIONS.md's fluid-charts
            # entry.
            row = (f'<div style="display:flex;align-items:center;min-height:64px;padding:6px 16px;box-sizing:border-box;border-radius:8px;{bg}{ring}opacity:{op}">'
                   f'<div style="flex:0 0 {RANK_NAME_COL};font-size:17px;font-weight:500">{esc(name)}</div>'
                   f'<div style="flex:1;display:flex;align-items:center;gap:14px">'
                   f'<div style="flex:1;min-width:0"><div style="width:{pct:.1f}%;height:28px;border-radius:3px;background:{tone(sent, data.overall_sentiment)}"></div></div>'
                   f'<div style="line-height:1.2;flex:none"><div style="font-size:18px;font-weight:600">{share}%</div><div style="font-size:13px;color:var(--muted)">{fmt(cnt)}</div></div></div>'
                   f'<div style="flex:0 0 clamp(70px,8%,110px);text-align:right;font-size:17px">{sent:+.2f}</div></div>')
            # Same three columns as the theme row so the bars share one scale and one left edge.
            subs = "".join(
                f'<div style="display:flex;align-items:center;min-height:44px;padding:0 16px;opacity:{op}">'
                f'<div style="flex:0 0 {RANK_NAME_COL};padding:4px 12px 4px 22px;box-sizing:border-box;font-size:15px;line-height:1.25;color:var(--ink)">{esc(c.name)}</div>'
                f'<div style="flex:1;display:flex;align-items:center;gap:14px">'
                f'<div style="flex:1;min-width:0"><div style="width:{c.share / mx * 100:.1f}%;height:16px;border-radius:3px;background:var(--neu)"></div></div>'
                f'<div style="flex:none;font-size:16px;font-weight:600">{c.share}%</div></div>'
                f'<div title="{RANK_SUB_TIP}" style="flex:0 0 clamp(70px,8%,110px);text-align:right;color:var(--muted)">&mdash;</div></div>' for c in kids)
        o += row + (f'<div class="vb-rank-sub" style="padding:2px 0 10px">{subs}</div>' if kids else "")
    return o

def rank_legend():
    def sw(c, t):
        return (f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:22px;font-size:14px;color:var(--muted)">'
                f'<span style="width:16px;height:16px;border-radius:3px;background:{c}"></span>{t}</span>')
    return (sw("var(--neg)", "More negative than average") + sw("var(--neu)", "About average") + sw("var(--pos)", "Milder than average"))

def rank_switch(data, small=False):
    """The Themes / Sub-themes switch, or "" when no theme has sub-themes (nothing to switch to)."""
    if not any(t.children for t in data.themes):
        return ""
    # Radio group name from the chart's content, so two different rank charts on a page don't share one.
    key = repr([data.selected_theme] + [(t.name, t.share, [c.name for c in t.children]) for t in data.themes]).encode()
    group = f"vbrk{zlib.crc32(key):08x}{'m' if small else ''}"
    btn = f'padding:8px {14 if small else 18}px;font-size:{14 if small else 15}px;cursor:pointer;user-select:none'
    return (f'<div class="vb-rank-switch" role="radiogroup" aria-label="Show" style="position:relative;display:inline-flex;flex:none;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--surface)">'
            f'<label style="{btn}"><input type="radio" name="{group}" value="themes" checked>Themes</label>'
            f'<label style="{btn};border-left:1px solid var(--line)"><input type="radio" name="{group}" value="sub">Sub-themes</label></div>')

def f_rank(data: ReportData):
    body = (f'<div class="vb-rank" style="padding:56px 48px">{RANK_CSS}<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">'
            f'<div>{hdr("What should we fix first?", f"Bar length is share of answered. Tint compares each theme with the overall average ({data.overall_sentiment:.2f}).")}</div>'
            f'{rank_switch(data)}</div>'
            f'<div style="margin-top:22px;display:flex;flex-wrap:wrap">{rank_legend()}</div>'
            f'<div style="display:flex;padding:22px 16px 8px;font-size:13px;font-weight:500;color:var(--muted)"><div style="flex:0 0 {RANK_NAME_COL}">Theme</div><div style="flex:1">Share of answered, with count</div><div style="flex:0 0 clamp(70px,8%,110px);text-align:right">Avg sentiment</div></div>'
            f'{rank_rows(data, False, None, data.selected_theme)}</div>')
    return body, 1180, 860

def f_rank_m(data: ReportData):
    switch = rank_switch(data, True)
    if switch:
        switch = f'<div style="margin-top:14px">{switch}</div>'
    body = (f'<div class="vb-rank" style="padding:24px 16px">{RANK_CSS}{hdr("What should we fix first?")}{switch}'
            f'<div style="margin-top:14px;display:flex;flex-wrap:wrap;row-gap:6px">{rank_legend()}</div>'
            f'<div style="margin-top:12px;font-size:13px;color:var(--muted)">{esc(data.selected_theme)} selected, others dimmed</div>'
            f'<div style="margin-top:6px">{rank_rows(data, True, data.selected_theme)}</div></div>')
    return body, 390, 960

# ---------- other-growth (docs/TODO.md, 2026-10-23 - "Look inside Other"'s own result-chart tabs) ----------
def f_other_growth(data: ReportData):
    """A full-width-track horizontal bar per theme, label above the bar rather than centered inside it -
    deliberately NOT `f_rank`'s own layout (same underlying `ReportData.themes` shape, reused as-is, but
    this app id is ONLY ever used for "Look inside Other"'s own newly-discovered-themes result tabs, never
    the main report, so it earns a visually distinct convention matching the mockup's own "sankey-style"
    reveal list rather than literally reusing f_rank's chart for a second purpose). Built from real, final
    per-theme share/count only - no live-growing animation (this job never reports partial progress mid-
    run, so there is nothing honest to animate - see app/api_themes.py's own docstring on why)."""
    rws = rows(data)
    rh, gap, y0 = 48, 20, 8
    total_h = y0 + len(rws) * (rh + gap)
    o = [f'<svg width="100%" viewBox="0 0 1180 {total_h}" style="display:block" role="img" aria-label="New themes found, ranked by share">']
    for i, (name, share, sent, cnt, col) in enumerate(rws):
        y = y0 + i * (rh + gap)
        o.append(T(0, y - 14, name, 15, 600))
        o.append(f'<rect x="0" y="{y}" width="1180" height="{rh}" rx="6" style="fill:var(--line);opacity:.4"/>')
        w = max(6.0, 1180 * min(1.0, share / 100))
        o.append(f'<rect x="0" y="{y}" width="{w:.1f}" height="{rh}" rx="6" style="fill:var(--{col})"/>')
        o.append(T(14, y + rh / 2, f"{share:g}%  {fmt(cnt)} answers", 14, 600, "var(--on-accent)" if w > 140 else "var(--ink)"))
    o.append("</svg>")
    body = f'<div style="padding:56px 48px">{hdr("New themes found inside Other", "Share of all Other answers each new theme now accounts for.")}<div style="margin-top:22px">{"".join(o)}</div></div>'
    return body, 1180, total_h + 56

# ---------- diverge ----------
def f_diverge(data: ReportData):
    DIV = [(t.name, *t.tones) for t in data.themes]
    cx = 600; rh = 60; y0 = 64
    # Scale to the room actually free on each side of the centre line (names end ~250, the
    # "negative / positive" column starts ~930). A fixed 5.2px per point pushed a 72%-positive bar
    # into that column.
    reach = max([max(ng + nu / 2, ps + nu / 2) for _, ng, nu, ps in DIV] or [1]) or 1
    s = min(5.2, 320 / reach)
    o = [f'<svg width="1084" height="{y0 + rh * len(DIV) + 10}" viewBox="0 0 1084 {y0 + rh * len(DIV) + 10}" role="img" aria-label="Diverging sentiment bars">']
    o.append(T(cx - 160, 20, "Negative", 14, 500, "var(--muted)", "end"))
    o.append(T(cx, 20, "Neutral", 14, 500, "var(--muted)", "middle"))
    o.append(T(cx + 160, 20, "Positive", 14, 500, "var(--muted)", "start"))
    o.append(T(1084, 20, "negative / positive", 14, 500, "var(--muted)", "end"))
    for i, (name, ng, nu, ps) in enumerate(DIV):
        y = y0 + i * rh
        if name == data.selected_theme:
            o.append(f'<rect x="-12" y="{y}" width="1108" height="{rh}" rx="8" style="fill:var(--surface)"/>')
        cy = y + rh / 2
        o.append(T(0, cy, name, 16, 500))
        hn = nu * s / 2
        o.append(f'<rect x="{cx - hn - ng * s:.1f}" y="{cy - 16}" width="{ng * s:.1f}" height="32" rx="3" style="fill:var(--neg)"/>')
        o.append(f'<rect x="{cx - hn:.1f}" y="{cy - 16}" width="{nu * s:.1f}" height="32" style="fill:var(--neu)"/>')
        o.append(f'<rect x="{cx + hn:.1f}" y="{cy - 16}" width="{ps * s:.1f}" height="32" rx="3" style="fill:var(--pos)"/>')
        # In-bar labels only where the segment can hold them; the right-hand column always prints both.
        if ng * s >= 40:
            o.append(T(cx - hn - ng * s / 2, cy, f"{ng}%", 14, 600, "var(--on-neg)", "middle"))
        if nu * s >= 26:  # neutral is not repeated on the right, so keep it down to a narrower width
            o.append(T(cx, cy, f"{nu}%", 14 if nu * s >= 40 else 11, 500, "var(--on-neu)", "middle"))
        if ps * s >= 40:
            o.append(T(cx + hn + ps * s / 2, cy, f"{ps}%", 14, 600, "var(--on-pos)", "middle"))
        o.append(T(1084, cy, f"{ng}% / {ps}%", 16, 600, "var(--ink)", "end"))
    o.append(f'<line x1="{cx}" y1="{y0 - 4}" x2="{cx}" y2="{y0 + rh * len(DIV)}" style="stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3"/>')
    o.append("</svg>")
    body = (f'<div style="padding:56px 48px">{hdr("Which themes sound negative or positive?", "Share of each theme\'s answers with negative, neutral and positive wording.")}'
            f'<div style="height:24px"></div>{"".join(o)}</div>')
    return body, 1180, 780

# ---------- bubbles ----------
def f_bubbles(data: ReportData):
    bub = bub_of(data)
    px0, pw, py0, ph = 60, 960, 40, 520
    o = ['<svg width="1084" height="620" viewBox="0 0 1084 620" role="img" aria-label="Theme similarity map">']
    hov = None
    for name, share, sent, cnt, col in rows(data):
        if name not in bub:
            continue
        x = px0 + bub[name][0] * pw
        y = py0 + bub[name][1] * ph
        r = 12.5 * math.sqrt(share)
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" style="fill:var(--{col});stroke:var(--bg);stroke-width:2"/>')
        o.append(T(x, y + r + 16, name, 14, 500, "var(--ink)", "middle"))
        o.append(T(x, y + r + 34, f"{share}%", 14, 400, "var(--muted)", "middle"))
        if name == data.hover_theme:
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 6:.1f}" style="fill:none;stroke:var(--ink);stroke-width:2"/>')
            tx, ty = x + r + 12, y - 62
            o.append(f'<rect x="{tx - 100:.1f}" y="{ty - 28:.1f}" width="200" height="52" rx="8" style="fill:var(--ink)"/>')
            o.append(T(tx, ty - 10, name, 14, 600, "var(--bg)", "middle"))
            o.append(T(tx, ty + 10, f"{share}% of answered, {sent:.2f}", 13, 400, "var(--bg)", "middle"))
    o.append("</svg>")
    body = (f'<div style="padding:56px 48px">{hdr("How do themes relate?", "Circle area is share. Distance means similar wording.")}'
            f'<div style="height:16px"></div>{"".join(o)}</div>')
    return body, 1180, 800

# ---------- byScore ----------
def key_row(data):
    o = '<div style="display:flex;flex-wrap:wrap;gap:8px 24px">'
    for name, share, sent, cnt, col in rows(data):
        o += (f'<span style="display:inline-flex;align-items:center;gap:8px;font-size:14px">'
              f'<span style="width:12px;height:12px;border-radius:3px;background:var(--{col})"></span>{esc(name)}</span>')
    return o + "</div>"

def f_byscore(data: ReportData):
    BYS = [(b.label, b.mix, b.sentiment, b.answers) for b in data.score.bands]
    rows_html = ""
    css_rules = ""
    for ri, (lab, vals, sent, n) in enumerate(BYS):
        segs = ""
        small = []
        for i, v in enumerate(vals):
            col = data.themes[i].color
            name = data.themes[i].name
            txt = f"{v}%"
            if 0 < v < 5:
                # Too thin to hold a readable label: print it under the bar instead (colour is never the
                # only carrier of a value), rather than a clipped "3.1" inside a sliver.
                small.append(f"{esc(name)} {v}%")
                segs += (f'<div title="{esc(name)} {v}%" style="flex:0 0 {v}%;background:var(--{col});'
                         f'border-right:2px solid var(--bg)"></div>')
                continue
            # The bar's own row is now fluid (width:100% below), so a segment's real rendered width can
            # no longer be decided server-side against an assumed 700px reference - both label variants
            # are always emitted, and a CSS container query (container-type:inline-size on the segment
            # itself) picks which is visible at the segment's real final width. Font sizes stay literal
            # px, driven by the data value v, never by width. See docs/DECISIONS.md's fluid-charts entry.
            cls = f"bysc{ri}_{i}"
            needed = round(len(name) * 7.6 + 16)
            full = f'<div class="{cls}f" style="font-size:13px;font-weight:500;line-height:1.2">{esc(name)}</div><div class="{cls}f" style="font-size:16px;font-weight:600;line-height:1.2">{txt}</div>'
            short = f'<div class="{cls}s" style="font-size:{15 if v >= 5 else 11}px;font-weight:600">{txt}</div>'
            css_rules += (f'.{cls}f{{display:none}}'
                           f'@container (min-width:{needed}px){{.{cls}f{{display:block}}.{cls}s{{display:none}}}}')
            segs += (f'<div class="{cls}" style="container-type:inline-size;flex:0 0 {v}%;background:var(--{col});color:{TH_ON[col]};border-right:2px solid var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden">{full}{short}</div>')
        # Tint by the sentiment's own sign (tone colours only ever show sentiment): it used to be --neg
        # for every value, so clearly positive groups (+0.50) showed as red.
        pp = min(55, abs(sent) / 0.2 * 55)
        tone = "--pos" if sent >= 0.05 else "--neg" if sent <= -0.05 else "--neu"
        note = (f'<div style="font-size:13px;color:var(--muted);margin-top:6px">Under 5%: {", ".join(small)}</div>'
                if small else "")
        rows_html += (f'<div style="display:flex;align-items:center;padding:20px 0;border-top:1px solid var(--line)">'
                 f'<div style="width:200px;flex:none"><div style="font-size:18px;font-weight:600">{lab}</div><div style="font-size:14px;color:var(--muted)">{fmt(n)} answers</div></div>'
                 f'<div style="flex:1;min-width:0"><div style="height:66px;display:flex;border-radius:6px;overflow:hidden">{segs}</div>{note}</div>'
                 f'<div style="margin-left:32px;display:inline-flex;align-items:baseline;gap:8px;padding:6px 16px;border:1px solid var(--line);border-radius:999px;background:color-mix(in srgb,var({tone}) {pp:.0f}%,var(--surface))">'
                 f'<span style="font-size:13px;color:var(--ink)">avg sentiment</span><span style="font-size:17px;font-weight:600">{sent:+.2f}</span></div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What does each score group talk about?", f"Theme mix by {data.score.name}. Each bar adds to 100%.")}'
            f'<style>{css_rules}</style>'
            f'<div style="height:24px"></div><div style="border-bottom:1px solid var(--line)">{rows_html}</div>'
            f'<div style="margin-top:24px">{key_row(data)}</div></div>')
    return body, 1180, 660

# ---------- heatmap ----------
def ramp_mix(v, overall):
    if overall == 0:
        # A row's overall share can be genuinely 0 under the Filters feature (SPEC.md section 5) - a
        # theme with zero rows in the current filtered view (`v` is then necessarily 0 too, same cause).
        # `build_segment_data` already skips a zero-overall row for its OWN highlight-ratio math (same
        # reason, see its docstring); this is the matching guard for this cell's colour-ramp math - the
        # same flat "no particular skew" floor `r <= 1` already returns at `r == 0`, not a crash.
        return 8
    r = v / overall
    if r <= 1:
        return 8 + 22 * r
    return 30 + 60 * min(1, (r - 1) / 1.5)

def f_heatmap(data: ReportData):
    seg_ = data.segment
    AGES = [(g.label, g.n) for g in seg_.groups]
    HM = [(r.theme, r.overall, r.values) for r in seg_.rows]
    # First column is a range (not a bare px) so it gets a little breathing room on a wide screen without
    # ever shrinking below a readable minimum - cell text/font-size is untouched, only the grid's own
    # column widths reflow. See docs/DECISIONS.md's fluid-charts entry.
    g = f'<div style="display:grid;grid-template-columns:minmax(160px,220px) repeat({len(AGES)},minmax(0,1fr));gap:4px">'
    g += '<div></div>'
    for a, n in AGES:
        g += f'<div style="padding:0 0 8px;text-align:center"><div style="font-size:16px;font-weight:500">{a}</div><div style="font-size:13px;color:var(--muted)">n={fmt(n)}</div></div>'
    for ri, (name, ov, vals) in enumerate(HM):
        g += f'<div style="display:flex;flex-direction:column;justify-content:center;padding-right:12px"><div style="font-size:16px;font-weight:500;line-height:1.25">{esc(name)}</div><div style="font-size:13px;color:var(--muted)">overall {ov}%</div></div>'
        for j, v in enumerate(vals):
            m = ramp_mix(v, ov)
            tc = "var(--on-ramp)" if m >= 55 else "var(--ink)"
            hov = (seg_.highlight == (ri, j))
            ring = "outline:2px solid var(--ink);outline-offset:2px;" if hov else ""
            tip = ""
            if hov:
                tip = ('<div style="position:absolute;left:50%;bottom:calc(100% + 12px);transform:translateX(-72%);width:250px;padding:10px 14px;border-radius:8px;background:var(--ink);color:var(--bg);font-size:14px;line-height:1.35;z-index:3">'
                       + esc(seg_.highlight_text) + '</div>')
            g += (f'<div style="position:relative;height:66px;border-radius:4px;background:color-mix(in srgb,var(--ramp) {m:.0f}%,var(--surface));color:{tc};display:flex;align-items:center;justify-content:center;font-size:19px;font-weight:{600 if m >= 55 else 500};{ring}">{v}%{tip}</div>')
    g += "</div>"
    steps = "".join(f'<span style="width:34px;height:14px;background:color-mix(in srgb,var(--ramp) {m}%,var(--surface));display:inline-block"></span>' for m in (10, 30, 50, 70, 90))
    legend = (f'<div style="margin-top:28px;display:flex;align-items:center;gap:12px;font-size:14px;color:var(--muted)">'
              f'<span>At or below overall share</span><span style="display:inline-flex;gap:2px">{steps}</span><span>Above overall share</span></div>')
    body = (f'<div style="padding:56px 48px">{hdr("Who raises what?", f"Share of each {seg_.name.lower()}'s answers. Darker means above the overall share.")}'
            f'<div style="height:64px"></div>{g}{legend}</div>')
    return body, 1180, 700

# ---------- trend ----------
TREND_W, TREND_H = 1084, 672

def chart_label(x, y, W, H, text, size, w=400, color="var(--ink)", anchor="start", rotate=0, opacity=1):
    """A sibling HTML label positioned as a % of a chart's own design W/H, for a shapes-only SVG (no
    <text> inside it) - an SVG <text> node scales with its ambient viewBox (verified: neither a literal
    px font-size nor <foreignObject> escapes that), so every label in a genuinely width-fluid chart has
    to live outside the SVG entirely to keep a literal, report-matching font-size. `anchor` replicates
    T()'s text-anchor via a CSS transform instead - "middle"/"end" shift the label left by half/all of
    its own rendered width, so it stays anchored to the same (x,y) point `T()` would have centered/
    right-aligned text on; translateY centers vertically the same way dominant-baseline="central" does.
    `rotate` (degrees) replicates a rotated <g> group, applied around the label's own center after it's
    positioned - used by sunburst()'s arc labels, unused (0) by f_trend's."""
    tx = {"start": "0%", "middle": "-50%", "end": "-100%"}[anchor]
    rot = f" rotate({rotate:.1f}deg)" if rotate else ""
    op = f"opacity:{opacity};" if opacity != 1 else ""
    return (f'<div style="position:absolute;left:{x / W * 100:.3f}%;top:{y / H * 100:.3f}%;'
            f'transform:translate({tx},-50%){rot};font-size:{size}px;font-weight:{w};color:{color};{op}'
            f'white-space:nowrap;line-height:1">{esc(text)}</div>')

def trend_label(x, y, text, size, w=400, color="var(--ink)", anchor="start"):
    return chart_label(x, y, TREND_W, TREND_H, text, size, w, color, anchor)

def f_trend(data: ReportData):
    tr = data.trend
    if (len(tr.labels) < 2 or not tr.series or len(tr.sentiment) != len(tr.labels)
            or any(len(s.values) != len(tr.labels) for s in tr.series)):
        return frame("What's rising or fading?", "Not enough eligible periods under the current filters.", "", 240)
    MONTHS = tr.labels
    NP = len(MONTHS)
    S = [(x.theme, x.color, x.values) for x in tr.series]
    sent = tr.sentiment
    x0, x1 = 56, 830
    dx = (x1 - x0) / (NP - 1)
    ty0, ty1 = 34, 394      # 0..40 %
    by0, by1 = 462, 622     # 0 .. -0.20
    def X(i): return x0 + dx * i
    def Y(v): return ty1 - v / 40 * (ty1 - ty0)
    def YS(v): return by0 + (0 - v) / 0.2 * (by1 - by0)
    # Shapes only (gridlines, polylines, dots) - pure coordinate geometry genuinely benefits from scaling
    # as one unit with the container's width (preserveAspectRatio="none" so it stretches horizontally
    # without letterboxing, matching the fixed-height/fluid-width design every other rewritten chart
    # uses). No <text> lives in here - see trend_label()'s docstring for why.
    o = [f'<svg width="100%" height="100%" viewBox="0 0 {TREND_W} {TREND_H}" preserveAspectRatio="none" '
         'style="display:block" role="img" aria-label="Theme share and average sentiment by month">']
    labels = []
    labels.append(trend_label(0, 12, "Share of answers", 15, 600))
    for g in (0, 10, 20, 30, 40):
        o.append(f'<line x1="{x0}" y1="{Y(g):.1f}" x2="{x1}" y2="{Y(g):.1f}" style="stroke:var(--line);stroke-width:1"/>')
        labels.append(trend_label(x0 - 10, Y(g), f"{g}%", 13, 400, "var(--muted)", "end"))
    HV = tr.hover_index
    for name, col, vals in S:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        o.append(f'<polyline points="{pts}" style="fill:none;stroke:var(--{col});stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round"/>')
        o.append(f'<circle cx="{X(NP - 1):.1f}" cy="{Y(vals[-1]):.1f}" r="4" style="fill:var(--{col})"/>')
        labels.append(trend_label(x1 + 16, Y(vals[-1]), f"{name} {vals[-1]:.0f}%", 14, 600, "var(--ink)"))
        o.append(f'<circle cx="{X(0):.1f}" cy="{Y(vals[0]):.1f}" r="4" style="fill:var(--{col})"/>')
        labels.append(trend_label(X(0) + 8, Y(vals[0]) - 12, f"{vals[0]:.0f}%", 13, 500, "var(--muted)"))
    # hover crosshair
    o.append(f'<line x1="{X(HV):.1f}" y1="{ty0 - 6}" x2="{X(HV):.1f}" y2="{by1}" style="stroke:var(--ink);stroke-width:1;stroke-dasharray:3 3"/>')
    for name, col, vals in S:
        o.append(f'<circle cx="{X(HV):.1f}" cy="{Y(vals[HV]):.1f}" r="4.5" style="fill:var(--surface);stroke:var(--{col});stroke-width:2.5"/>')
        labels.append(trend_label(X(HV) + 10, Y(vals[HV]) - 11, f"{vals[HV]:.1f}%", 13, 600, "var(--ink)"))
    # bottom
    labels.append(trend_label(0, by0 - 28, "Average sentiment", 15, 600))
    for g in (0, -0.1, -0.2):
        o.append(f'<line x1="{x0}" y1="{YS(g):.1f}" x2="{x1}" y2="{YS(g):.1f}" style="stroke:var(--line);stroke-width:1"/>')
        labels.append(trend_label(x0 - 10, YS(g), f"{g:.2f}" if g else "0.00", 13, 400, "var(--muted)", "end"))
    pts = " ".join(f"{X(i):.1f},{YS(v):.1f}" for i, v in enumerate(sent))
    o.append(f'<polyline points="{pts}" style="fill:none;stroke:var(--ink);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round"/>')
    o.append(f'<circle cx="{X(0):.1f}" cy="{YS(sent[0]):.1f}" r="4" style="fill:var(--ink)"/>')
    labels.append(trend_label(X(0) + 8, YS(sent[0]) - 14, f"{sent[0]:.2f}", 13, 500, "var(--muted)"))
    o.append(f'<circle cx="{X(NP - 1):.1f}" cy="{YS(sent[-1]):.1f}" r="4" style="fill:var(--ink)"/>')
    labels.append(trend_label(x1 + 16, YS(sent[-1]), f"Average sentiment {sent[-1]:.2f}", 14, 600))
    o.append(f'<circle cx="{X(HV):.1f}" cy="{YS(sent[HV]):.1f}" r="4.5" style="fill:var(--surface);stroke:var(--ink);stroke-width:2.5"/>')
    labels.append(trend_label(X(HV) + 10, YS(sent[HV]) - 12, f"{sent[HV]:.2f}", 13, 600))
    for i, m in enumerate(MONTHS):
        labels.append(trend_label(X(i), by1 + 26, m, 13, 500 if i == HV else 400, "var(--ink)" if i == HV else "var(--muted)", "middle"))
    o.append("</svg>")
    chart = f'<div style="position:relative;width:100%;height:{TREND_H}px">{"".join(o)}{"".join(labels)}</div>'
    body = (f'<div style="padding:56px 48px">{hdr("What's rising or fading?".replace("What's", "What\'s"), tr.note)}'
            f'<div style="height:24px"></div>{chart}</div>')
    return body, 1180, 880

# ---------- themes over time (small multiples) ----------
# The report's always-on "over time" section whenever the column has a date (T1, 2026-10-25). One small
# panel per theme on ONE shared scale, so panels compare at a glance and no line crosses another's label;
# f_trend's single combined chart fixes its axes at 0-40% and labels every period, which real data breaks.
PANEL_W, PANEL_H = 300, 96


def _panel_scale(top: float) -> int:
    """The shared y-axis top: the largest share rounded up to a step of 5 (10 above 30%)."""
    step = 10 if top > 30 else 5
    return max(step, int(math.ceil(top / step) * step))


def f_themes_over_time(data: ReportData):
    tr = data.trend
    if len(tr.labels) < 3 or not tr.series or any(len(s.values) != len(tr.labels) for s in tr.series):
        return frame("How do themes change over time?", "Not enough answers in enough periods to show a change.", "", 240)
    n = len(tr.labels)
    top = _panel_scale(max(v for s in tr.series for v in s.values))
    counts = tr.counts if len(tr.counts) == n else [None] * n

    def X(i):
        return 6 + i * (PANEL_W - 12) / (n - 1)

    def Y(v):
        return PANEL_H - 4 - v / top * (PANEL_H - 10)

    panels = ""
    for s in tr.series:
        pts = [(X(i), Y(v)) for i, v in enumerate(s.values)]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = f"{pts[0][0]:.1f},{PANEL_H - 4} {line} {pts[-1][0]:.1f},{PANEL_H - 4}"
        dots = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" style="fill:var(--{s.color})">'
            f'<title>{esc(tr.labels[i])}: {s.values[i]}%' + (f" of {fmt(counts[i])} answers" if counts[i] else "") + "</title></circle>"
            for i, (x, y) in enumerate(pts))
        first, last = s.values[0], s.values[-1]
        change = round(last - first, 1)
        arrow = "&#8599;" if change >= 1 else "&#8600;" if change <= -1 else "&#8594;"
        panels += (
            f'<div style="min-width:0" data-theme="{esc(s.theme)}">'
            # Two lines for every name, so the panels' charts line up row by row.
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;height:42px">'
            f'<div title="{esc(s.theme)}" style="font-size:16px;font-weight:600;line-height:1.3;min-width:0;'
            f'overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">{esc(s.theme)}</div>'
            f'<div style="flex:none;font-size:15px;font-variant-numeric:tabular-nums;white-space:nowrap">'
            f'{first:g}% <span aria-hidden="true">{arrow}</span> <strong>{last:g}%</strong></div></div>'
            f'<svg width="100%" height="{PANEL_H}" viewBox="0 0 {PANEL_W} {PANEL_H}" preserveAspectRatio="none" '
            f'style="display:block;margin-top:8px;overflow:visible" role="img" '
            f'aria-label="{esc(s.theme)}: {first:g}% in {esc(tr.labels[0])}, {last:g}% in {esc(tr.labels[-1])}">'
            f'<line x1="0" y1="{PANEL_H - 4}" x2="{PANEL_W}" y2="{PANEL_H - 4}" style="stroke:var(--line);stroke-width:1"/>'
            f'<polygon points="{area}" style="fill:color-mix(in srgb,var(--{s.color}) 16%,transparent)"/>'
            f'<polyline points="{line}" style="fill:none;stroke:var(--{s.color});stroke-width:2.5;stroke-linejoin:round" vector-effect="non-scaling-stroke"/>'
            f'{dots}</svg>'
            f'<div style="display:flex;justify-content:space-between;margin-top:6px;font-size:13px;color:var(--muted)">'
            f'<span>{esc(tr.labels[0])}</span><span>{esc(tr.labels[-1])}</span></div></div>')
    rows = math.ceil(len(tr.series) / 3)
    span = (f" {fmt(min(c for c in counts if c))} to {fmt(max(c for c in counts if c))} answers per period."
            if any(counts) else "")
    # The periods actually drawn: `tr.note` names the whole date range, including periods left out below.
    every = tr.note.split(",")[0] if "," in tr.note else "Per period"
    sub = (f"{every}, {tr.labels[0]} to {tr.labels[-1]}. Each panel is one theme's share of answers per period, "
           f"all on the same 0-{top}% scale."
           f"{span} Periods with under 30 answers are left out.")
    inner = (f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:32px 40px">'
             f'{panels}</div>')
    return frame("How do themes change over time?", sub, inner, 200 + rows * 170)


# ---------- scores by theme (P1) ----------
def f_theme_scores(data: ReportData):
    """Themes down the side, score/number columns across: each cell is the theme's mean minus everyone
    else's. Only differences that passed the test in `build_theme_score_data` are tinted (accent, darker
    for a bigger gap within that column) and carry an up/down mark; the rest print plain and muted. Not
    tone colours: a column like Age or a helpful-vote count is not sentiment."""
    ts = data.theme_scores
    if ts is None or not ts.columns:
        return frame("How do scores differ by theme?", "No score or number column to compare themes on.", "", 240)
    gaps = [max((abs(r[j]) for r in ts.diffs if r[j] is not None), default=0) or 1 for j in range(len(ts.columns))]
    head = ('<th style="text-align:left;padding:0 12px 10px 0"></th>' + "".join(
        f'<th style="padding:0 8px 10px;font-size:13px;font-weight:500;color:var(--muted);text-align:center;'
        f'vertical-align:bottom;min-width:76px;max-width:120px;overflow-wrap:anywhere">{esc(c.replace("_", " "))}'
        f'<div style="font-weight:400;margin-top:2px">avg {ts.overall[j]:.{ts.decimals[j]}f}</div></th>'
        for j, c in enumerate(ts.columns)))
    body = ""
    for i, name in enumerate(ts.themes):
        cells = ""
        for j, d in enumerate(ts.diffs[i]):
            if d is None:
                cells += '<td style="padding:6px 8px;text-align:center;color:var(--muted)" title="Too few answers with a value">&ndash;</td>'
                continue
            num = f"{d:+.{ts.decimals[j]}f}"
            if ts.notable[i][j]:
                mix = 18 + round(42 * abs(d) / gaps[j])
                mark = "&#9650;" if d > 0 else "&#9660;"
                cells += (f'<td style="padding:6px 8px;text-align:center;font-weight:600;'
                          f'background:color-mix(in srgb,var(--accent) {mix}%,var(--surface));'
                          f'color:{"var(--on-accent)" if mix >= 45 else "var(--ink)"}" '
                          f'title="{esc(name)}: {num} against everyone else on {esc(ts.columns[j])}, a tested difference">'
                          f'<span aria-hidden="true" style="font-size:10px;margin-right:4px">{mark}</span>{num}</td>')
            else:
                cells += (f'<td style="padding:6px 8px;text-align:center;color:var(--muted)" '
                          f'title="{esc(name)}: {num} on {esc(ts.columns[j])}, within chance">{num}</td>')
        body += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<th scope="row" style="text-align:left;padding:8px 12px 8px 0;font-size:15px;font-weight:500;min-width:180px">'
                 f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px;'
                 f'background:var(--{ts.colors[i]})"></span>{esc(name)}</th>{cells}</tr>')
    table = (f'<div style="overflow-x:auto"><table style="border-collapse:separate;border-spacing:2px;'
             f'font-variant-numeric:tabular-nums;font-size:15px;width:100%">'
             f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
             f'<div style="margin-top:16px;font-size:14px;color:var(--muted);max-width:820px">Tinted: a tested '
             f'difference (5% false-discovery rate, at least a small effect); darker is a bigger gap. '
             f'&#9650; above everyone else, &#9660; below. Plain numbers are within chance.</div>')
    sub = "Each cell is the theme's average minus everyone else's average on that column."
    return frame("How do scores differ by theme?", sub, table, 240 + 44 * len(ts.themes))


# ---------- freq ----------
def f_freq(data: ReportData):
    fq = data.frequency
    OCC = [(i.label, i.pct, i.merged) for i in fq.items]
    if not OCC:
        # Same empty-sequence guard f_phrases needed (chart-block stream, 2026-10-24) - this crashed on
        # max() of an empty list for any report with no real short_text column (every report until this
        # stream, and still most real reports, which have no second short-answer column at all).
        body = (f'<div style="padding:56px 48px">{hdr("What did people say most?", "")}'
                '<div style="height:20px"></div><div style="color:var(--muted);max-width:640px">'
                "No short-answer column produced a real ranked list for this report.</div></div>")
        return body, 1180, 220
    mx = max(p for _, p, _ in OCC)
    rows_html = ""
    for i, (n, p, merged) in enumerate(OCC):
        bw = p / mx * 560
        cnt = round(p / 100 * fq.answered)
        note = f'<span style="font-size:13px;color:var(--muted);margin-left:16px">{merged} spellings merged</span>' if merged else ""
        bg = "background:var(--surface);" if n == fq.highlight else ""
        rows_html += (f'<div style="display:flex;align-items:center;height:52px;padding:0 16px;border-radius:8px;{bg}">'
                 f'<div style="width:220px;font-size:17px;font-weight:500;flex:none">{esc(n)}</div>'
                 f'<div style="flex:1;display:flex;align-items:center;gap:14px"><div style="width:{bw:.0f}px;height:26px;border-radius:3px;background:var(--accent)"></div>'
                 f'<div style="line-height:1.2"><span style="font-size:17px;font-weight:600">{p}%</span> <span style="font-size:13px;color:var(--muted);margin-left:6px">{fmt(cnt)}</span>{note}</div></div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What did people say most?", f"{fq.question} {fmt(fq.answered)} answered.")}'
            f'<div style="height:20px"></div>{rows_html}'
            f'<div style="margin-top:28px;padding-top:20px;border-top:1px solid var(--line);font-size:16px;color:var(--muted);max-width:820px">{esc(fq.footnote)}</div></div>')
    return body, 1180, 860

# ---------- phrases ----------
def ph_tint(s):
    if s < -0.03:
        p = 12 + min(1, abs(s) / 0.25) * 40
        return f"color-mix(in srgb,var(--neg) {p:.0f}%,var(--surface))"
    if s > 0.03:
        p = 12 + min(1, s / 0.12) * 40
        return f"color-mix(in srgb,var(--pos) {p:.0f}%,var(--surface))"
    return "color-mix(in srgb,var(--neu) 30%,var(--surface))"

def f_phrases(data: ReportData):
    PH = [(p.text, p.count, p.sentiment) for p in data.phrases.phrases]
    if not PH:
        # Found wiring this up for real (chart-block stream, 2026-10-24): this crashed on `max()` of an
        # empty sequence whenever a report has no answer text to extract phrases from (every ReportData
        # built without `answer_texts`, plus any real report too small/varied for a phrase to recur) -
        # never caught before because this chart was never registered in FRAMES, so nothing but the demo
        # EV sample (always non-empty) ever called it. Same "nothing real to show, say so honestly"
        # discipline as the Arc tab's own excluded-chart message - never an empty or fake chart.
        body = (f'<div style="padding:56px 48px">{hdr("Which phrases recur?", "Chip size is how often a phrase appears. Each chip shows its count and average sentiment.")}'
                '<div style="height:28px"></div><div style="color:var(--muted);max-width:640px">'
                "No phrase came up often enough, across enough different answers, to call it recurring.</div></div>")
        return body, 1180, 280
    mx = max(c for _, c, _ in PH)
    chips = ""
    for p, c, s in PH:
        fs = 15 + c / mx * 19
        ring = "border:2px solid var(--ink);" if p == data.phrases.highlight else "border:1px solid var(--line);"
        chips += (f'<div style="display:inline-flex;align-items:baseline;gap:10px;padding:{8 + fs * 0.12:.0f}px {14 + fs * 0.35:.0f}px;border-radius:999px;background:{ph_tint(s)};{ring}">'
                  f'<span style="font-size:{fs:.0f}px;font-weight:500;line-height:1.2">{esc(p)}</span>'
                  f'<span style="font-size:13px;color:var(--muted)">{fmt(c)}</span><span style="font-size:13px;color:var(--muted)">{s:+.2f}</span></div>')
    def sw(c, t):
        return (f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:22px;font-size:14px;color:var(--muted)">'
                f'<span style="width:22px;height:14px;border-radius:999px;border:1px solid var(--line);background:{c}"></span>{t}</span>')
    leg = (sw(ph_tint(-0.25), "Negative wording, -0.25") + sw(ph_tint(-0.12), "Mildly negative") + sw(ph_tint(0), "About neutral") + sw(ph_tint(0.10), "Positive wording, +0.10"))
    body = (f'<div style="padding:56px 48px">{hdr("Which phrases recur?", "Chip size is how often a phrase appears. Each chip shows its count and average sentiment.")}'
            f'<div style="height:28px"></div><div style="display:flex;flex-wrap:wrap;gap:16px 14px;align-items:center;max-width:1000px">{chips}</div>'
            f'<div style="margin-top:36px;display:flex;flex-wrap:wrap;row-gap:8px">{leg}</div></div>')
    return body, 1180, 640

# ---------- quotes ----------
SC = {"negative": "var(--neg)", "neutral": "var(--neu)", "positive": "var(--pos)"}

def f_quotes(data: ReportData):
    Q = [(q.text, q.theme, q.tone) for q in data.quotes.quotes]
    tcol = {t.name: t.color for t in data.themes}
    hi = data.quotes.highlight_index
    chips = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:20px">'
    for name in ["All"] + [t.name for t in data.themes if t.name != "Other"]:
        if name == "All":
            st = "background:var(--accent);color:var(--on-accent);border:1px solid var(--accent);font-weight:600;"
            dot = ""
        else:
            hv = "background:var(--surface);" if name == data.selected_theme else ""
            st = f"border:1px solid var(--line);{hv}font-weight:500;"
            dot = f'<span style="width:9px;height:9px;border-radius:50%;background:var(--{tcol[name]})"></span>'
        chips += f'<span style="display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;font-size:14px;{st}">{dot}{esc(name)}</span>'
    chips += "</div>"
    rows = ""
    for i, (q, th, sn) in enumerate(Q):
        bg = "background:var(--surface);" if i == hi else ""
        rows += (f'<div style="display:flex;align-items:center;gap:20px;min-height:62px;padding:8px 16px;border-top:1px solid var(--line);border-radius:{8 if i == hi else 0}px;{bg}">'
                 f'<div style="width:100px;flex:none;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)"><span style="width:11px;height:11px;border-radius:50%;background:{SC[sn]}"></span>{sn}</div>'
                 f'<div style="flex:1;font-size:19px;line-height:1.4">{esc(q)}</div>'
                 f'<div style="width:230px;flex:none;text-align:right;font-size:14px;font-weight:500;color:var(--muted)">{esc(th)}</div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What does it sound like?", "Verbatim answers, with their theme and tone.")}'
            f'<div style="margin-top:22px">{seg(["Most typical", "Random", "Most negative", "Most positive"], "Most typical", "Random")}</div>'
            f'{chips}<div style="height:24px"></div><div style="border-bottom:1px solid var(--line)">{rows}</div></div>')
    return body, 1180, 800

# ---------- quality ----------
def f_quality(data: ReportData):
    # Was an SVG histogram at a fixed pixel width; bars are simple axis-aligned rects with no curved
    # geometry, so there's no reason to keep SVG here (unlike sentsun's genuine polar shapes) - a CSS
    # flex "bar chart" lets each bar's own column genuinely reflow with the available width, the same
    # pattern proven by byScore. Only the track HEIGHT stays a fixed px reference (270px) - the ask was
    # for width to reflow, not height - and every font-size stays a literal px, driven by the data value,
    # never by width. See docs/DECISIONS.md's fluid-charts entry.
    q = data.quality
    BINS = q.bins
    mx = max(c for _, c in BINS)
    track_h = 270
    bars = ""
    labels = ""
    for lab, c in BINS:
        h = c / mx * 100
        typ = lab == q.typical_bin
        fill = "var(--accent)" if typ else "color-mix(in srgb,var(--accent) 55%,var(--bg))"
        note = (f'<div style="font-size:14px;font-weight:500;color:var(--accent);text-align:center;margin-bottom:6px;white-space:nowrap">{esc(q.typical_note)}</div>'
                if typ else "")
        bars += (f'<div style="flex:1;display:flex;flex-direction:column;align-items:center">'
                 f'{note}'
                 f'<div style="font-size:15px;font-weight:600;color:var(--ink);margin-bottom:6px">{fmt(c)}</div>'
                 f'<div style="width:100%;max-width:100px;height:{track_h}px;display:flex;align-items:flex-end">'
                 f'<div style="width:100%;height:{h:.1f}%;border-radius:3px 3px 0 0;background:{fill}"></div></div>'
                 f'</div>')
        labels += f'<div style="flex:1;text-align:center;font-size:15px;font-weight:500;color:var(--ink)">{esc(lab)}</div>'
    chart = (f'<div style="display:flex;align-items:flex-end;gap:20px;border-bottom:1px solid var(--ink)">{bars}</div>'
             f'<div style="display:flex;gap:20px;margin-top:22px">{labels}</div>'
             f'<div style="margin-top:22px;text-align:center;font-size:14px;font-weight:500;color:var(--muted)">Words per answer</div>')
    notes = q.notes
    nt = '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:40px;margin-top:20px">' + "".join(
        f'<div style="border-top:1px solid var(--line);padding-top:14px;font-size:16px;line-height:1.55">{esc(n)}</div>' for n in notes) + "</div>"
    body = (f'<div style="padding:56px 48px">{hdr("Can I trust this?", f"Answer length in words, for the {fmt(data.answered)} answers analysed.")}'
            f'<div style="height:40px"></div>{chart}{nt}</div>')
    return body, 1180, 880

# ---------- context ----------
def f_context(data: ReportData):
    cx = data.context
    opts = cx.kind_options
    menu = ('<span style="position:absolute;left:-14px;top:calc(100% + 12px);width:270px;padding:6px;background:var(--surface);border:1px solid var(--line);border-radius:12px;z-index:5;'
            'font-size:18px;font-weight:400;line-height:1.3;display:block;text-align:left">')
    for o_ in opts:
        if o_ == cx.kind:
            st = "background:color-mix(in srgb,var(--accent) 14%,var(--surface));color:var(--accent);font-weight:600;"
        elif o_ == cx.kind_hover:
            st = "background:var(--bg);"
        else:
            st = ""
        menu += f'<span style="display:block;padding:10px 14px;border-radius:8px;{st}">{o_}</span>'
    menu += "</span>"
    ctl = "color:var(--accent);border-bottom:2px dotted var(--accent);"
    body = (f'<div style="padding:72px 80px">'
            f'<div style="font-size:48px;font-weight:300;line-height:1.25;max-width:1020px">This question asks for '
            f'<span style="position:relative;display:inline-block;{ctl}">{esc(cx.kind)}{menu}</span>, framed '
            f'<span style="{ctl}">{esc(cx.framing)}</span>, and answers run '
            f'<span style="{ctl}">{esc(cx.length)}</span>.</div>'
            f'<div style="margin-top:340px;font-size:19px;line-height:1.55;max-width:820px;color:var(--ink)">{fmt(data.answered)} of {fmt(data.total)} responses had an answer to analyse. {esc(cx.columns_note)}</div>'
            f'<details style="margin-top:36px;max-width:820px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)">'
            f'<summary style="display:flex;justify-content:space-between;align-items:center;padding:16px 0;font-size:18px;font-weight:500;list-style:none;cursor:pointer">How the charts were chosen<span style="font-size:24px;font-weight:300;color:var(--muted)">+</span></summary></details></div>')
    return body, 1180, 760

# ---------- tokens ----------
def f_tokens(data: ReportData):  # static design reference, ignores data
    def sw(c):
        return f'<span style="display:inline-block;width:26px;height:26px;border-radius:6px;border:1px solid var(--line);background:{c};vertical-align:middle"></span>'
    def row(tok, l, d, use):
        dd = f'{sw(d)} <span style="color:var(--muted)">{d}</span>' if d else '<span style="color:var(--muted)">same</span>'
        return (f'<div style="display:grid;grid-template-columns:150px 170px 170px 1fr;align-items:center;padding:7px 0;border-top:1px solid var(--line);font-size:14px">'
                f'<span style="font-weight:600">{tok}</span><span>{sw(l)} <span style="color:var(--muted)">{l}</span></span><span>{dd}</span><span style="color:var(--muted)">{use}</span></div>')
    def head(t):
        return (f'<div style="margin-top:28px;display:grid;grid-template-columns:150px 170px 170px 1fr;font-size:13px;font-weight:500;color:var(--muted);padding-bottom:6px"><span style="font-size:16px;font-weight:600;color:var(--ink)">{t}</span><span>Light</span><span>Dark</span><span>Use</span></div>')
    r = head("Surface and ink")
    r += row("--bg", "#f2f7f6", "#0c191e", "Page ground")
    r += row("--surface", "#ffffff", "#12262d", "Primary chart panel, hover rows, segment gaps")
    r += row("--ink", "#12303a", "#e3efee", "Text, selected outline")
    r += row("--muted", "#546b71", "#9fb5b8", "Captions, axis labels")
    r += row("--line", "#d3e0df", "#25434b", "Hairlines, gridlines")
    r += row("--accent", "#0f6688", "#5cc8e6", "Controls, single-colour bars")
    r += row("--on-accent", "#ffffff", "#0c191e", "Text on accent")
    r += head("Themes, only to identify themes")
    for i, c in enumerate(["#3f8a57", "#2680c7", "#26cbd8", "#43b895", "#0f6688", "#a5c94a", "#1eaae4"], 1):
        r += row(f"--t{i}", c, None, ["Cost", "Charging", "Range and battery", "Not needed", "Doubts about the technology", "Availability", "Uncertainty"][i - 1])
    r += row("--other", "#8b9a9f", None, "Other")
    r += head("Sentiment, only for tone")
    r += row("--neg", "#c8503f", "#e2705f", "Negative; on-colour --on-neg")
    r += row("--neu", "#b3bfc1", "#5b767c", "Neutral; on-colour --on-neu")
    r += row("--pos", "#3f8a57", "#5fb37a", "Positive; on-colour --on-pos")
    r += row("--ramp", "#2680c7", "#5cc8e6", "Heatmap: color-mix(in srgb, var(--ramp) N%, var(--surface))")
    r += row("--dim", "0.28", "0.28", "Opacity of unselected themes")
    tip = ('<div style="margin-top:28px;font-size:14px;color:var(--muted);line-height:1.5;max-width:900px">Type: Jost only. --font: \'Jost\'. Weights 300 large numbers and headlines, 400 body, 500 labels, 600 titles. Body 16px/1.55 with tabular numbers. '
           'Segment gaps are a 3px stroke of --surface. Tint for rank bars is color-mix(in srgb, var(--neg|--pos) P%, var(--neu)). Every value is also printed as a number.</div>')
    body = f'<div style="padding:56px 48px">{hdr("Design tokens", "CSS variables set on the chart root. Dark values apply under the dark class.")}{r}{tip}</div>'
    return body, 1180, 1160

# ---------- new frames ----------
def Th(x, y, s, size=14, w=400, fill="var(--ink)", anchor="start"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" dominant-baseline="central" '
            f'style="font-size:{size}px;font-weight:{w};fill:{fill};paint-order:stroke;stroke:var(--bg);stroke-width:4px;stroke-linejoin:round">{esc(s)}</text>')

def wrap(name, maxw, fs):
    wpc = fs * 0.53
    words = name.split()
    if max(len(w) for w in words) * wpc > maxw:
        return None
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if len(t) * wpc <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    return lines

def fit_label(x, y, w, h, name, pct, fs, color, rot=True):
    lh = fs * 1.25
    wpc = fs * 0.53
    lines = wrap(name, w - 12, fs) if name else []
    if lines is not None and (len(lines) + 1) * lh <= h - 8:
        n = len(lines) + 1
        ty = y + h / 2 - n * lh / 2 + lh / 2
        out = ""
        for i, t in enumerate(lines + [pct]):
            out += T(x + w / 2, ty + i * lh, t, fs, 500 if i < len(lines) else 600, color, "middle")
        return out
    def rotated(txt):
        return (f'<g transform="translate({x + w / 2:.1f} {y + h / 2:.1f}) rotate(-90)">'
                + T(0, 0, txt, fs, 600, color, "middle") + "</g>")
    if rot and name and len(f"{name} {pct}") * wpc <= h - 8 and lh <= w - 3:
        return rotated(f"{name} {pct}")
    if len(pct) * wpc <= w - 4 and lh <= h:
        return T(x + w / 2, y + h / 2, pct, fs, 600, color, "middle")
    if rot and len(pct) * wpc <= h - 8 and lh <= w - 3:
        return rotated(pct)
    return ""

def squarify(items, x, y, w, h):
    total = sum(v for _, v in items)
    if total <= 0:
        # Every item has a zero (or negative, never expected) share - e.g. the Filters feature (SPEC.md
        # section 5) can legitimately narrow a report down to zero matching rows. Render no boxes at all
        # rather than dividing by zero; `treemap_html`'s own per-cell label logic already handles a rect
        # tuple cleanly, so an empty treemap is just a blank area, not a crash.
        return {}
    scale = w * h / total
    rem = [(k, v * scale) for k, v in items]
    rects = {}
    def worst(row, side):
        s = sum(a for _, a in row)
        return max(side * side * max(a for _, a in row) / (s * s), s * s / (side * side * min(a for _, a in row)))
    while rem:
        side = min(w, h)
        row = [rem[0]]; i = 1
        while i < len(rem) and worst(row + [rem[i]], side) <= worst(row, side):
            row.append(rem[i]); i += 1
        rem = rem[i:]
        s = sum(a for _, a in row)
        if w >= h:
            cw = s / h; yy = y
            for k, a in row:
                hh = a / cw; rects[k] = (x, yy, cw, hh); yy += hh
            x += cw; w -= cw
        else:
            rh = s / w; xx = x
            for k, a in row:
                ww = a / rh; rects[k] = (xx, y, ww, rh); xx += ww
            y += rh; h -= rh
    return rects

MIX = [46, 36, 27]

def frame(title, sub, inner, h, extra_top=24):
    return (f'<div style="padding:56px 48px">{hdr(title, sub)}<div style="height:{extra_top}px"></div>{inner}</div>'), 1180, h

OTHER_MAX_TREEMAP_AREA = 5.0  # see _treemap_areas below


def _treemap_areas(rows_data) -> dict[str, float]:
    """The box AREA each treemap row gets, as opposed to its real reported `share` (still shown verbatim
    in the cell's own label text - this function never changes what number is printed, only how much
    space each box occupies). "Other" is a catch-all bucket (folded-in rank-8+ themes plus genuinely
    unclustered noise, see `app.findings.theme_nodes`'s own merge note) that is frequently the single
    largest real-world row by a wide margin (confirmed live: 25.6% on a real dataset) - every real theme's
    own box, and therefore its label, got squeezed into whatever sliver was left, clipping names/sub-theme
    labels that the viewer actually wants to read. Capping "Other"'s own AREA at `OTHER_MAX_TREEMAP_AREA`
    (5%) once it exceeds that share, and handing the freed area to every other row in proportion to its
    own existing share, fixes exactly that: "Other" still reads its true percentage in its label, it just
    never visually dominates the layout. A dataset where "Other" is already <= 5% is untouched - nothing
    to cap, nothing to redistribute, areas equal real shares exactly as before this fix."""
    other = next((r for r in rows_data if r[4] == "other"), None)
    rest_total = sum(r[1] for r in rows_data if r[4] != "other")
    # Nothing to redistribute the freed area TO (every row is "other") - leave it at its real,
    # uncapped area rather than shrinking the total area represented for no gain.
    others_excess = max(0.0, other[1] - OTHER_MAX_TREEMAP_AREA) if (other and rest_total > 0) else 0.0
    areas: dict[str, float] = {}
    for name, share, _, _, col in rows_data:
        if col == "other":
            areas[name] = share - others_excess
        else:
            areas[name] = share + others_excess * (share / rest_total)
    return areas


# ---- treemap
def treemap_html(data: ReportData, w: int, h: int, other_hint: bool = False, report: bool = False) -> str:
    """The treemap's own markup (no `frame()` wrapper) - `f_treemap` below calls this at its own
    standalone size, and `f_overview` calls it again at a smaller "hero"/browse size, so the layout logic
    itself exists in exactly one place rather than being copy-pasted per caller.

    `w`/`h` are the design's reference size that `squarify()` packs against - not a rendered pixel size
    any more. Every rect it returns is expressed as a `%` of `w`/`h` here, so the whole treemap is a
    `position:relative` box whose HEIGHT stays this design's fixed `h`px (matching every other rewritten
    chart's "width reflows, height doesn't" choice) but whose WIDTH genuinely fills whatever its own
    container gives it - see docs/DECISIONS.md's fluid-charts entry. Each cell's own label always tries
    to show its name (matching the original design prototype's own density - it wraps a name across as
    many lines as fit rather than dropping to a bare percentage early): since HEIGHT never changes with
    viewport width, the number of lines that fit is fully computable server-side from the cell's own
    known height, and `-webkit-line-clamp` is set to exactly that count - WIDTH-wise wrapping is left
    entirely to the browser's own natural text flow, which adapts correctly to whatever width the cell
    renders at with no server-side pixel-width guess needed (`wrap()`/`fit_label()`, used elsewhere by
    the 3 dead chart functions still on the old fixed-pixel SVG design, are not used here any more). A
    cell too short even for one line still gets one attempted line, clipped by `overflow:hidden` rather
    than overflowing into a sibling cell - the same "never overflow" guarantee the old pixel-fit logic
    existed to provide, now enforced structurally by CSS instead of computed per-render.

    Each theme's own box (and any sub-theme boxes nested inside it) carries `data-theme="..."`, so a
    frontend click/hover handler can resolve any part of a theme's drawing - including a sub-theme box -
    back to its parent theme with a single `closest('[data-theme]')` lookup (see
    `frontend/src/ThemeChart.tsx`); `closest()` is DOM-structure-based and does not care that this is now
    a `<div>` tree instead of nested `<svg><g>` groups.

    `report=True` (the report overview only; gallery frames never pass it) swaps every label for one that
    never breaks a word: see `_TreemapLabels`. It also names a merged Other box that holds real themes
    ("113 more themes", BUG-043) and shows its "Look inside" pointer only when it holds unthemed answers."""
    rows_data = treemap_rows(data)
    # squarify's own layout math (`worst()`) divides by each row's smallest item, so a zero-share theme -
    # unreachable before the Filters feature, now a real case: a filter combination can legitimately leave
    # one theme with 0 matching rows while others still have some (SPEC.md section 5) - would still crash
    # it even with the other, non-zero items present. A 0%-share theme draws no box at all; it is simply
    # not in this filtered view, not an error.
    drawable = [r for r in rows_data if r[1] > 0]
    areas = _treemap_areas(drawable)
    rects = squarify([(n, areas[n]) for n, _, _, _, _ in drawable], 0, 0, w, h)
    if not rects:
        # Every theme has a zero share (e.g. a Filters-feature combination that matches zero rows entirely,
        # SPEC.md section 5) - an empty box, not a crash (see squarify's own comment for why `rects` can
        # come back `{}`).
        return f'<div style="position:relative;height:{h}px"></div>'
    labels = _TreemapLabels(drawable) if report else None
    cells = []
    for idx, (name, share, sent, cnt, col) in enumerate(drawable):
        rx, ry, rw, rh = rects[name]
        if labels is not None:
            cells.append(_report_treemap_cell(data, labels, name, share, col, rects[name], w, h, areas, other_hint))
            continue

        sub_html = ""
        header_pct = TREEMAP_HEADER_PCT
        layout = _treemap_sub_layout(data, name, share, rw, rh)
        if layout is not None:
            sub_entries, sub_w, sub_h = layout
            sub_cells = ""
            for k, sn, sp, sx, sy, sw, sh in sub_entries:
                # Line count is computed from this sub-cell's own known height (sh, already in the
                # fixed 580px design-height reference frame the browser actually renders at) rather
                # than capped at a fixed number - see treemap_html's own docstring. Width-wise
                # wrapping is left entirely to the browser's natural text flow.
                s_line_h = 14 * 1.2
                s_max_lines = max(1, int((sh - 4) // s_line_h))
                if sn == "__remainder__":
                    # Muted, never one of MIX's theme-tinted colors, and the label text itself says
                    # what it is - colour is never the only carrier (CLAUDE.md's design rules).
                    bg = "color-mix(in srgb, var(--muted) 18%, var(--surface))"
                    label_text = f"{sp:g}% not in a sub-theme"
                else:
                    bg = f"color-mix(in srgb,var(--{col}) {MIX[k] + 12}%,var(--surface))"
                    label_text = f'{esc(sn)} <span style="font-weight:600">{sp:g}%</span>'
                sub_cells += (
                    f'<div style="position:absolute;left:{sx / sub_w * 100:.2f}%;top:{sy / sub_h * 100:.2f}%;'
                    f'width:{sw / sub_w * 100:.2f}%;height:{sh / sub_h * 100:.2f}%;padding:1.5px">'
                    f'<div style="width:100%;height:100%;border-radius:3px;overflow:hidden;'
                    f'background:{bg};'
                    f'display:flex;align-items:center;justify-content:center;text-align:center;padding:2px">'
                    f'<span lang="en" style="font-size:14px;font-weight:500;color:var(--ink);line-height:1.2;'
                    f'overflow:hidden;overflow-wrap:break-word;hyphens:auto;-webkit-hyphens:auto;display:-webkit-box;'
                    f'-webkit-line-clamp:{s_max_lines};-webkit-box-orient:vertical">'
                    f'{label_text}</span>'
                    f'</div></div>')
            sub_html = f'<div style="position:absolute;left:0;top:{header_pct}%;width:100%;height:{100 - header_pct}%">{sub_cells}</div>'

        # Same height-derived line count as sub-cells above, computed against the header area only
        # (header_pct of rh) when sub-cells actually render - otherwise a tall cell's label could compute
        # more lines than fit before the sub-cells start, visually colliding with them.
        label_h = (rh * header_pct / 100) if sub_html else rh
        # Narrow cells drop to 13px, and long words hyphenate ("compli-ments") instead of being split
        # with no hyphen ("compliment s"), which read as two words.
        fs = 15 if rw >= 110 else 13
        line_h = fs * 1.3
        max_lines = max(1, int((label_h - 12 - 8) // line_h))
        label = (f'<div lang="en" style="font-size:{fs}px;font-weight:500;color:{TH_ON[col]};line-height:1.3;'
                 f'overflow:hidden;overflow-wrap:break-word;hyphens:auto;-webkit-hyphens:auto;display:-webkit-box;'
                 f'-webkit-line-clamp:{max_lines};-webkit-box-orient:vertical">'
                 f'{esc(name)} <span style="font-weight:600">{share}%</span></div>')

        cells.append(
            f'<div data-theme="{esc(name)}" style="position:absolute;left:{rx / w * 100:.2f}%;top:{ry / h * 100:.2f}%;'
            f'width:{rw / w * 100:.2f}%;height:{rh / h * 100:.2f}%;padding:1.5px">'
            f'<div style="width:100%;height:100%;border-radius:5px;overflow:hidden;position:relative;'
            f'background:var(--{col})">'
            f'<div style="position:absolute;left:10px;top:12px;right:8px">{label}</div>'
            f'{sub_html}{_other_hint(name, share, areas, rw, rh) if other_hint and col == "other" else ""}</div></div>')
    style = labels.style() if labels is not None else ""
    return f'<div style="position:relative;width:100%;height:{h}px">{style}{"".join(cells)}</div>'


def _other_hint(name: str, share: float, areas: dict[str, float], rw: float, rh: float) -> str:
    """Report page only (the Inside Other section sits right under the treemap): points the reader at it,
    and says so when the box is drawn smaller than its real share (`_treemap_areas` caps Other's area).
    Skipped in a box too small to hold it, rather than overflowing."""
    if rw < 80 or rh < 64:
        return ""  # below this the box only has room for its own name and share
    capped = areas.get(name, share) < share - 1e-9
    note = ('<div style="font-size:11.5px;font-weight:400;line-height:1.3;margin-top:2px">'
            'Drawn smaller than its real share</div>') if capped and rw >= 120 and rh >= 84 else ""
    return (f'<div style="position:absolute;left:10px;right:8px;bottom:10px;color:{TH_ON["other"]}">'
            f'<div style="font-size:14px;font-weight:600">Look inside ↓</div>{note}</div>')


TREEMAP_HEADER_PCT = 34  # a fixed share of a cell's own height reserved for its label when it has
                         # sub-themes, not a computed "how tall did the label actually render" pixel value
                         # - see treemap_html's own docstring.


def _treemap_sub_layout(data: ReportData, name: str, share: float, rw: float, rh: float):
    """Where a treemap cell's sub-theme boxes go, or None when it draws none: `(entries, sub_w, sub_h)`,
    each entry `(k, name, share, x, y, w, h)` in the sub-area's own reference frame. Shared by the
    gallery and report label paths of `treemap_html`, so both draw identical boxes."""
    subs = subs_of(data, name)
    if not subs:
        return None
    # A theme's stored sub-themes are only required to cover >= MIN_SUBTHEME_COVERAGE (50%) of its own
    # answers (app/text_pipeline/subthemes.py) - deliberate, documented design, not a bug. But squarify()
    # always fills 100% of the reserved sub-area with whatever `subs` it's given, so without this, a theme
    # covered by only half its own answers LOOKS fully covered. A synthetic remainder entry gets real
    # proportional space instead, rendered distinctly (not one of MIX's tints). Skipped when the gap
    # rounds to ~0 - not worth a cell for noise.
    remainder = round(share - sum(sp for _, sp in subs), 1)
    if remainder > 0.5:
        subs = subs + [("__remainder__", remainder)]
    sub_w, sub_h = rw - 10, rh * (100 - TREEMAP_HEADER_PCT) / 100 - 5
    if sub_w <= 20 or sub_h <= 20:
        return None
    sr = squarify(subs, 0, 0, sub_w, sub_h)
    entries = []
    for k, (sn, sp) in enumerate(subs):
        sx, sy, sw, sh = sr[(sn, sp)] if (sn, sp) in sr else sr[sn]
        entries.append((k, sn, sp, sx, sy, sw, sh))
    return entries, sub_w, sub_h


def other_display_name(data: ReportData, name: str = "Other") -> str:
    """The report's name for the merged "Other" box (BUG-043). That box holds unthemed answers plus every
    real theme ranked 8th or lower; calling all of it "Other" contradicted the Inside Other section, which
    only counts the unthemed answers. Plain `name` when no real theme is folded in (or nothing is known)."""
    b = data.other_breakdown
    if b is None or b.hidden_real_theme_count <= 0:
        return name
    n = b.hidden_real_theme_count
    more = f"{n} more theme{'' if n == 1 else 's'}"
    return more if b.hidden_real_share >= b.noise_share else f"Other and {more}"


def other_has_unthemed(data: ReportData) -> bool:
    """Whether the merged Other box holds unthemed answers - the only thing "Look inside" works on.
    Unknown (no breakdown, e.g. a gallery or test fixture) counts as yes, the behaviour before BUG-043."""
    b = data.other_breakdown
    return b is None or b.noise_count > 0


# Visually hidden but read by screen readers: a report treemap box's full name and share, whatever its
# visible label had room for.
SR_ONLY = ("position:absolute;width:1px;height:1px;margin:-1px;padding:0;border:0;overflow:hidden;"
           "clip:rect(0 0 0 0);white-space:nowrap")
WORD_EM = 0.6  # deliberately generous average letter width (in em) for "does this word fit" checks
NUM_EM = 0.58  # the same for a printed share ("50.7%"); tabular digits are close to this
HINT_MIN_W = 118  # container width (px) the one-line "Look inside ↓" needs; below it the hint is just "↓"
ARROW_MIN_W = 18


def _wrapped_line_count(words: list[str], width: float, fs: float) -> int:
    lines, cur = 0, ""
    for word in words:
        line = f"{cur} {word}" if cur else word
        if cur and len(line) * fs * WORD_EM > width:
            lines, cur = lines + 1, word
        else:
            cur = line
    return lines + (1 if cur else 0)


def _min_label_width(text: str, fs: float, max_lines: int) -> float:
    """The narrowest text width (px) at which `text` wraps, at spaces only, into `max_lines` lines or
    fewer - so no word is ever wider than its line. Estimated with `WORD_EM`; never below the longest
    word, never above the whole text on one line."""
    words = text.split()
    full = len(text) * fs * WORD_EM
    width = max(len(word) for word in words) * fs * WORD_EM
    while width < full and _wrapped_line_count(words, width, fs) > max_lines:
        width += 2
    return min(width, full)


class _TreemapLabels:
    """Report-only treemap labels (BUG-044) that never break a word mid-letter at any real width.

    Every box carries up to two visible labels: its full "name share%" (wrapping at spaces only) and a
    share-only fallback. A CSS container query on the box's own rendered width picks one: the full label
    when its longest word and its line count fit, otherwise the share alone, otherwise nothing. The box's
    `title` and a screen-reader-only span always carry the full name. Thresholds come from `WORD_EM`; the
    box's height is fixed, so line counts are computed here exactly as `treemap_html` already does.
    Class names carry a hash of the boxes so two treemaps on one page never share rules."""

    def __init__(self, drawable):
        key = repr([(r[0], r[1]) for r in drawable]).encode()
        self.uid = f"vbtm{zlib.crc32(key):08x}"
        self.n = 0
        self.rules: list[str] = []

    def new_class(self) -> str:
        self.n += 1
        return f"{self.uid}-{self.n}"

    def switch(self, cls: str, full_min: float, pct_min: float) -> None:
        self.rules.append(f"@container (width<{full_min:.0f}px){{.{cls}f{{display:none}}.{cls}p{{display:block}}}}"
                          f"@container (width<{pct_min:.0f}px){{.{cls}p{{display:none}}}}")

    def hint_switch(self, cls: str) -> None:
        self.rules.append(f"@container (width<{HINT_MIN_W}px){{.{cls}h{{display:none}}.{cls}k{{display:block}}}}"
                          f"@container (width<{ARROW_MIN_W}px){{.{cls}k{{display:none}}}}")

    def style(self) -> str:
        return (f"<style>.{self.uid}-p,.{self.uid}-k{{display:none}}{''.join(self.rules)}</style>")


def _report_sub_cell(labels: _TreemapLabels, col: str, k: int, sn: str, sp: float,
                     sx: float, sy: float, sw: float, sh: float, sub_w: float, sub_h: float) -> str:
    if sn == "__remainder__":
        # Muted, never one of MIX's theme-tinted colours, and the label says what it is.
        bg = "color-mix(in srgb, var(--muted) 18%, var(--surface))"
        plain = f"{sp:g}% not in a sub-theme"
        label_html = esc(plain)
    else:
        bg = f"color-mix(in srgb,var(--{col}) {MIX[k] + 12}%,var(--surface))"
        plain = f"{sn} {sp:g}%"
        label_html = f'{esc(sn)} <span style="font-weight:600">{sp:g}%</span>'
    fs, line_h = 14, 14 * 1.2
    max_lines = int((sh - 7) // line_h)  # 1.5px outer and 2px inner padding on each side
    visible = ""
    if max_lines >= 1:
        cls = labels.new_class()
        labels.switch(cls, _min_label_width(plain, fs, max_lines) + 2, len(f"{sp:g}%") * fs * NUM_EM + 2)
        visible = (f'<div class="{cls}f" aria-hidden="true" style="min-width:0">'
                   f'<span lang="en" style="font-size:{fs}px;font-weight:500;color:var(--ink);line-height:1.2;'
                   f'overflow:hidden;overflow-wrap:normal;hyphens:manual;display:-webkit-box;'
                   f'-webkit-line-clamp:{max_lines};-webkit-box-orient:vertical">{label_html}</span></div>'
                   f'<div class="{labels.uid}-p {cls}p" aria-hidden="true" style="font-size:{fs}px;font-weight:600;'
                   f'color:var(--ink);line-height:1.2;white-space:nowrap">{sp:g}%</div>')
    return (f'<div title="{esc(plain)}" style="position:absolute;left:{sx / sub_w * 100:.2f}%;top:{sy / sub_h * 100:.2f}%;'
            f'width:{sw / sub_w * 100:.2f}%;height:{sh / sub_h * 100:.2f}%;padding:1.5px">'
            f'<div style="width:100%;height:100%;border-radius:3px;overflow:hidden;position:relative;'
            f'background:{bg};container-type:inline-size;'
            f'display:flex;align-items:center;justify-content:center;text-align:center;padding:2px">'
            f'<span style="{SR_ONLY}">{esc(plain)}</span>{visible}</div></div>')


def _report_treemap_cell(data: ReportData, labels: _TreemapLabels, name: str, share: float, col: str,
                         rect, w: int, h: int, areas: dict[str, float], other_hint: bool) -> str:
    """One box of the report overview's treemap: same geometry and colours as the gallery path in
    `treemap_html`, with `_TreemapLabels` labels, the BUG-043 name for a merged Other box, and a "Look
    inside" pointer that drops to a bare "↓" in a box too narrow for the words (BUG-036)."""
    rx, ry, rw, rh = rect
    is_other = col == "other"
    display = other_display_name(data, name) if is_other else name
    plain = f"{display} {share}%"

    sub_html = ""
    layout = _treemap_sub_layout(data, name, share, rw, rh)
    if layout is not None:
        sub_entries, sub_w, sub_h = layout
        sub_html = (f'<div style="position:absolute;left:0;top:{TREEMAP_HEADER_PCT}%;width:100%;'
                    f'height:{100 - TREEMAP_HEADER_PCT}%">'
                    + "".join(_report_sub_cell(labels, col, k, sn, sp, sx, sy, sw, sh, sub_w, sub_h)
                              for k, sn, sp, sx, sy, sw, sh in sub_entries)
                    + "</div>")

    label_h = (rh * TREEMAP_HEADER_PCT / 100) if sub_html else rh
    fs = 15 if rw >= 110 else 13
    line_h = fs * 1.3
    max_lines = int((label_h - 12 - 8) // line_h)

    # The pointer to Inside Other, at the box's foot. Only when Other holds unthemed answers (the only
    # thing Look inside works on) and the box is tall enough to keep at least one label line above it.
    hint = ""
    capped = areas.get(name, share) < share - 1e-9
    note_fits = capped and rw >= 120 and rh >= 84

    def lines_above(reserve: float) -> int:  # label lines left above a pointer `reserve` px tall
        return int((label_h - 12 - 4 - reserve) // line_h)

    note_text = "Drawn smaller than its real share"
    # 10px foot margin + the 14px pointer line; the 11.5px note adds its own wrapped lines.
    note_reserve = 29 + 15 * _wrapped_line_count(note_text.split(), rw - 21, 11.5)
    if note_fits and lines_above(note_reserve) < 1:
        note_fits = False  # keep the pointer, drop its "drawn smaller" note
    reserve = note_reserve if note_fits else 27
    if other_hint and is_other and other_has_unthemed(data) and rh >= 64 and lines_above(reserve) >= 1:
        max_lines = lines_above(reserve)
        cls = labels.new_class()
        labels.hint_switch(cls)
        note = ('<div style="font-size:11.5px;font-weight:400;line-height:1.3;margin-top:2px">'
                f'{note_text}</div>') if note_fits else ""
        hint = (f'<div style="position:absolute;left:10px;right:8px;bottom:10px;color:{TH_ON["other"]}">'
                f'<div class="{cls}h"><div style="font-size:14px;font-weight:600;white-space:nowrap">Look inside ↓</div>{note}</div>'
                f'<div class="{labels.uid}-k {cls}k" role="img" aria-label="Look inside Other, below" '
                f'title="Look inside Other, below" style="font-size:16px;font-weight:600;line-height:1">↓</div></div>')

    visible = ""
    if max_lines >= 1:
        cls = labels.new_class()
        labels.switch(cls, _min_label_width(plain, fs, max_lines) + 18, len(f"{share}%") * fs * NUM_EM + 10)
        visible = (f'<div class="{cls}f" aria-hidden="true" style="position:absolute;left:10px;top:12px;right:8px">'
                   f'<div lang="en" style="font-size:{fs}px;font-weight:500;color:{TH_ON[col]};line-height:1.3;'
                   f'overflow:hidden;overflow-wrap:normal;hyphens:manual;display:-webkit-box;'
                   f'-webkit-line-clamp:{max_lines};-webkit-box-orient:vertical">'
                   f'{esc(display)} <span style="font-weight:600">{share}%</span></div></div>'
                   f'<div class="{labels.uid}-p {cls}p" aria-hidden="true" style="position:absolute;left:6px;top:12px;'
                   f'right:4px;font-size:{fs}px;font-weight:600;color:{TH_ON[col]};line-height:1.3;'
                   f'white-space:nowrap">{share}%</div>')

    return (f'<div data-theme="{esc(name)}" title="{esc(plain)}" style="position:absolute;left:{rx / w * 100:.2f}%;'
            f'top:{ry / h * 100:.2f}%;width:{rw / w * 100:.2f}%;height:{rh / h * 100:.2f}%;padding:1.5px">'
            f'<div style="width:100%;height:100%;border-radius:5px;overflow:hidden;position:relative;'
            f'background:var(--{col});container-type:inline-size">'
            f'<span style="{SR_ONLY}">{esc(plain)}</span>{visible}{sub_html}{hint}</div></div>')


def _too_narrow_for(name: str, box_w: float, fs: float = 15) -> bool:
    """Rough, decision-only estimate of whether a box this wide, at the chart's reference width, could
    show even its own first word on one line - used solely to choose between the treemap and icicle
    layouts (`_prefers_icicle` below), never to compute an actual render (the real render always leaves
    width-wise wrapping to the browser's own text flow - see `treemap_html`'s own docstring for why
    precise server-side width wrapping is deliberately avoided there; this is a coarser, one-time estimate
    used only to pick a layout)."""
    if not name or name == "__remainder__":
        return False
    first_word = name.split()[0]
    wpc = fs * 0.53  # same average-character-width convention fit_label() already uses
    chars_per_line = (box_w - 12) / wpc
    return chars_per_line < min(len(first_word), 6)


def _prefers_icicle(data: ReportData, w: int = 1084, h: int = 580) -> bool:
    """True when the treemap's packed-square layout would leave at least one theme or sub-theme box too
    narrow to show even a short fragment of its own name - confirmed live on a real dataset: long theme
    names ("Versatility and style appeal") and several small sub-themes collapsed to single-letter boxes
    ("P...", "B", "U..."). `icicle_html` (below) reads far better in that case, since every box gets the
    chart's full row height and only its WIDTH varies. `treemap_html` stays the default (denser, matches
    the original design) when every name already has enough room.

    Runs the exact same squarify layout `treemap_html` itself would use, purely to make this one yes/no
    decision - draws nothing, cheap pure-Python math, no re-render."""
    rows_data = treemap_rows(data)
    drawable = [r for r in rows_data if r[1] > 0]
    if not drawable:
        return False
    areas = _treemap_areas(drawable)
    rects = squarify([(n, areas[n]) for n, _, _, _, _ in drawable], 0, 0, w, h)
    for name, share, sent, cnt, col in drawable:
        rx, ry, rw, rh = rects[name]
        if _too_narrow_for(name, rw):
            return True
        subs = subs_of(data, name)
        if not subs:
            continue
        sub_w, sub_h = rw - 10, rh * (100 - 34) / 100 - 5
        if sub_w <= 20 or sub_h <= 20:
            return True
        sr = squarify(subs, 0, 0, sub_w, sub_h)
        for sn, sp in subs:
            _, _, sw, sh = sr[(sn, sp)] if (sn, sp) in sr else sr[sn]
            if _too_narrow_for(sn, sw) or sh < 28:
                return True
    return False


def _icicle_cell(label_name: str, share: float, col: str, x: float, y: float, box_w: float, box_h: float,
                  total_w: float, total_h: float, *, theme_name: str, is_sub: bool, mix_k: int = 0) -> str:
    if box_w <= 0 or box_h <= 0:
        return ""
    is_remainder = label_name == "__remainder__"
    fs = 14 if is_sub else 15
    if is_remainder:
        bg = "color-mix(in srgb, var(--muted) 18%, var(--surface))"
        text_color = "var(--ink)"
    elif is_sub:
        bg = f"color-mix(in srgb,var(--{col}) {MIX[mix_k % len(MIX)] + 12}%,var(--surface))"
        text_color = "var(--ink)"
    else:
        bg = f"var(--{col})"
        text_color = TH_ON[col]
    outer_open = (
        f'<div data-theme="{esc(theme_name)}" style="position:absolute;left:{x / total_w * 100:.2f}%;'
        f'top:{y / total_h * 100:.2f}%;width:{box_w / total_w * 100:.2f}%;height:{box_h / total_h * 100:.2f}%;'
        f'padding:1.5px">'
        f'<div style="width:100%;height:100%;border-radius:4px;overflow:hidden;background:{bg};'
        f'position:relative">'
    )

    # A column's HEIGHT is always generous here (the whole point of this layout), but its WIDTH can still
    # be genuinely tiny (a 1%-share theme is ~1% of the chart's width no matter which layout draws it).
    # The reference design (design/screens/icicle.dc.html) rotates a too-narrow label 90° rather than
    # wrapping it horizontally - the icicle-layout analogue of the legacy fixed-pixel fit_label()'s own
    # `rotated()` fallback, rebuilt here as one CSS transform on a single-line span instead of SVG. This
    # shows real text (not just a number) in far less width than horizontal wrapping needs, while still
    # avoiding the worse failure mode a pure line-clamp-by-height approach had: given enough height and no
    # width check at all, a narrow column would spell its whole name one character per line, vertically
    # (confirmed live on a real dataset) - rotation reads as one real line, never that.
    wpc = fs * 0.53
    chars_per_line = (box_w - 12) / wpc
    pct_only = f"{share:g}%"
    full_text_plain = f"{label_name} {pct_only}" if not is_remainder else f"{pct_only} not in a sub-theme"

    if is_remainder:
        body = _icicle_label(f"{share:g}% not in a sub-theme", fs, text_color)
    elif chars_per_line >= 6:
        label_text = (f'{esc(label_name)} <span style="font-weight:600">{pct_only}</span>' if is_sub
                      else f'{esc(label_name)} <span style="font-weight:600">{share}%</span>')
        body = _icicle_label(label_text, fs, text_color)
    elif box_w >= fs * 1.4 + 6 and len(full_text_plain) * wpc <= box_h - 16:
        # Rotated fits: the STRING's length (now running along the box's generous HEIGHT) clears that
        # height, and the box is at least wide enough for one line's own thickness.
        body = _icicle_rotated_label(f"{esc(label_name)} {pct_only}", fs, text_color)
    elif box_w >= fs * 1.4 + 6 and len(pct_only) * wpc <= box_h - 16:
        body = _icicle_rotated_label(pct_only, fs, text_color)
    elif chars_per_line >= len(pct_only):
        body = _icicle_label(pct_only, fs, text_color)
    else:
        # Too narrow even for the bare percentage on one line, rotated or not - no text at all reads
        # better than a character-by-character wrap either way. The box's own size/colour still carries
        # real information; a click still resolves it via `data-theme`.
        body = ""
    return outer_open + body + "</div></div>"


def _icicle_label(label_text: str, fs: float, text_color: str) -> str:
    """Horizontal, wrapped, line-clamped label - the normal case, used whenever a column is wide enough
    that real multi-word wrapping reads better than rotating a single line (see `_icicle_cell`)."""
    line_h = fs * 1.25
    return (
        f'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
        f'text-align:center;padding:6px">'
        f'<span style="font-size:{fs}px;font-weight:500;color:{text_color};line-height:1.25;'
        f'overflow:hidden;overflow-wrap:break-word;display:-webkit-box;'
        # Never more than 6 lines even when height would allow more - 6 lines of a narrow column's own
        # width is already generous; beyond that, line-clamp's own ellipsis is the right degrade, not an
        # ever-taller stack of near-empty lines.
        f'-webkit-line-clamp:6;-webkit-box-orient:vertical">{label_text}</span></div>'
    )


def _icicle_rotated_label(text: str, fs: float, text_color: str) -> str:
    """One-line label rotated -90° (reads bottom-to-top, matching design/screens/icicle.dc.html) for a
    column too narrow for horizontal wrapping but tall enough for the whole line sideways. Callers must
    have already confirmed the real string length fits the box's height - this never wraps or clamps."""
    return (
        f'<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(-90deg);'
        f'transform-origin:center;white-space:nowrap;font-size:{fs}px;font-weight:500;color:{text_color};'
        f'line-height:1.2">{text}</div>'
    )


def icicle_html(data: ReportData, w: int, h: int, other_label: str | None = None) -> str:
    """Row-based alternative to `treemap_html`'s packed squares, chosen per-report by `_prefers_icicle`
    above: every theme gets the chart's FULL row height (only its WIDTH varies, by share), and sub-themes
    sit in a second full-height row directly below their parent theme's own x-span - far more room for a
    long name to wrap than a small packed square gets. Mirrors `treemap_html`'s own fluid conventions
    exactly (CSS %, `-webkit-line-clamp` computed from each box's own known height, `esc()`-escaped
    labels, `data-theme` attributes for click/hover) - this is a new, live-report-quality rendering of the
    layout idea the legacy fixed-pixel `f_icicle` (below) sketched, not a reuse of that dead code.

    "Other"'s box WIDTH is capped the same way `treemap_html`'s box AREA is (`_treemap_areas`, reused
    as-is - width and area are the same thing once every box shares one fixed row height), for the same
    reason: it is frequently the single largest box for reasons unrelated to being the most worth reading.

    `other_label` (report only, see `other_display_name`) replaces the merged Other box's visible name;
    its `data-theme` stays the real name.
    """
    rows_data = treemap_rows(data)
    drawable = [r for r in rows_data if r[1] > 0]
    if not drawable:
        return f'<div style="position:relative;height:{h}px"></div>'
    areas = _treemap_areas(drawable)

    has_subs = any(subs_of(data, name) for name, *_ in drawable)
    if has_subs:
        gap = 8
        theme_row_h = h * 0.58
        sub_row_top = theme_row_h + gap
        sub_row_h = h - sub_row_top
    else:
        theme_row_h = h
        sub_row_top = h
        sub_row_h = 0

    cells = []
    x = 0.0
    for name, share, sent, cnt, col in drawable:
        box_w = areas[name] / 100 * w
        label_name = other_label if (other_label and col == "other") else name
        cells.append(_icicle_cell(label_name, share, col, x, 0.0, box_w, theme_row_h, w, h,
                                   theme_name=name, is_sub=False))

        subs = subs_of(data, name)
        if subs and sub_row_h > 20 and box_w > 20:
            # Same "incomplete sub-theme coverage" synthetic remainder treemap_html's nested sub-layout
            # uses, for the same reason - see that function's own comment.
            remainder = round(share - sum(sp for _, sp in subs), 1)
            sub_entries = subs + ([("__remainder__", remainder)] if remainder > 0.5 else [])
            sub_total = sum(sp for _, sp in sub_entries)
            if sub_total > 0:
                sx = x
                for k, (sn, sp) in enumerate(sub_entries):
                    sub_w = sp / sub_total * box_w
                    cells.append(_icicle_cell(sn, sp, col, sx, sub_row_top, sub_w, sub_row_h, w, h,
                                               theme_name=name, is_sub=True, mix_k=k))
                    sx += sub_w
        x += box_w
    return f'<div style="position:relative;width:100%;height:{h}px">{"".join(cells)}</div>'


def f_treemap(data: ReportData):
    if _prefers_icicle(data, 1084, 580):
        tm = icicle_html(data, 1084, 580)
        return frame("What are the themes?", "Width is share of answered. Sub-themes sit below their theme.", tm, 800)
    tm = treemap_html(data, 1084, 580)
    return frame("What are the themes?", "Block area is share of answered. Sub-themes sit inside their theme.", tm, 800)

# fix: squarify keys must be hashable and unique; sub items are (name, share) tuples keyed by name
def _sub_items(subs):
    return [(sn, sp) for sn, sp in subs]

# ---- icicle
def f_icicle(data: ReportData):
    W = 1084
    o = [f'<svg width="{W}" height="380" viewBox="0 0 {W} 380" role="img" aria-label="Icicle chart: themes above, sub-themes below">']
    o.append(T(0, 8, "Themes", 14, 500, "var(--muted)"))
    y1, h1, y2, h2 = 24, 130, 158, 210
    a = 0.0
    for name, share, sent, cnt, col in rows(data):
        x = a / 100 * W; w = share / 100 * W; a += share
        o.append(f'<rect x="{x + 1.5:.1f}" y="{y1}" width="{w - 3:.1f}" height="{h1}" rx="3" style="fill:var(--{col})"/>')
        o.append(fit_label(x + 1.5, y1, w - 3, h1, name, f"{share}%", 13, TH_ON[col]))
        aa = x
        for k, (sn, sp) in enumerate(subs_of(data, name)):
            sw = sp / 100 * W
            o.append(f'<rect x="{aa + 1.5:.1f}" y="{y2}" width="{sw - 3:.1f}" height="{h2}" rx="3" style="fill:color-mix(in srgb,var(--{col}) {MIX[k] + 12}%,var(--surface))"/>')
            o.append(fit_label(aa + 1.5, y2, sw - 3, h2, sn, f"{sp:g}%", 12.5, "var(--ink)"))
            aa += sw
    o.append(T(0, y2 + h2 + 22, "Sub-themes, as share of all answered. Uncertainty and Other have none.", 14, 400, "var(--muted)"))
    o.append("</svg>")
    return frame("What are the themes?", "Width is share of answered. Read down from a theme to its sub-themes.", "".join(o), 620)

# ---- sentiment sunburst
def f_sentsun(data: ReportData):
    # Same shapes-only-SVG + sibling-HTML-labels split as sunburst()/arc_label() above (this function has
    # its own independent drawing loop - a single ring split by sentiment tone, not sub-themes, so it
    # isn't a candidate for sharing that helper directly) - see arc_label()'s and chart_label()'s
    # docstrings for why. The diagram's own wrapper gets aspect-ratio:1 (it's a circle - W and H are
    # always equal here) and a flexible width bound instead of a literal flex:none 580px, so it can use a
    # little extra space on a wide screen instead of staying pinned to one fixed size; the "answered"
    # count is a real report number (it always reads correctly at any size since it's genuinely centered
    # via % + translate, not computed against a specific rendered pixel size). See docs/DECISIONS.md.
    W = H = 580
    cx = cy = 290
    R = 280
    hole, r1, r2 = 0.34 * R, 0.62 * R, 0.64 * R
    shapes = [f'<svg width="100%" height="100%" viewBox="0 0 {W} {H}" role="img" aria-label="Sentiment sunburst: themes inside, tone split outside">']
    labels = []
    a = 0.0
    tones = tones_of(data)
    for name, share, sent, cnt, col in rows(data):
        span = share * 3.6
        a0, a1 = a, a + span
        a = a1
        # Finding-aware highlight (fixes 2+ tone_contrast findings rendering the byte-identical chart,
        # see docs/DECISIONS.md): `app/api_report.py` passes a per-finding `data.selected_theme` override
        # into this one render call, so the inner wedge for THAT finding's theme gets a bold ink stroke -
        # same "selected theme, others plain" language f_diverge/f_rank already use elsewhere in this file,
        # not a new visual idiom.
        is_sel = name == data.selected_theme
        ring_stroke = "var(--ink)" if is_sel else "var(--surface)"
        ring_width = 4.5 if is_sel else 3
        shapes.append(f'<path d="{wedge(cx, cy, hole, r1, a0, a1)}" style="fill:var(--{col});stroke:{ring_stroke};stroke-width:{ring_width}"/>')
        labels.append(arc_label(cx, cy, (hole + r1) / 2, r1 - hole, a0, a1, name, f"{share}%", 13.5, TH_ON[col], W, H))
        aa = a0
        for v, c, on in zip(tones[name], ("neg", "neu", "pos"), ("var(--on-neg)", "var(--on-neu)", "var(--on-pos)")):
            sp = span * v / 100
            shapes.append(f'<path d="{wedge(cx, cy, r2, R, aa, aa + sp)}" style="fill:var(--{c});stroke:var(--surface);stroke-width:2.5"/>')
            labels.append(arc_label(cx, cy, (r2 + R) / 2, R - r2, aa, aa + sp, None, f"{v}%", 13, on, W, H))
            aa += sp
    labels.append(chart_label(cx, cy - 12, W, H, fmt(data.answered), 32, 300, "var(--ink)", "middle"))
    labels.append(chart_label(cx, cy + 16, W, H, "answered", 15, 400, "var(--muted)", "middle"))
    shapes.append("</svg>")
    diagram = f'<div style="position:relative;width:100%;height:100%">{"".join(shapes)}{"".join(labels)}</div>'
    tbl = ('<div style="flex:1;padding-top:12px"><div style="display:flex;align-items:center;gap:10px;height:30px;font-size:13px;font-weight:500;color:var(--muted)">'
           '<span style="width:12px"></span><span style="flex:1">Theme</span>'
           '<span style="width:72px;text-align:right">Negative</span><span style="width:72px;text-align:right">Neutral</span><span style="width:72px;text-align:right">Positive</span></div>')
    for name, share, sent, cnt, col in rows(data):
        ng, nu, ps = tones[name]
        row_bg = "background:var(--surface);" if name == data.selected_theme else ""
        name_weight = 600 if name == data.selected_theme else 400
        tbl += (f'<div style="display:flex;align-items:center;gap:10px;height:44px;border-top:1px solid var(--line);font-size:15px;{row_bg}">'
                f'<span style="width:12px;height:12px;border-radius:3px;background:var(--{col})"></span><span style="flex:1;line-height:1.2;font-weight:{name_weight}">{esc(name)}</span>'
                f'<span style="width:72px;text-align:right;font-weight:600">{ng}%</span><span style="width:72px;text-align:right">{nu}%</span><span style="width:72px;text-align:right">{ps}%</span></div>')
    def sw(c, t):
        return f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:20px;font-size:14px;color:var(--muted)"><span style="width:14px;height:14px;border-radius:3px;background:{c}"></span>{t}</span>'
    tbl += f'<div style="margin-top:20px">{sw("var(--neg)", "Negative")}{sw("var(--neu)", "Neutral")}{sw("var(--pos)", "Positive")}</div></div>'
    inner = (f'<div style="display:flex;gap:40px;align-items:flex-start">'
             f'<div style="flex:1 1 320px;max-width:{W}px;aspect-ratio:1">{diagram}</div>{tbl}</div>')
    subtitle = "Inner ring is the theme. Outer ring splits each theme by tone."
    if data.selected_theme in {t.name for t in data.themes}:
        subtitle += f" {data.selected_theme} is outlined."
    return frame("Which themes sound negative or positive?", subtitle, inner, 800)

# ---- marimekko
def f_mekko(data: ReportData):
    W = 1084
    gap = 3
    avail = W - gap * (len(data.themes) - 1)
    Hc = 440
    o = [f'<svg width="{W}" height="600" viewBox="0 0 {W} 600" role="img" aria-label="Marimekko: theme width is share, height is tone split">']
    x = 0.0
    tones = tones_of(data)
    for name, share, sent, cnt, col in rows(data):
        w = share / 100 * avail
        ng, nu, ps = tones[name]
        y = Hc
        for v, c, on in ((ng, "neg", "var(--on-neg)"), (nu, "neu", "var(--on-neu)"), (ps, "pos", "var(--on-pos)")):
            h = v / 100 * Hc
            y -= h
            o.append(f'<rect x="{x:.1f}" y="{y + 1:.1f}" width="{w:.1f}" height="{h - 2:.1f}" style="fill:var(--{c})"/>')
            txt = f"{v}%" if w >= 50 else f"{v}"
            o.append(T(x + w / 2, y + h / 2, txt, 15 if w >= 50 else 11.5, 600, on, "middle"))
        o.append(fit_label(x, Hc + 8, w, 120, name, f"{share}%", 14, "var(--ink)", True).replace("rotate(-90)", "rotate(90)") if False else "")
        lines = wrap(name, w - 6, 14)
        ty = Hc + 22
        if lines is not None and len(lines) <= 4:
            for i, t in enumerate(lines + [f"{share}%"]):
                o.append(T(x + w / 2, ty + i * 18, t, 14, 500 if i < len(lines) else 600, "var(--ink)", "middle"))
        else:
            o.append(f'<g transform="translate({x + w / 2:.1f} {Hc + 12}) rotate(90)">{T(0, 0, f"{name} {share}%", 14, 500)}</g>')
        x += w + gap
    o.append("</svg>")
    return frame("Which themes sound negative or positive?", "Column width is share of answered. Column height splits into negative, neutral and positive wording.", "".join(o), 800)

# ---- sankey
def f_sankey(data: ReportData):
    W, H = 1084, max(620, 36 * (len(data.score.bands) - 1) + 180)
    names = [t.name for t in data.themes]
    tcol = [t.color for t in data.themes]
    BYS = [(b.label, b.mix, b.sentiment, b.answers) for b in data.score.bands]
    nb, nt = len(BYS), len(names)
    tones = tones_of(data)
    L = []
    for lab, vals, sent, n in BYS:
        L.append([n * v / 100 for v in vals])
    M = [sum(L[b][i] for b in range(nb)) for i in range(nt)]
    tot = sum(M)
    if tot <= 0:
        return frame("Who says what, and how do they feel?", "No eligible grouped answers are available.", "", 320)
    R_ = [[M[i] * tones[names[i]][t] / 100 for i in range(nt)] for t in range(3)]
    RT = [sum(r) for r in R_]
    # All three columns must fit, including segment flows with more than three score-style bands.
    s = (H - 60 - max((nt - 1) * 12, (nb - 1) * 36, 72)) / tot
    xl, xm, xr, nw = 170, 520, 900, 14
    y0l = (H - (tot * s + (nb - 1) * 36)) / 2
    y0m = (H - (tot * s + (nt - 1) * 12)) / 2
    y0r = (H - (tot * s + 72)) / 2
    ly = []; y = y0l
    for b in range(nb):
        ly.append(y); y += sum(L[b]) * s + 36
    my = []; y = y0m
    for i in range(nt):
        my.append(y); y += M[i] * s + 12
    ry = []; y = y0r
    for t in range(3):
        ry.append(y); y += RT[t] * s + 36
    def link(x0, ya, x1, yb, h, fill, op):
        xm_ = (x0 + x1) / 2
        return (f'<path d="M{x0} {ya:.1f}C{xm_} {ya:.1f} {xm_} {yb:.1f} {x1} {yb:.1f}L{x1} {yb + h:.1f}C{xm_} {yb + h:.1f} {xm_} {ya + h:.1f} {x0} {ya + h:.1f}Z" style="fill:{fill};fill-opacity:{op}"/>')
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Flow from score band to theme to tone">']
    o.append(T(xl, 8, data.score.name, 14, 500, "var(--muted)", "start"))
    o.append(T(xm, 8, "Theme", 14, 500, "var(--muted)", "start"))
    o.append(T(xr, 8, "Tone", 14, 500, "var(--muted)", "start"))
    inm = [my[i] for i in range(nt)]
    for b in range(nb):
        yy = ly[b]
        for i in range(nt):
            h = L[b][i] * s
            o.append(link(xl + nw, yy, xm, inm[i], h, f"var(--{tcol[i]})", 0.55))
            inm[i] += h; yy += h
    outm = [my[i] for i in range(nt)]
    inr = list(ry)
    for i in range(nt):
        for t, c in enumerate(("neg", "neu", "pos")):
            h = R_[t][i] * s
            o.append(link(xm + nw, outm[i], xr, inr[t], h, f"var(--{c})", 0.6))
            outm[i] += h; inr[t] += h
    for b, (lab, vals, sent, n) in enumerate(BYS):
        h = sum(L[b]) * s
        o.append(f'<rect x="{xl}" y="{ly[b]:.1f}" width="{nw}" height="{h:.1f}" rx="2" style="fill:var(--ink)"/>')
        o.append(T(xl - 12, ly[b] + h / 2 - 10, lab, 16, 600, anchor="end"))
        o.append(T(xl - 12, ly[b] + h / 2 + 10, f"{fmt(n)} answers", 14, 400, "var(--muted)", "end"))
    for i in range(nt):
        h = M[i] * s
        o.append(f'<rect x="{xm}" y="{my[i]:.1f}" width="{nw}" height="{h:.1f}" rx="2" style="fill:var(--{tcol[i]})"/>')
        o.append(Th(xm + nw + 10, my[i] + h / 2, f"{names[i]} {fmt(round(M[i]))}", 14, 600))
    for t, (lab, c) in enumerate((("Negative", "neg"), ("Neutral", "neu"), ("Positive", "pos"))):
        h = RT[t] * s
        o.append(f'<rect x="{xr}" y="{ry[t]:.1f}" width="{nw}" height="{h:.1f}" rx="2" style="fill:var(--{c})"/>')
        o.append(T(xr + nw + 10, ry[t] + h / 2 - 10, lab, 16, 600))
        o.append(T(xr + nw + 10, ry[t] + h / 2 + 10, f"{fmt(round(RT[t]))} ({RT[t] / tot * 100:.0f}%)", 14, 400, "var(--muted)"))
    o.append("</svg>")
    source = "group" if data.score.name == data.segment.name else "score group"
    return frame("Who says what, and how do they feel?", f"Answers flow from {source} to theme to tone. Band height is number of answers.", "".join(o), H + 240)

# ---- arc diagram
def f_arc(data: ReportData):
    W, base = 1084, 400
    nt = len(data.themes)
    idx = {t.name: i for i, t in enumerate(data.themes)}
    PAIRS = [(min(idx[p.a], idx[p.b]), max(idx[p.a], idx[p.b]), p.count) for p in data.cooccurrence if p.a in idx and p.b in idx]
    xs = [70 + i * (W - 140) / max(nt - 1, 1) for i in range(nt)]
    o = [f'<svg width="{W}" height="560" viewBox="0 0 {W} 560" role="img" aria-label="Arc diagram of themes that appear in the same answer">']
    sel = idx.get(data.selected_theme, -1)
    for a, b, c in sorted(PAIRS, key=lambda p: p[2]):
        hit = sel in (a, b)
        r = (xs[b] - xs[a]) / 2
        col = "var(--t2)" if hit else "var(--muted)"
        op = 0.8 if hit else 0.22
        o.append(f'<path d="M{xs[a]:.1f} {base}A{r:.1f} {r:.1f} 0 0 1 {xs[b]:.1f} {base}" style="fill:none;stroke:{col};stroke-opacity:{op};stroke-width:{1.5 + c / 1900 * 14:.1f}"/>')
    for a, b, c in PAIRS:
        if sel in (a, b):
            r = (xs[b] - xs[a]) / 2
            o.append(Th((xs[a] + xs[b]) / 2, base - r - 14, fmt(c), 14, 600, "var(--ink)", "middle"))
    for i, (name, share, sent, cnt, col) in enumerate(rows(data)):
        r = 7 * math.sqrt(share)
        dim = 1 if i == sel or any(sel in (a, b) and i in (a, b) for a, b, c in PAIRS) else 0.35
        o.append(f'<circle cx="{xs[i]:.1f}" cy="{base}" r="{r:.1f}" style="fill:var(--{col});stroke:var(--bg);stroke-width:2;opacity:{dim}"/>')
        lines = (wrap(name, 128, 14) or [name]) + [f"{share}%"]
        for k, t in enumerate(lines):
            o.append(T(xs[i], base + 46 + k * 18, t, 14, 500 if k < len(lines) - 1 else 600, "var(--ink)" if dim == 1 else "var(--muted)", "middle"))
    o.append("</svg>")
    return frame("Which themes come up together?", "Each arc joins two themes mentioned in the same answer. Arc thickness is the number of answers. " + data.selected_theme + " is selected.", "".join(o), 760)

# ---- answer map
def f_map(data: ReportData):
    rnd = random.Random(data.answer_map.seed)
    bub = bub_of(data)
    has_real_points = bool(data.answer_map.points_by_theme)
    W, Hh = 1084, 620
    px0, pw, py0, ph = 60, 960, 40, 520
    # Honest, not just cosmetic: with real positions, one dot IS one real sampled answer - "about 50
    # answers" (the old synthetic-density ratio, share*9.5 dots standing in for the real count) would be
    # a wrong claim about real data.
    alt = ("Map of answers: each dot is one real sampled answer, placed by real wording similarity" if has_real_points
           else "Map of answers: each dot is about 50 answers, placed near answers with similar wording")
    o = [f'<svg width="{W}" height="{Hh}" viewBox="0 0 {W} {Hh}" role="img" aria-label="{esc(alt)}">']
    sel = data.selected_theme
    labels = ""
    tip = ""
    real_points = data.answer_map.points_by_theme
    for name, share, sent, cnt, col in rows(data):
        g = f'<g style="opacity:{1 if name == sel else DIM}">'
        if name in real_points:
            # Real sampled per-answer positions (chart-block stream, 2026-10-24, batch 4) - plotted
            # directly, never jittered: a reader seeing "two separate clusters" here is seeing a real
            # shape in the data, not a density illustration (see the synthetic branch below, still used
            # when no real positions exist, e.g. every report built before this stream).
            pts = [(px0 + x * pw, py0 + y * ph) for x, y in real_points[name]]
            cxy = (px0 + bub[name][0] * pw, py0 + bub[name][1] * ph) if name in bub else None
        elif name not in bub:
            n = round(share * 9.5)
            pts = [(px0 + rnd.random() * pw, py0 + rnd.random() * ph) for _ in range(n)]
            cxy = None
        else:
            n = round(share * 9.5)
            cx0, cy0 = px0 + bub[name][0] * pw, py0 + bub[name][1] * ph
            sg = 24 + 5 * math.sqrt(share)
            pts = [(rnd.gauss(cx0, sg), rnd.gauss(cy0, sg * 0.85)) for _ in range(n)]
            cxy = (cx0, cy0)
        for (x, y) in pts:
            g += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.8" style="fill:var(--{col});fill-opacity:.85"/>'
        g += "</g>"
        o.append(g)
        if cxy:
            sg = 24 + 5 * math.sqrt(share)
            op = 1 if name == sel else DIM + 0.1
            labels += f'<g style="opacity:{op}">' + Th(cxy[0], cxy[1] + sg * 1.9 + 8, name, 15, 600, "var(--ink)", "middle") + Th(cxy[0], cxy[1] + sg * 1.9 + 27, f"{share}%", 14, 400, "var(--muted)", "middle") + "</g>"
            if name == sel:
                tip = (f'<circle cx="{cxy[0] + 14:.1f}" cy="{cxy[1] - 10:.1f}" r="8" style="fill:none;stroke:var(--ink);stroke-width:2"/>'
                       f'<rect x="{cxy[0] + 30:.1f}" y="{cxy[1] - 86:.1f}" width="330" height="58" rx="8" style="fill:var(--ink)"/>'
                       + T(cxy[0] + 44, cxy[1] - 66, data.answer_map.tip_text, 14, 500, "var(--bg)")
                       + T(cxy[0] + 44, cxy[1] - 44, data.answer_map.tip_note, 13, 400, "var(--bg)"))
    o.append(labels)
    o.append(tip)
    o.append("</svg>")
    density_note = "Each dot is one real sampled answer." if has_real_points else "Each dot is about 50 answers."
    return frame("What does the whole pool of answers look like?", f"{density_note} " + data.selected_theme + " is selected.", "".join(o), 820)


# ---------- group_split_bars, compare_dots, slope_change (chart-block stream, 2026-10-24 - new ----------
# renderers for 3 of app/report_blocks.py's "reuse group" blocks: real data (SegmentData/TrendData) that
# existing renderers never drew, so unlike diverge/sunburst/byScore above these needed real new chart code
# - still no new upstream data pipeline, same as the rest of that group.

def _theme_color_by_name(data: ReportData, name: str) -> str:
    """`SegmentRow.theme`/`TrendSeries.theme` are plain name strings (app/chart_data.py), not already
    carrying a colour token the way `ThemeNode` does - this looks the matching node up once per row, same
    "other" fallback `_theme_color`/`treemap_rows` already use elsewhere for a name this report's top-7
    nodes don't cover."""
    node = next((t for t in data.themes if t.name == name), None)
    return node.color if node is not None else "other"


def f_group_split_bars(data: ReportData):
    """Two segment groups, side by side per theme - CLAUDE.md's "no pie/donut" + "colour never the only
    carrier" rules kept: each theme's own two bars share that theme's own colour token (identity), split
    only by opacity (not a second meaning-bearing colour), with both real numbers always printed."""
    seg_ = data.segment
    ga, gb = seg_.groups[0], seg_.groups[1]
    ROWS = [(r.theme, _theme_color_by_name(data, r.theme), r.values[0], r.values[1]) for r in seg_.rows]
    rh = 64
    rows_html = ""
    for name, col, va, vb in ROWS:
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:16px;height:{rh}px;border-top:1px solid var(--line)">'
            f'<div style="flex:0 0 clamp(140px,20%,240px);font-size:15px;font-weight:500;line-height:1.2">{esc(name)}</div>'
            f'<div style="flex:1;display:flex;flex-direction:column;gap:6px">'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<div style="flex:1;height:16px;border-radius:3px;background:var(--line);overflow:hidden">'
            f'<div style="width:{va}%;height:100%;background:var(--{col})"></div></div>'
            f'<div style="width:48px;text-align:right;font-size:14px;font-weight:600">{va}%</div></div>'
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<div style="flex:1;height:16px;border-radius:3px;background:var(--line);overflow:hidden">'
            f'<div style="width:{vb}%;height:100%;background:color-mix(in srgb,var(--{col}) 45%,var(--surface))"></div></div>'
            f'<div style="width:48px;text-align:right;font-size:14px;font-weight:600;color:var(--muted)">{vb}%</div></div>'
            f'</div></div>'
        )
    # Neutral ink tones here, NOT var(--accent): each row's own two bars are ITS OWN theme colour (full
    # tone vs. a 45% tint of it), so a fixed accent swatch would mismatch every row's actual bar colour.
    # "solid vs. lighter" in neutral ink reads correctly against any theme's hue, row to row.
    legend = (f'<div style="margin-top:4px;display:flex;gap:20px;font-size:14px;color:var(--muted)">'
              f'<span style="display:inline-flex;align-items:center;gap:8px"><span style="width:14px;height:14px;border-radius:3px;background:var(--ink)"></span>{esc(ga.label)}</span>'
              f'<span style="display:inline-flex;align-items:center;gap:8px"><span style="width:14px;height:14px;border-radius:3px;background:color-mix(in srgb,var(--ink) 35%,var(--surface))"></span>{esc(gb.label)}</span></div>')
    sub = f"{ga.label} (n={fmt(ga.n)}) against {gb.label} (n={fmt(gb.n)}). Share of each group's own answers."
    body = (f'<div style="padding:56px 48px">{hdr("Two groups side by side", sub)}'
            f'<div style="height:24px"></div>{legend}<div style="margin-top:12px">{rows_html}</div></div>')
    return body, 1180, 120 + rh * len(ROWS)


def f_compare_dots(data: ReportData):
    """One leading theme's share across many segment groups (8-20, too many for a readable heatmap grid)
    as a dot plot against a dashed "overall" reference line - same `--ramp`/overall-comparison language
    `f_heatmap` already uses for "this group vs the dataset as a whole", just one row per group instead of
    one cell."""
    seg_ = data.segment
    lead = seg_.rows[0]
    col = _theme_color_by_name(data, lead.theme)
    groups = sorted(zip(seg_.groups, lead.values), key=lambda gv: gv[1], reverse=True)
    rh = 40
    AXIS_W = 760
    rows_html = ""
    for g, v in groups:
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:16px;height:{rh}px">'
            f'<div style="flex:0 0 clamp(120px,18%,200px);font-size:14px;line-height:1.2">{esc(g.label)}</div>'
            f'<div style="position:relative;width:{AXIS_W}px;height:100%">'
            f'<div style="position:absolute;left:{lead.overall / 100 * AXIS_W:.1f}px;top:0;bottom:0;width:0;border-left:1px dashed var(--muted)"></div>'
            f'<div style="position:absolute;left:0;right:0;top:50%;height:1px;background:var(--line)"></div>'
            f'<div style="position:absolute;left:{v / 100 * AXIS_W - 6:.1f}px;top:50%;transform:translateY(-50%);width:12px;height:12px;border-radius:50%;background:var(--{col})"></div>'
            f'</div><div style="width:48px;text-align:right;font-size:14px;font-weight:600">{v}%</div></div>'
        )
    body = (f'<div style="padding:56px 48px">{hdr(f"{lead.theme}, by group", f"Dashed line is the overall share ({lead.overall}%). {len(groups)} groups, largest value first.")}'
            f'<div style="height:24px"></div>{rows_html}</div>')
    return body, 1180, 120 + rh * len(groups)


def f_slope_change(data: ReportData):
    """First period against last - a slope graph (SPEC's own "see more" tier, not a full trend line):
    one line per theme from its first-period share to its last-period share, coloured by that theme's own
    token. Uses only `tr.labels[0]`/`[-1]` and each series' matching endpoints - genuinely two points, not
    a thinned-down version of `f_trend`'s own multi-period line."""
    tr = data.trend
    first_label, last_label = tr.labels[0], tr.labels[-1]
    W, H = 1084, 120 + 56 * len(tr.series)
    x0, x1 = 160, W - 160
    top, bottom = 60, H - 40
    span = max(1, bottom - top)

    # Autoscaled to the real values present, NOT a fixed 0-100% domain - found live: several real themes'
    # shares (e.g. 8/10/16/26/33%) all sit in one low band of a 0-100 scale, so a fixed domain crammed
    # every line and label into the bottom third of the chart, overlapping unreadably. Padding keeps a
    # single value (or several identical ones) from landing exactly on an edge; the real numbers printed
    # next to each point are untouched either way - this only changes where the LINE is drawn, never what
    # it says, same "never invent or hide a number" discipline every other chart here already follows.
    all_values = [v for s in tr.series for v in (s.values[0], s.values[-1])]
    lo, hi = min(all_values), max(all_values)
    pad = max(2.0, (hi - lo) * 0.15)
    lo, hi = max(0.0, lo - pad), hi + pad
    v_span = max(1.0, hi - lo)

    def y_of(v: float) -> float:
        return bottom - (v - lo) / v_span * span

    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Slope chart: theme share, first period against last">']
    o.append(T(x0, 30, first_label, 14, 600, "var(--muted)"))
    o.append(T(x1, 30, last_label, 14, 600, "var(--muted)", "end"))
    labels = []
    for s in tr.series:
        v0, v1 = s.values[0], s.values[-1]
        y0v, y1v = y_of(v0), y_of(v1)
        o.append(f'<line x1="{x0}" y1="{y0v:.1f}" x2="{x1}" y2="{y1v:.1f}" style="stroke:var(--{s.color});stroke-width:3"/>')
        o.append(f'<circle cx="{x0}" cy="{y0v:.1f}" r="5" style="fill:var(--{s.color})"/>')
        o.append(f'<circle cx="{x1}" cy="{y1v:.1f}" r="5" style="fill:var(--{s.color})"/>')
        labels.append(chart_label(x0 - 12, y0v, W, H, f"{s.theme}  {v0}%", 14, 500, f"var(--{s.color})", "end"))
        labels.append(chart_label(x1 + 12, y1v, W, H, f"{v1}%", 14, 500, f"var(--{s.color})", "start"))
    o.append("</svg>")
    diagram = f'<div style="position:relative;width:100%">{"".join(o)}{"".join(labels)}</div>'
    return frame("First against last", f"{first_label} against {last_label}. Every theme's share, start to end.", diagram, H)


# ---------- tone_by_number, theme_mix_over_time (chart-block stream, 2026-10-24 batch 1 - both reuse ----
# data shapes that already existed before this stream started: ScoreBand already carries a real
# `sentiment` per band (used today only by byScore's own mix bars), and TrendData already carries a real
# per-theme-per-period share series (used today only by f_trend's combined line chart). Neither needed a
# new upstream pipeline - only a new way to look at data this app already computes.

def f_tone_by_number(data: ReportData):
    """One row per score/number band, a bar diverging from 0 toward each band's own average sentiment,
    tinted by `tone()` the same way f_rank's own sentiment column already is - "the more X, the more
    negative they sound" as a real, already-computed trend across bands, not a new correlation computed
    here."""
    sd = data.score
    overall = data.overall_sentiment
    rh = 60
    AXIS_W = 760
    rows_html = ""
    for b in sd.bands:
        col = tone(b.sentiment, overall)
        pct = (max(-1.0, min(1.0, b.sentiment)) + 1) / 2 * 100  # -1..1 -> 0..100% of the axis
        left, width = (50.0, pct - 50.0) if pct >= 50 else (pct, 50.0 - pct)
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:16px;height:{rh}px;border-top:1px solid var(--line)">'
            f'<div style="flex:0 0 clamp(140px,20%,220px);font-size:15px;font-weight:500">{esc(b.label)}</div>'
            f'<div style="position:relative;width:{AXIS_W}px;height:28px">'
            f'<div style="position:absolute;left:50%;top:0;bottom:0;width:0;border-left:1px dashed var(--muted)"></div>'
            f'<div style="position:absolute;top:50%;transform:translateY(-50%);left:{left:.1f}%;width:{width:.1f}%;height:16px;border-radius:3px;background:{col}"></div>'
            f'</div><div style="width:64px;text-align:right;font-size:14px;font-weight:600">{b.sentiment:+.2f}</div>'
            f'<div style="width:72px;text-align:right;font-size:13px;color:var(--muted)">{fmt(b.answers)}</div></div>'
        )
    sub = f"{sd.name}, lowest to highest. Average sentiment per band, dashed line is 0 (neutral)."
    body = (f'<div style="padding:56px 48px">{hdr("Tone by number band", sub)}<div style="height:24px"></div>{rows_html}</div>')
    return body, 1180, 120 + rh * len(sd.bands)


def f_theme_mix_over_time(data: ReportData):
    """Stacked horizontal bars, one per period - each theme's own real per-period share (`TrendData.series`)
    as a segment, so a reader sees the whole MIX shift, not just one line's up-and-down the way f_trend's
    combined chart already shows. Deliberately horizontal stacked bars, not an SVG stream/area shape - same
    "shapes-only-SVG not needed for axis-aligned rects" reasoning f_quality/f_byscore already follow."""
    tr = data.trend
    rh = 48
    rows_html = ""
    for i, label in enumerate(tr.labels):
        segs = ""
        for s in tr.series:
            v = s.values[i] if i < len(s.values) else 0
            if v <= 0:
                continue
            segs += f'<div style="width:{v}%;height:100%;background:var(--{s.color})" title="{esc(s.theme)} {v}%"></div>'
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:16px;height:{rh}px">'
            f'<div style="flex:0 0 80px;font-size:14px;color:var(--muted)">{esc(label)}</div>'
            f'<div style="flex:1;display:flex;height:28px;border-radius:4px;overflow:hidden;background:var(--line)">{segs}</div></div>'
        )
    legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:20px;font-size:14px;color:var(--muted)">'
        f'<span style="width:14px;height:14px;border-radius:3px;background:var(--{s.color})"></span>{esc(s.theme)}</span>'
        for s in tr.series
    )
    sub = f"{tr.note} Each bar is one period; segment width is that theme's share."
    body = (f'<div style="padding:56px 48px">{hdr("Theme mix over time", sub)}<div style="height:24px"></div>'
            f'{rows_html}<div style="margin-top:24px">{legend}</div></div>')
    return body, 1180, 120 + rh * len(tr.labels)


# ---------- trend_groups / trend_styled (chart-block stream, 2026-10-24, batch 2 - a NEW cross-tab: -----
# GroupTrendData, per-GROUP sentiment over time, not per-theme share like f_trend above)

def _trend_group_lines(data: ReportData, styled: bool):
    """Shared geometry for `f_trend_groups`/`f_trend_styled` - `styled` adds a distinct dash pattern AND
    marker shape per group (not colour alone), so the same chart stays readable in greyscale, print, or
    for a colour-blind reader - the design's own stated reason for `trend_styled` existing as a second
    block at all, not a cosmetic variant nobody asked for."""
    gt = data.group_trend
    W, H = 1084, 520
    x0, x1 = 160, W - 60
    top, bottom = 50, H - 60
    NP = len(gt.labels)
    dx = (x1 - x0) / max(1, NP - 1)

    if not gt.series:
        # Same empty-sequence guard f_phrases/f_freq needed - no group_trend candidate survived for most
        # reports (needs both a real segment column and a real date column at once), and this renderer is
        # gallery-only until Stage 2 wires real chart-selection logic anyway.
        return '<div style="color:var(--muted)">No group and date column pairing produced a real trend for this report.</div>', W, 100

    all_values = [v for s in gt.series for v in s.values]
    lo, hi = min(all_values), max(all_values)
    pad = max(0.02, (hi - lo) * 0.15)
    lo, hi = lo - pad, hi + pad
    v_span = max(0.01, hi - lo)

    def X(i): return x0 + dx * i
    def Y(v): return bottom - (v - lo) / v_span * (bottom - top)

    DASH = ["none", "6 4", "2 3", "10 3 2 3", "1 4"]
    MARK = ["circle", "square", "diamond", "triangle", "circle"]

    def marker(shape, cx, cy, col):
        if shape == "square":
            return f'<rect x="{cx - 5:.1f}" y="{cy - 5:.1f}" width="10" height="10" style="fill:{col}"/>'
        if shape == "diamond":
            return f'<rect x="{cx - 4.5:.1f}" y="{cy - 4.5:.1f}" width="9" height="9" transform="rotate(45 {cx:.1f} {cy:.1f})" style="fill:{col}"/>'
        if shape == "triangle":
            return f'<path d="M{cx:.1f} {cy - 6:.1f} L{cx + 6:.1f} {cy + 5:.1f} L{cx - 6:.1f} {cy + 5:.1f} Z" style="fill:{col}"/>'
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" style="fill:{col}"/>'

    o = [f'<svg width="100%" height="100%" viewBox="0 0 {W} {H}" preserveAspectRatio="none" style="display:block" '
         f'role="img" aria-label="Average sentiment per {esc(gt.group_column)} group, over time">']
    for g in (-1.0, -0.5, 0.0, 0.5, 1.0):
        if lo <= g <= hi:
            o.append(f'<line x1="{x0}" y1="{Y(g):.1f}" x2="{x1}" y2="{Y(g):.1f}" style="stroke:var(--line);stroke-width:1"/>')
    labels = [chart_label(x0, top - 24, W, H, "Average sentiment, by group", 15, 600)]
    for i, s in enumerate(gt.series):
        col = f"var(--{s.color})"
        dash = f';stroke-dasharray:{DASH[i % len(DASH)]}' if styled and DASH[i % len(DASH)] != "none" else ""
        pts = " ".join(f"{X(i_):.1f},{Y(v):.1f}" for i_, v in enumerate(s.values))
        o.append(f'<polyline points="{pts}" style="fill:none;stroke:{col};stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round{dash}"/>')
        for i_, v in enumerate(s.values):
            if styled:
                o.append(marker(MARK[i % len(MARK)], X(i_), Y(v), col))
        labels.append(chart_label(x1 + 14, Y(s.values[-1]), W, H, f"{s.group} {s.values[-1]:+.2f}", 14, 600, col))
    for i, lab in enumerate(gt.labels):
        labels.append(chart_label(X(i), bottom + 24, W, H, lab, 13, 400, "var(--muted)", "middle"))
    o.append("</svg>")
    chart = f'<div style="position:relative;width:100%;height:{H}px">{"".join(o)}{"".join(labels)}</div>'
    return chart, W, H


def f_trend_groups(data: ReportData):
    chart, w, h = _trend_group_lines(data, styled=False)
    body = f'<div style="padding:56px 48px">{hdr("Over time, by group", data.group_trend.note)}<div style="height:24px"></div>{chart}</div>'
    return body, 1180, h + 160


def f_trend_styled(data: ReportData):
    chart, w, h = _trend_group_lines(data, styled=True)
    sub = f"{data.group_trend.note} Dash and marker, not colour alone, tell each group's line apart."
    body = f'<div style="padding:56px 48px">{hdr("Over time, by dash and marker", sub)}<div style="height:24px"></div>{chart}</div>'
    return body, 1180, h + 160


# ---------- binned_grid (chart-block stream, 2026-10-24, batch 3 - a NEW data shape: BinnedGridData) ----
def f_binned_grid(data: ReportData):
    """Two independent number columns, quartile-banded, crossed into a grid - "Higher spenders are far
    less likely to sound neutral." Same plain HTML/CSS grid shape `f_heatmap` already uses (axis-aligned
    cells, no curved geometry, no reason for SVG), tinted by `tone()` against this report's real overall
    sentiment instead of `--ramp` against a row's own overall (there is no single "theme" row here to be
    above/below - every cell is its own independent (row band, column band) pairing)."""
    bg = data.binned_grid
    overall = data.overall_sentiment
    g = f'<div style="display:grid;grid-template-columns:minmax(140px,180px) repeat({len(bg.col_labels)},minmax(0,1fr));gap:4px">'
    g += '<div></div>'
    for cl in bg.col_labels:
        g += f'<div style="padding:0 0 8px;text-align:center;font-size:14px;font-weight:500">{esc(cl)}</div>'
    cell_by_pos = {(c.row_label, c.col_label): c for c in bg.cells}
    for rl in bg.row_labels:
        g += f'<div style="display:flex;align-items:center;font-size:15px;font-weight:500">{esc(rl)}</div>'
        for cl in bg.col_labels:
            c = cell_by_pos.get((rl, cl))
            if c is None or c.count == 0:
                g += '<div style="height:66px;border-radius:4px;background:var(--line);opacity:.35"></div>'
                continue
            col = tone(c.sentiment, overall)
            g += (f'<div style="height:66px;border-radius:4px;background:{col};display:flex;flex-direction:column;'
                  f'align-items:center;justify-content:center;color:var(--ink)">'
                  f'<span style="font-size:17px;font-weight:600">{c.sentiment:+.2f}</span>'
                  # var(--ink) at reduced opacity, NOT var(--muted) - found live: a flat muted grey has
                  # poor contrast against a strongly-tinted cell (confirmed via screenshot on a real
                  # dataset), while ink-at-opacity stays legible on every tint this chart ever produces,
                  # matching the sentiment number's own already-confirmed-legible colour above it.
                  f'<span style="font-size:12px;color:var(--ink);opacity:.6">{fmt(c.count)}</span></div>')
    g += "</div>"
    sub = f"{bg.row_name} by {bg.col_name}. Colour is average sentiment, against this report's overall ({overall:+.2f})."
    body = f'<div style="padding:56px 48px">{hdr("Two numbers together", sub)}<div style="height:28px"></div>{g}</div>'
    return body, 1180, 160 + 90 * len(bg.row_labels)


# ---------- vs_average (chart-block stream, 2026-10-24, batch 2 - a NEW data shape: CategoryAvgData) ----
def f_vs_average(data: ReportData):
    """One bar per category, length = that category's own average of the number column, with a dashed
    reference line at the real overall average - "Software engineers and managers earn well above
    average" as a real, already-computed ranking, not an invented one. Same diverge-from-a-reference-line
    language `f_tone_by_number` above already uses, just against a real numeric average instead of 0."""
    ca = data.category_avg
    rh = 56
    mx = max((i.avg for i in ca.items), default=1) or 1
    AXIS_W = 760
    ref_pct = min(100.0, ca.overall_avg / mx * 100)
    rows_html = ""
    for i in ca.items:
        pct = min(100.0, i.avg / mx * 100)
        above = i.avg >= ca.overall_avg
        col = "var(--pos)" if above else "var(--neg)"
        rows_html += (
            f'<div style="display:flex;align-items:center;gap:16px;height:{rh}px;border-top:1px solid var(--line)">'
            f'<div style="flex:0 0 clamp(140px,20%,220px);font-size:15px;font-weight:500">{esc(i.label)}</div>'
            f'<div style="position:relative;width:{AXIS_W}px;height:20px">'
            f'<div style="position:absolute;left:{ref_pct:.1f}%;top:-4px;bottom:-4px;width:0;border-left:1px dashed var(--muted)"></div>'
            f'<div style="width:{pct:.1f}%;height:100%;border-radius:3px;background:{col}"></div></div>'
            f'<div style="width:96px;text-align:right;font-size:14px;font-weight:600">{i.avg:,.0f}</div>'
            f'<div style="width:64px;text-align:right;font-size:13px;color:var(--muted)">{fmt(i.n)}</div></div>'
        )
    sub = f"{ca.category_name}. {ca.number_name}, dashed line is the real overall average ({ca.overall_avg:,.0f})."
    body = f'<div style="padding:56px 48px">{hdr("Compared with average", sub)}<div style="height:24px"></div>{rows_html}</div>'
    return body, 1180, 120 + rh * len(ca.items)


# ---------- registry and standalone rendering ----------
FRAMES = {
    "overview": f_overview, "sunburst": f_sunburst, "treemap": f_treemap, "icicle": f_icicle,
    "sentsun": f_sentsun, "rank": f_rank, "diverge": f_diverge, "mekko": f_mekko, "bubbles": f_bubbles,
    "sankey": f_sankey, "arc": f_arc, "map": f_map, "byScore": f_byscore, "heatmap": f_heatmap,
    "trend": f_trend, "quality": f_quality, "context": f_context, "tokens": f_tokens,
    "sunburst-mobile": f_sunburst_m, "rank-mobile": f_rank_m, "othergrowth": f_other_growth,
    "groupSplitBars": f_group_split_bars, "compareDots": f_compare_dots, "slopeChange": f_slope_change,
    "groupMix": f_group_mix,
    "phrases": f_phrases, "toneByNumber": f_tone_by_number, "themeMixOverTime": f_theme_mix_over_time,
    "themesOverTime": f_themes_over_time, "themeScores": f_theme_scores,
    "quotes": f_quotes, "freq": f_freq, "vsAverage": f_vs_average,
    "trendGroups": f_trend_groups, "trendStyled": f_trend_styled, "binnedGrid": f_binned_grid,
}

# Human-readable title per frame id, for the chart list API.
TITLES = {
    "groupMix": "Group size and theme mix",
    "overview": "Overview", "sunburst": "Themes, sunburst", "treemap": "Themes, treemap", "icicle": "Themes, icicle",
    "sentsun": "Sentiment sunburst", "rank": "Rank themes", "diverge": "Diverging sentiment", "mekko": "Sentiment marimekko",
    "bubbles": "Theme similarity", "sankey": "Score to theme to tone", "arc": "Theme co-occurrence", "map": "Answer map",
    "byScore": "Themes by score group", "heatmap": "Themes by segment", "trend": "Trend over time", "quality": "Answer quality",
    "context": "Question context", "tokens": "Design tokens", "sunburst-mobile": "Themes, sunburst (mobile)",
    "rank-mobile": "Rank themes (mobile)", "othergrowth": "New themes found",
    "groupSplitBars": "Two groups side by side", "compareDots": "Many groups, little space",
    "slopeChange": "First against last", "phrases": "Which phrases recur?",
    "toneByNumber": "Tone by number band", "themeMixOverTime": "Theme mix over time",
    "themesOverTime": "Themes over time", "themeScores": "Scores by theme",
    "quotes": "What does it sound like?", "freq": "What did people say most?",
    "vsAverage": "Compared with average", "trendGroups": "Over time, by group",
    "trendStyled": "Over time, by dash and marker", "binnedGrid": "Two numbers together",
}

def render_parts(frame_id: str, data: ReportData | None = None):
    """Return (body_html, width, height) for a frame. data defaults to the EV sample."""
    if data is None:
        from .fixtures.ev_sample import EV
        data = EV
    return FRAMES[frame_id](data)

def render_report_parts(frame_id: str, data: ReportData, selected: str | None = None):
    """Like render_parts, for the real report page: gallery frames that draw several demo states side by
    side get their single real state instead. Every other frame is unchanged."""
    if frame_id == "sunburst":
        return sunburst_report(data, selected)
    if frame_id == "context":
        return context_report(data)
    if frame_id == "overview":
        return f_overview(data, report=True)
    return render_parts(frame_id, data)

def context_report(data: ReportData):
    """The question-context sentence as plain text, for exports and any client without the live control.
    `f_context` is the gallery mockup: it draws the type menu permanently open over the sentence, leaves a
    fixed gap for it, and ends in an empty "How the charts were chosen" section. On the report page the
    frontend replaces this with a real dropdown (frontend/src/QuestionContext.tsx)."""
    cx = data.context
    em = "color:var(--accent);font-weight:400"
    note = f" You changed this from Verbatim's guess, {esc(cx.guessed_kind)}." if cx.corrected else ""
    payload = json.dumps({
        "kind": cx.kind, "options": cx.kind_options, "guessed_kind": cx.guessed_kind, "corrected": cx.corrected,
        "framing": cx.framing, "length": cx.length,
        "answered_note": f"{fmt(data.answered)} of {fmt(data.total)} responses had an answer to analyse.",
        "columns_note": cx.columns_note,
    })
    body = (f'<div style="padding:56px 48px" data-context="{esc(payload)}">'
            f'<div style="font-size:36px;font-weight:300;line-height:1.3;max-width:1020px">This question asks for '
            f'<span style="{em}">{esc(cx.kind)}</span>, framed <span style="{em}">{esc(cx.framing)}</span>, and '
            f'answers run <span style="{em}">{esc(cx.length)}</span>.</div>'
            f'<div style="margin-top:20px;font-size:17px;line-height:1.55;max-width:820px;color:var(--muted)">'
            f'{fmt(data.answered)} of {fmt(data.total)} responses had an answer to analyse. {esc(cx.columns_note)}{note}</div></div>')
    return body, 1180, 300

def render(frame_id: str, data: ReportData | None = None) -> str:
    body, w, h = render_parts(frame_id, data)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>[{esc(frame_id)}]</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost:wght@300;400;500;600&amp;display=swap">
<style>{CSS}html,body{{background:#f2f7f6}}</style></head>
<body><div class="v" style="width:{w}px;min-height:{h}px;max-width:100%;margin:0 auto;position:relative">{body}</div></body></html>"""

import html, math, random

from .chart_data import ReportData


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
            else:  # Other callout
                shapes.append(f'<g style="opacity:{op}"><polyline points="{px:.1f},{py:.1f} {px + 14:.1f},{py - 30:.1f} {px + 26:.1f},{py - 30:.1f}" style="fill:none;stroke:var(--muted);stroke-width:1"/>'
                               f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" style="fill:var(--other)"/></g>')
                labels.append(chart_label(px + 32, py - 40, W, H, f"{name} {fmt(cnt)} ({share}%)", 14, 600, opacity=op))
                labels.append(chart_label(px + 32, py - 22, W, H, notes[name], 13, 400, "var(--muted)", opacity=op))
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

def f_sunburst(data: ReportData):
    def panel(cap, selected, hover):
        return (f'<div style="font-size:14px;font-weight:500;color:var(--muted);margin:0 0 10px">{esc(cap)}</div>'
                f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:24px;display:flex;gap:24px;height:630px">'
                f'<div style="flex:none">{sunburst(data, 640, 580, 380, 300, 245, 14, 12.5, selected, hover)}</div>'
                f'<div style="flex:1;min-width:0">{theme_rows(data, selected, hover)}</div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What are the themes?", data.question)}'
            f'<div style="height:24px"></div>'
            + panel(f"Default, hover on {data.hover_theme}", None, data.hover_theme)
            + '<div style="height:40px"></div>'
            + panel(f"{data.selected_theme} selected, others dimmed", data.selected_theme, None) + "</div>")
    return body, 1180, 1640

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


def f_overview(data: ReportData):
    stats = data.overview.stats
    chart = treemap_html(data, OVERVIEW_TREEMAP_W, OVERVIEW_TREEMAP_H)
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
def rank_rows(data, mobile=False, selected=None, hover=None):
    o = ""
    mx = max(t.share for t in data.themes)
    for name, share, sent, cnt, col in rows(data):
        sel = name == selected
        op = DIM if (selected and not sel) else 1
        bg = "background:var(--surface);" if (name == hover or sel) else ""
        ring = "outline:2px solid var(--ink);outline-offset:-2px;" if sel else ""
        if mobile:
            bw = share / mx * 236
            o += (f'<div style="padding:10px 12px;border-radius:8px;{bg}{ring}opacity:{op}">'
                  f'<div style="display:flex;justify-content:space-between;font-size:15px;font-weight:500"><span>{esc(name)}</span>'
                  f'<span style="font-weight:400;color:var(--muted)">{sent:+.2f}</span></div>'
                  f'<div style="display:flex;align-items:center;gap:10px;margin-top:6px"><div style="width:{bw:.0f}px;height:22px;border-radius:3px;background:{tone(sent, data.overall_sentiment)};flex:none"></div>'
                  f'<div style="line-height:1.15"><div style="font-size:16px;font-weight:600">{share}%</div><div style="font-size:12px;color:var(--muted)">{fmt(cnt)}</div></div></div></div>')
        else:
            pct = share / mx * 100
            # Bar width is a % of its own flex:1 wrapper (not a px number computed against a fixed
            # design width) so the bar genuinely lengthens as the row itself widens - the two side
            # columns use flex-basis: clamp() rather than a bare px so they get a little breathing
            # room on a wide screen without ever shrinking below a readable minimum. Font sizes are
            # untouched literal px - only the layout reflows, matching docs/DECISIONS.md's fluid-charts
            # entry.
            o += (f'<div style="display:flex;align-items:center;height:64px;padding:0 16px;border-radius:8px;{bg}{ring}opacity:{op}">'
                  f'<div style="flex:0 0 clamp(160px,18%,280px);font-size:17px;font-weight:500">{esc(name)}</div>'
                  f'<div style="flex:1;display:flex;align-items:center;gap:14px">'
                  f'<div style="flex:1;min-width:0"><div style="width:{pct:.1f}%;height:28px;border-radius:3px;background:{tone(sent, data.overall_sentiment)}"></div></div>'
                  f'<div style="line-height:1.2;flex:none"><div style="font-size:18px;font-weight:600">{share}%</div><div style="font-size:13px;color:var(--muted)">{fmt(cnt)}</div></div></div>'
                  f'<div style="flex:0 0 clamp(70px,8%,110px);text-align:right;font-size:17px">{sent:+.2f}</div></div>')
    return o

def rank_legend():
    def sw(c, t):
        return (f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:22px;font-size:14px;color:var(--muted)">'
                f'<span style="width:16px;height:16px;border-radius:3px;background:{c}"></span>{t}</span>')
    return (sw("var(--neg)", "More negative than average") + sw("var(--neu)", "About average") + sw("var(--pos)", "Milder than average"))

def f_rank(data: ReportData):
    body = (f'<div style="padding:56px 48px"><div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<div>{hdr("What should we fix first?", f"Bar length is share of answered. Tint compares each theme with the overall average ({data.overall_sentiment:.2f}).")}</div>'
            f'{seg(["Themes", "Sub-themes"], "Themes")}</div>'
            f'<div style="margin-top:22px;display:flex;flex-wrap:wrap">{rank_legend()}</div>'
            f'<div style="display:flex;padding:22px 16px 8px;font-size:13px;font-weight:500;color:var(--muted)"><div style="flex:0 0 clamp(160px,18%,280px)">Theme</div><div style="flex:1">Share of answered, with count</div><div style="flex:0 0 clamp(70px,8%,110px);text-align:right">Avg sentiment</div></div>'
            f'{rank_rows(data, False, None, data.selected_theme)}</div>')
    return body, 1180, 860

def f_rank_m(data: ReportData):
    body = (f'<div style="padding:24px 16px">{hdr("What should we fix first?")}'
            f'<div style="margin-top:14px">{seg(["Themes", "Sub-themes"], "Themes", None, True)}</div>'
            f'<div style="margin-top:14px;display:flex;flex-wrap:wrap;row-gap:6px">{rank_legend()}</div>'
            f'<div style="margin-top:12px;font-size:13px;color:var(--muted)">{esc(data.selected_theme)} selected, others dimmed</div>'
            f'<div style="margin-top:6px">{rank_rows(data, True, data.selected_theme)}</div></div>')
    return body, 390, 960

# ---------- diverge ----------
def f_diverge(data: ReportData):
    DIV = [(t.name, *t.tones) for t in data.themes]
    s = 5.2; cx = 600; rh = 60; y0 = 64
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
        o.append(T(cx - hn - ng * s / 2, cy, f"{ng}%", 14, 600, "var(--on-neg)", "middle"))
        o.append(T(cx, cy, f"{nu}%", 14, 500, "var(--on-neu)", "middle"))
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
        for i, v in enumerate(vals):
            col = data.themes[i].color
            name = data.themes[i].name
            txt = f"{v}%" if v >= 5 else f"{v}"
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
        pp = min(55, abs(sent) / 0.2 * 55)
        rows_html += (f'<div style="display:flex;align-items:center;padding:20px 0;border-top:1px solid var(--line)">'
                 f'<div style="width:200px;flex:none"><div style="font-size:18px;font-weight:600">{lab}</div><div style="font-size:14px;color:var(--muted)">{fmt(n)} answers</div></div>'
                 f'<div style="flex:1;height:66px;display:flex;border-radius:6px;overflow:hidden">{segs}</div>'
                 f'<div style="margin-left:32px;display:inline-flex;align-items:baseline;gap:8px;padding:6px 16px;border:1px solid var(--line);border-radius:999px;background:color-mix(in srgb,var(--neg) {pp:.0f}%,var(--surface))">'
                 f'<span style="font-size:13px;color:var(--ink)">avg sentiment</span><span style="font-size:17px;font-weight:600">{sent:+.2f}</span></div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What does each score group talk about?", f"Theme mix by {data.score.name}. Each bar adds to 100%.")}'
            f'<style>{css_rules}</style>'
            f'<div style="height:24px"></div><div style="border-bottom:1px solid var(--line)">{rows_html}</div>'
            f'<div style="margin-top:24px">{key_row(data)}</div></div>')
    return body, 1180, 660

# ---------- heatmap ----------
def ramp_mix(v, overall):
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

# ---------- freq ----------
def f_freq(data: ReportData):
    fq = data.frequency
    OCC = [(i.label, i.pct, i.merged) for i in fq.items]
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

# ---- treemap
def treemap_html(data: ReportData, w: int, h: int) -> str:
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
    a `<div>` tree instead of nested `<svg><g>` groups."""
    rects = squarify([(n, s) for n, s, _, _, _ in treemap_rows(data)], 0, 0, w, h)
    cells = []
    for idx, (name, share, sent, cnt, col) in enumerate(treemap_rows(data)):
        rx, ry, rw, rh = rects[name]

        subs = subs_of(data, name)
        sub_html = ""
        header_pct = 34  # a fixed share of this cell's own height reserved for its label, not a computed
                          # "how tall did the label actually render" pixel value - see docstring above.
        if subs:
            sub_w, sub_h = rw - 10, rh * (100 - header_pct) / 100 - 5
            if sub_w > 20 and sub_h > 20:
                sr = squarify(subs, 0, 0, sub_w, sub_h)
                sub_cells = ""
                for k, (sn, sp) in enumerate(subs):
                    sx, sy, sw, sh = sr[(sn, sp)] if (sn, sp) in sr else sr[sn]
                    # Line count is computed from this sub-cell's own known height (sh, already in the
                    # fixed 580px design-height reference frame the browser actually renders at) rather
                    # than capped at a fixed number - see treemap_html's own docstring. Width-wise
                    # wrapping is left entirely to the browser's natural text flow.
                    s_line_h = 14 * 1.2
                    s_max_lines = max(1, int((sh - 4) // s_line_h))
                    sub_cells += (
                        f'<div style="position:absolute;left:{sx / sub_w * 100:.2f}%;top:{sy / sub_h * 100:.2f}%;'
                        f'width:{sw / sub_w * 100:.2f}%;height:{sh / sub_h * 100:.2f}%;padding:1.5px">'
                        f'<div style="width:100%;height:100%;border-radius:3px;overflow:hidden;'
                        f'background:color-mix(in srgb,var(--{col}) {MIX[k] + 12}%,var(--surface));'
                        f'display:flex;align-items:center;justify-content:center;text-align:center;padding:2px">'
                        f'<span style="font-size:14px;font-weight:500;color:var(--ink);line-height:1.2;'
                        f'overflow:hidden;overflow-wrap:break-word;display:-webkit-box;'
                        f'-webkit-line-clamp:{s_max_lines};-webkit-box-orient:vertical">'
                        f'{esc(sn)} <span style="font-weight:600">{sp:g}%</span></span>'
                        f'</div></div>')
                sub_html = f'<div style="position:absolute;left:0;top:{header_pct}%;width:100%;height:{100 - header_pct}%">{sub_cells}</div>'

        # Same height-derived line count as sub-cells above, computed against the header area only
        # (header_pct of rh) when sub-cells actually render - otherwise a tall cell's label could compute
        # more lines than fit before the sub-cells start, visually colliding with them.
        line_h = 15 * 1.3
        label_h = (rh * header_pct / 100) if sub_html else rh
        max_lines = max(1, int((label_h - 12 - 8) // line_h))
        label = (f'<div style="font-size:15px;font-weight:500;color:{TH_ON[col]};line-height:1.3;'
                 f'overflow:hidden;overflow-wrap:break-word;display:-webkit-box;'
                 f'-webkit-line-clamp:{max_lines};-webkit-box-orient:vertical">'
                 f'{esc(name)} <span style="font-weight:600">{share}%</span></div>')

        cells.append(
            f'<div data-theme="{esc(name)}" style="position:absolute;left:{rx / w * 100:.2f}%;top:{ry / h * 100:.2f}%;'
            f'width:{rw / w * 100:.2f}%;height:{rh / h * 100:.2f}%;padding:1.5px">'
            f'<div style="width:100%;height:100%;border-radius:5px;overflow:hidden;position:relative;'
            f'background:var(--{col})">'
            f'<div style="position:absolute;left:10px;top:12px;right:8px">{label}</div>'
            f'{sub_html}</div></div>')
    return f'<div style="position:relative;width:100%;height:{h}px">{"".join(cells)}</div>'


def f_treemap(data: ReportData):
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
        shapes.append(f'<path d="{wedge(cx, cy, hole, r1, a0, a1)}" style="fill:var(--{col});stroke:var(--surface);stroke-width:3"/>')
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
        tbl += (f'<div style="display:flex;align-items:center;gap:10px;height:44px;border-top:1px solid var(--line);font-size:15px">'
                f'<span style="width:12px;height:12px;border-radius:3px;background:var(--{col})"></span><span style="flex:1;line-height:1.2">{esc(name)}</span>'
                f'<span style="width:72px;text-align:right;font-weight:600">{ng}%</span><span style="width:72px;text-align:right">{nu}%</span><span style="width:72px;text-align:right">{ps}%</span></div>')
    def sw(c, t):
        return f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:20px;font-size:14px;color:var(--muted)"><span style="width:14px;height:14px;border-radius:3px;background:{c}"></span>{t}</span>'
    tbl += f'<div style="margin-top:20px">{sw("var(--neg)", "Negative")}{sw("var(--neu)", "Neutral")}{sw("var(--pos)", "Positive")}</div></div>'
    inner = (f'<div style="display:flex;gap:40px;align-items:flex-start">'
             f'<div style="flex:1 1 320px;max-width:{W}px;aspect-ratio:1">{diagram}</div>{tbl}</div>')
    return frame("Which themes sound negative or positive?", "Inner ring is the theme. Outer ring splits each theme by tone.", inner, 800)

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
    W, H = 1084, 620
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
    R_ = [[M[i] * tones[names[i]][t] / 100 for i in range(nt)] for t in range(3)]
    RT = [sum(r) for r in R_]
    s = (560 - (nt - 1) * 12) / tot
    xl, xm, xr, nw = 170, 520, 900, 14
    y0l = (H - (tot * s + (nb - 1) * 36)) / 2
    y0m = (H - (tot * s + (nt - 1) * 12)) / 2
    y0r = y0l
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
    return frame("Who says what, and how do they feel?", "Answers flow from score group to theme to tone. Band height is number of answers.", "".join(o), 860)

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
    W, Hh = 1084, 620
    px0, pw, py0, ph = 60, 960, 40, 520
    o = [f'<svg width="{W}" height="{Hh}" viewBox="0 0 {W} {Hh}" role="img" aria-label="Map of answers: each dot is about 50 answers, placed near answers with similar wording">']
    sel = data.selected_theme
    labels = ""
    tip = ""
    for name, share, sent, cnt, col in rows(data):
        g = f'<g style="opacity:{1 if name == sel else DIM}">'
        n = round(share * 9.5)
        if name not in bub:
            pts = [(px0 + rnd.random() * pw, py0 + rnd.random() * ph) for _ in range(n)]
            cxy = None
        else:
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
    return frame("What does the whole pool of answers look like?", "Each dot is about 50 answers, placed near answers with similar wording. " + data.selected_theme + " is selected.", "".join(o), 820)


# ---------- registry and standalone rendering ----------
FRAMES = {
    "overview": f_overview, "sunburst": f_sunburst, "treemap": f_treemap, "icicle": f_icicle,
    "sentsun": f_sentsun, "rank": f_rank, "diverge": f_diverge, "mekko": f_mekko, "bubbles": f_bubbles,
    "sankey": f_sankey, "arc": f_arc, "map": f_map, "byScore": f_byscore, "heatmap": f_heatmap,
    "trend": f_trend, "quality": f_quality, "context": f_context, "tokens": f_tokens,
    "sunburst-mobile": f_sunburst_m, "rank-mobile": f_rank_m,
}

# Human-readable title per frame id, for the chart list API.
TITLES = {
    "overview": "Overview", "sunburst": "Themes, sunburst", "treemap": "Themes, treemap", "icicle": "Themes, icicle",
    "sentsun": "Sentiment sunburst", "rank": "Rank themes", "diverge": "Diverging sentiment", "mekko": "Sentiment marimekko",
    "bubbles": "Theme similarity", "sankey": "Score to theme to tone", "arc": "Theme co-occurrence", "map": "Answer map",
    "byScore": "Themes by score group", "heatmap": "Themes by segment", "trend": "Trend over time", "quality": "Answer quality",
    "context": "Question context", "tokens": "Design tokens", "sunburst-mobile": "Themes, sunburst (mobile)",
    "rank-mobile": "Rank themes (mobile)",
}

def render_parts(frame_id: str, data: ReportData | None = None):
    """Return (body_html, width, height) for a frame. data defaults to the EV sample."""
    if data is None:
        from .fixtures.ev_sample import EV
        data = EV
    return FRAMES[frame_id](data)

def render(frame_id: str, data: ReportData | None = None) -> str:
    body, w, h = render_parts(frame_id, data)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>[{esc(frame_id)}]</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost:wght@300;400;500;600&amp;display=swap">
<style>{CSS}html,body{{background:#f2f7f6}}</style></head>
<body><div class="v" style="width:{w}px;min-height:{h}px;max-width:100%;margin:0 auto;position:relative">{body}</div></body></html>"""

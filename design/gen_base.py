import html, math, random, json, os

ROOT = "/private/tmp/claude-501/-Users-shashikamihiranga-Desktop-Open-Ended-Response-Visualation/b43e4e41-12a4-427b-a057-edeefdfe52a1/scratchpad/verbatim"
OUT = ROOT + "/project"

def esc(s): return html.escape(str(s), quote=False)
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

# ---------- data ----------
THEMES = [
    ("Cost", 30, -0.05, 14258, "t1"),
    ("Charging", 26, -0.20, 12357, "t2"),
    ("Range and battery", 16, -0.10, 7604, "t3"),
    ("Not needed", 10, -0.02, 4753, "t4"),
    ("Doubts about the technology", 8, -0.15, 3802, "t5"),
    ("Availability", 5, 0.10, 2376, "t6"),
    ("Uncertainty", 3, 0.05, 1426, "t7"),
    ("Other", 2, -0.03, 950, "other"),
]
TCOL = {n: c for n, _, _, _, c in THEMES}
TH_ON = {"t1": "#ffffff", "t2": "#ffffff", "t3": "#12303a", "t4": "#12303a", "t5": "#ffffff",
         "t6": "#12303a", "t7": "#12303a", "other": "#12303a"}
SUBS = {
    "Cost": [("Upfront price", 15), ("Battery replacement cost", 7.5), ("Insurance and running costs", 7.5)],
    "Charging": [("No home charger", 11.7), ("Too few public chargers", 9.1), ("Slow to charge", 5.2)],
    "Range and battery": [("Range anxiety", 9.6), ("Battery life", 6.4)],
    "Not needed": [("Current car is fine", 5.5), ("Barely drive", 2.5), ("Hybrid or petrol is enough", 2)],
    "Doubts about the technology": [("Too new", 4), ("Resale value", 4)],
    "Availability": [("Waiting lists", 3), ("No dealers nearby", 2)],
}
ANSWERED = 47525
OVERALL = -0.10
DIM = 0.28

def tone(s):
    d = s - OVERALL
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
    s = f'<div style="font-size:22px;font-weight:600;line-height:1.3">{esc(title)}</div>'
    if sub:
        s += f'<div style="font-size:15px;color:var(--muted);margin-top:2px">{esc(sub)}</div>'
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

def arc_label(cx, cy, rm, thick, a0, a1, name, pct, fs, color):
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
    lines = lines + [pct]
    x, y = polar(cx, cy, rm, mid)
    rot = mid if not (90 < mid < 270) else mid + 180
    n = len(lines)
    items = ""
    for i, t in enumerate(lines):
        dy = (i - (n - 1) / 2) * lh
        wt = 500 if i < n_name else (600 if n_name else 500)
        items += (f'<text x="0" y="{dy:.1f}" text-anchor="middle" dominant-baseline="central" '
                  f'style="font-size:{fs}px;font-weight:{wt};fill:{color}">{esc(t)}</text>')
    return f'<g transform="translate({x:.1f} {y:.1f}) rotate({rot:.1f})">{items}</g>'

def sunburst(W, H, cx, cy, R, fs_in, fs_out, selected=None, hover=None, external=True, cfs=34, csub=15):
    hole, r1, r2 = 0.36 * R, 0.68 * R, 0.70 * R
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Two-ring sunburst: themes inside, sub-themes outside">']
    a = 0.0
    ext = []
    for name, share, sent, cnt, col in THEMES:
        span = share * 3.6
        a0, a1 = a, a + span
        a = a1
        op = 1 if selected in (None, name) else DIM
        g = [f'<g style="opacity:{op}">']
        g.append(f'<path d="{wedge(cx, cy, hole, r1, a0, a1)}" style="fill:var(--{col});stroke:var(--surface);stroke-width:3"/>')
        if external and span < 30:
            ext.append((name, share, cnt, col, (a0 + a1) / 2))
        else:
            g.append(arc_label(cx, cy, (hole + r1) / 2, r1 - hole, a0, a1, name, f"{share}%", fs_in, TH_ON[col]))
        aa = a0
        for k, (sn, sp) in enumerate(SUBS.get(name, [])):
            sspan = sp * 3.6
            mixp = [46, 36, 27][k]
            g.append(f'<path d="{wedge(cx, cy, r2, R, aa, aa + sspan)}" style="fill:color-mix(in srgb,var(--{col}) {mixp}%,var(--surface));stroke:var(--surface);stroke-width:2.5"/>')
            g.append(arc_label(cx, cy, (r2 + R) / 2, R - r2, aa, aa + sspan, sn, f"{sp:g}%", fs_out, "var(--ink)"))
            aa += sspan
        if hover == name:
            g.append(f'<path d="{wedge(cx, cy, hole, R, a0, a1)}" style="fill:none;stroke:var(--ink);stroke-width:2.5"/>')
        if external and span < 30:
            pass
        g.append("</g>")
        o.append("".join(g))
    # external callouts for small themes (desktop)
    if external:
        pos = {
            "Doubts about the technology": (160, 144, ["Doubts about", "the technology", "8%"]),
            "Availability": (250, 78, ["Availability", "5%"]),
            "Uncertainty": (306, 40, ["Uncertainty 3%"]),
        }
        for name, share, cnt, col, mid in ext:
            op = 1 if selected in (None, name) else DIM
            px, py = polar(cx, cy, R + 2, mid)
            if name in pos:
                ex, ey, lines = pos[name]
                lh = 16
                n = len(lines)
                t = f'<g style="opacity:{op}"><line x1="{ex + 5}" y1="{ey}" x2="{px:.1f}" y2="{py:.1f}" style="stroke:var(--muted);stroke-width:1"/>'
                t += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" style="fill:var(--{col})"/>'
                for i, ln in enumerate(lines):
                    dy = (i - (n - 1) / 2) * lh
                    wt = 600 if i == n - 1 and n > 1 else 500
                    t += T(ex, ey + dy, ln, 14, wt, "var(--ink)", "end")
                t += "</g>"
                o.append(t)
            else:  # Other callout
                t = f'<g style="opacity:{op}"><polyline points="{px:.1f},{py:.1f} {px + 14:.1f},{py - 30:.1f} {px + 26:.1f},{py - 30:.1f}" style="fill:none;stroke:var(--muted);stroke-width:1"/>'
                t += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" style="fill:var(--other)"/>'
                t += T(px + 32, py - 40, "Other 950 (2%)", 14, 600)
                t += T(px + 32, py - 22, "Folded in: answers too rare for a theme", 13, 400, "var(--muted)")
                t += "</g>"
                o.append(t)
    o.append(T(cx, cy - csub * 0.9, "47,525", cfs, 300, "var(--ink)", "middle"))
    o.append(T(cx, cy + cfs * 0.45, "answered", csub, 400, "var(--muted)", "middle"))
    o.append("</svg>")
    return "".join(o)

def theme_rows(selected=None, hover=None, mobile=False):
    rh = 38 if mobile else 40
    fs = 14 if mobile else 15
    o = [f'<div style="display:flex;align-items:center;gap:10px;height:30px;padding:0 10px;font-size:13px;font-weight:500;color:var(--muted)">'
         f'<span style="width:12px"></span><span style="flex:1">Theme</span><span style="width:{54 if mobile else 64}px;text-align:right">Answers</span><span style="width:{40 if mobile else 44}px;text-align:right">Share</span></div>']
    for name, share, sent, cnt, col in THEMES:
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
            for k, (sn, sp) in enumerate(SUBS.get(name, [])):
                mixp = [46, 36, 27][k]
                o.append(f'<div style="display:flex;align-items:center;gap:10px;height:34px;padding:0 10px 0 30px;font-size:{fs - 1}px">'
                         f'<span style="width:10px;height:10px;border-radius:2px;background:color-mix(in srgb,var(--{col}) {mixp + 20}%,var(--surface));flex:none"></span>'
                         f'<span style="flex:1;line-height:1.2">{esc(sn)}</span>'
                         f'<span style="width:{54 if mobile else 64}px;text-align:right">{fmt(round(sp / 100 * ANSWERED))}</span>'
                         f'<span style="width:{40 if mobile else 44}px;text-align:right;color:var(--muted)">{sp:g}%</span></div>')
    return "".join(o)

def f_sunburst():
    def panel(cap, selected, hover):
        return (f'<div style="font-size:14px;font-weight:500;color:var(--muted);margin:0 0 10px">{esc(cap)}</div>'
                f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:24px;display:flex;gap:24px;height:630px">'
                f'<div style="flex:none">{sunburst(640, 580, 380, 300, 245, 14, 12.5, selected, hover)}</div>'
                f'<div style="flex:1;min-width:0">{theme_rows(selected, hover)}</div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What are the themes?", "Why haven\'t you bought an electric vehicle yet?")}'
            f'<div style="height:24px"></div>'
            + panel("Default, hover on Range and battery", None, "Range and battery")
            + '<div style="height:40px"></div>'
            + panel("Charging selected, others dimmed", "Charging", None) + "</div>")
    return body, 1180, 1640

def f_sunburst_m():
    body = (f'<div style="padding:24px 16px">{hdr("What are the themes?")}'
            f'<div style="height:16px"></div>'
            f'<div style="background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:12px 0 0">'
            f'{sunburst(358, 340, 179, 172, 150, 11, 10.5, None, None, False, 24, 12)}'
            f'<div style="padding:0 16px 12px">{theme_rows(None, None, True)}'
            f'<div style="margin-top:14px;font-size:13px;color:var(--muted);line-height:1.4">Other 950 (2%). Folded in: answers too rare for a theme.</div></div></div></div>')
    return body, 390, 960

# ---------- overview ----------
def f_overview():
    stats = [("Responses", "50,000", ""), ("Answered", "95%", "(2,475 blank, n/a or don't know)"),
             ("Typical length", "8 words", ""), ("Average sentiment", "-0.10", "Negative is expected for this question"),
             ("Themes", "7", "(17 sub-themes)")]
    st = '<div style="display:flex;margin-top:36px">'
    for i, (l, n, note) in enumerate(stats):
        bd = "border-left:1px solid var(--line);padding-left:24px;" if i else ""
        st += (f'<div style="flex:1;{bd}padding-right:16px"><div style="font-size:14px;font-weight:500;color:var(--muted)">{esc(l)}</div>'
               f'<div style="font-size:54px;font-weight:300;line-height:1.15;margin:4px 0 6px">{esc(n)}</div>'
               f'<div style="font-size:14px;color:var(--muted);line-height:1.4;min-height:40px">{esc(note)}</div></div>')
    st += "</div>"
    sent = ["Cost is the largest theme at 30% of answers, led by \"Upfront price\".",
            "Charging carries the most negative wording (-0.20 against -0.10 overall).",
            "Age group \"65+\" mentions Not needed 2.6 times as often as the average respondent."]
    ws = "".join(f'<div style="padding:20px 0;border-top:1px solid var(--line);font-size:24px;font-weight:300;line-height:1.35">{esc(s)}</div>' for s in sent)
    body = (f'<div style="padding:56px 48px">{hdr("How big, how clean, what's notable".replace("what's","what\'s"), "Why haven\'t you bought an electric vehicle yet?")}'
            f'{st}<div style="margin-top:56px;font-size:22px;font-weight:600;margin-bottom:12px">What stands out</div>'
            f'<div style="border-bottom:1px solid var(--line);max-width:960px">{ws}</div></div>')
    return body, 1180, 680

# ---------- rank ----------
def rank_rows(mobile=False, selected=None, hover=None):
    o = ""
    for name, share, sent, cnt, col in THEMES:
        sel = name == selected
        op = DIM if (selected and not sel) else 1
        bg = "background:var(--surface);" if (name == hover or sel) else ""
        ring = "outline:2px solid var(--ink);outline-offset:-2px;" if sel else ""
        if mobile:
            bw = share / 30 * 236
            o += (f'<div style="padding:10px 12px;border-radius:8px;{bg}{ring}opacity:{op}">'
                  f'<div style="display:flex;justify-content:space-between;font-size:15px;font-weight:500"><span>{esc(name)}</span>'
                  f'<span style="font-weight:400;color:var(--muted)">{sent:+.2f}</span></div>'
                  f'<div style="display:flex;align-items:center;gap:10px;margin-top:6px"><div style="width:{bw:.0f}px;height:22px;border-radius:3px;background:{tone(sent)};flex:none"></div>'
                  f'<div style="line-height:1.15"><div style="font-size:16px;font-weight:600">{share}%</div><div style="font-size:12px;color:var(--muted)">{fmt(cnt)}</div></div></div></div>')
        else:
            bw = share / 30 * 560
            o += (f'<div style="display:flex;align-items:center;height:64px;padding:0 16px;border-radius:8px;{bg}{ring}opacity:{op}">'
                  f'<div style="width:250px;font-size:17px;font-weight:500;flex:none">{esc(name)}</div>'
                  f'<div style="flex:1;display:flex;align-items:center;gap:14px"><div style="width:{bw:.0f}px;height:28px;border-radius:3px;background:{tone(sent)}"></div>'
                  f'<div style="line-height:1.2"><div style="font-size:18px;font-weight:600">{share}%</div><div style="font-size:13px;color:var(--muted)">{fmt(cnt)}</div></div></div>'
                  f'<div style="width:90px;text-align:right;font-size:17px">{sent:+.2f}</div></div>')
    return o

def rank_legend():
    def sw(c, t):
        return (f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:22px;font-size:14px;color:var(--muted)">'
                f'<span style="width:16px;height:16px;border-radius:3px;background:{c}"></span>{t}</span>')
    return (sw("var(--neg)", "More negative than average") + sw("var(--neu)", "About average") + sw("var(--pos)", "Milder than average"))

def f_rank():
    body = (f'<div style="padding:56px 48px"><div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<div>{hdr("What should we fix first?", "Bar length is share of answered. Tint compares each theme with the overall average (-0.10).")}</div>'
            f'{seg(["Themes", "Sub-themes"], "Themes")}</div>'
            f'<div style="margin-top:22px;display:flex;flex-wrap:wrap">{rank_legend()}</div>'
            f'<div style="display:flex;padding:22px 16px 8px;font-size:13px;font-weight:500;color:var(--muted)"><div style="width:250px">Theme</div><div style="flex:1">Share of answered, with count</div><div style="width:90px;text-align:right">Avg sentiment</div></div>'
            f'{rank_rows(False, None, "Charging")}</div>')
    return body, 1180, 860

def f_rank_m():
    body = (f'<div style="padding:24px 16px">{hdr("What should we fix first?")}'
            f'<div style="margin-top:14px">{seg(["Themes", "Sub-themes"], "Themes", None, True)}</div>'
            f'<div style="margin-top:14px;display:flex;flex-wrap:wrap;row-gap:6px">{rank_legend()}</div>'
            f'<div style="margin-top:12px;font-size:13px;color:var(--muted)">Charging selected, others dimmed</div>'
            f'<div style="margin-top:6px">{rank_rows(True, "Charging")}</div></div>')
    return body, 390, 960

# ---------- diverge ----------
DIV = [("Cost", 38, 40, 22), ("Charging", 52, 33, 15), ("Range and battery", 44, 38, 18), ("Not needed", 30, 45, 25),
       ("Doubts about the technology", 47, 36, 17), ("Availability", 28, 40, 32), ("Uncertainty", 25, 45, 30), ("Other", 30, 40, 30)]

def f_diverge():
    s = 5.2; cx = 600; rh = 60; y0 = 64
    o = [f'<svg width="1084" height="{y0 + rh * 8 + 10}" viewBox="0 0 1084 {y0 + rh * 8 + 10}" role="img" aria-label="Diverging sentiment bars">']
    o.append(T(cx - 160, 20, "Negative", 14, 500, "var(--muted)", "end"))
    o.append(T(cx, 20, "Neutral", 14, 500, "var(--muted)", "middle"))
    o.append(T(cx + 160, 20, "Positive", 14, 500, "var(--muted)", "start"))
    o.append(T(1084, 20, "negative / positive", 14, 500, "var(--muted)", "end"))
    for i, (name, ng, nu, ps) in enumerate(DIV):
        y = y0 + i * rh
        if name == "Charging":
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
    o.append(f'<line x1="{cx}" y1="{y0 - 4}" x2="{cx}" y2="{y0 + rh * 8}" style="stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3"/>')
    o.append("</svg>")
    body = (f'<div style="padding:56px 48px">{hdr("Which themes sound negative or positive?", "Share of each theme\'s answers with negative, neutral and positive wording.")}'
            f'<div style="height:24px"></div>{"".join(o)}</div>')
    return body, 1180, 780

# ---------- bubbles ----------
BUB = {"Cost": (0.30, 0.35), "Charging": (0.68, 0.50), "Range and battery": (0.82, 0.25), "Not needed": (0.15, 0.75),
       "Doubts about the technology": (0.45, 0.80), "Availability": (0.50, 0.15), "Uncertainty": (0.28, 0.65)}

def f_bubbles():
    px0, pw, py0, ph = 60, 960, 40, 520
    o = ['<svg width="1084" height="620" viewBox="0 0 1084 620" role="img" aria-label="Theme similarity map">']
    hov = None
    for name, share, sent, cnt, col in THEMES:
        if name not in BUB:
            continue
        x = px0 + BUB[name][0] * pw
        y = py0 + BUB[name][1] * ph
        r = 12.5 * math.sqrt(share)
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" style="fill:var(--{col});stroke:var(--bg);stroke-width:2"/>')
        o.append(T(x, y + r + 16, name, 14, 500, "var(--ink)", "middle"))
        o.append(T(x, y + r + 34, f"{share}%", 14, 400, "var(--muted)", "middle"))
        if name == "Range and battery":
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 6:.1f}" style="fill:none;stroke:var(--ink);stroke-width:2"/>')
            tx, ty = x + r + 12, y - 62
            o.append(f'<rect x="{tx - 100:.1f}" y="{ty - 28:.1f}" width="200" height="52" rx="8" style="fill:var(--ink)"/>')
            o.append(T(tx, ty - 10, "Range and battery", 14, 600, "var(--bg)", "middle"))
            o.append(T(tx, ty + 10, "16% of answered, -0.10", 13, 400, "var(--bg)", "middle"))
    o.append("</svg>")
    body = (f'<div style="padding:56px 48px">{hdr("How do themes relate?", "Circle area is share. Distance means similar wording.")}'
            f'<div style="height:16px"></div>{"".join(o)}</div>')
    return body, 1180, 800

# ---------- byScore ----------
BYS = [("Low (0-6)", [27, 25, 15, 18, 9, 2, 2, 2], -0.14, 16000),
       ("Middle (7-8)", [33, 28, 17, 3, 7, 7, 3, 2], -0.10, 19000),
       ("High (9-10)", [30, 24, 18, 1, 6, 14, 5, 2], -0.03, 12525)]
SHORT = ["Cost", "Charging", "Range and battery", "Not needed", "Doubts about the technology", "Availability", "Uncertainty", "Other"]

def key_row():
    o = '<div style="display:flex;flex-wrap:wrap;gap:8px 24px">'
    for name, share, sent, cnt, col in THEMES:
        o += (f'<span style="display:inline-flex;align-items:center;gap:8px;font-size:14px">'
              f'<span style="width:12px;height:12px;border-radius:3px;background:var(--{col})"></span>{esc(name)}</span>')
    return o + "</div>"

def f_byscore():
    rows = ""
    for lab, vals, sent, n in BYS:
        segs = ""
        for i, v in enumerate(vals):
            col = THEMES[i][4]
            wpx = v * 7
            name = SHORT[i]
            show_name = wpx >= len(name) * 7.6 + 16
            txt = f"{v}%" if v >= 5 else f"{v}"
            inner = ""
            if show_name:
                inner = f'<div style="font-size:13px;font-weight:500;line-height:1.2">{esc(name)}</div><div style="font-size:16px;font-weight:600;line-height:1.2">{txt}</div>'
            else:
                inner = f'<div style="font-size:{15 if v >= 5 else 11}px;font-weight:600">{txt}</div>'
            segs += (f'<div style="flex:0 0 {v}%;background:var(--{col});color:{TH_ON[col]};border-right:2px solid var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden">{inner}</div>')
        pp = min(55, abs(sent) / 0.2 * 55)
        rows += (f'<div style="display:flex;align-items:center;padding:20px 0;border-top:1px solid var(--line)">'
                 f'<div style="width:200px;flex:none"><div style="font-size:18px;font-weight:600">{lab}</div><div style="font-size:14px;color:var(--muted)">{fmt(n)} answers</div></div>'
                 f'<div style="width:700px;height:66px;display:flex;border-radius:6px;overflow:hidden;flex:none">{segs}</div>'
                 f'<div style="margin-left:32px;display:inline-flex;align-items:baseline;gap:8px;padding:6px 16px;border:1px solid var(--line);border-radius:999px;background:color-mix(in srgb,var(--neg) {pp:.0f}%,var(--surface))">'
                 f'<span style="font-size:13px;color:var(--ink)">avg sentiment</span><span style="font-size:17px;font-weight:600">{sent:+.2f}</span></div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What does each score group talk about?", "Theme mix by Likelihood to buy. Each bar adds to 100%.")}'
            f'<div style="height:24px"></div><div style="border-bottom:1px solid var(--line)">{rows}</div>'
            f'<div style="margin-top:24px">{key_row()}</div></div>')
    return body, 1180, 660

# ---------- heatmap ----------
AGES = [("18-24", 5100), ("25-34", 9800), ("35-44", 10600), ("45-54", 9300), ("55-64", 7200), ("65+", 5500)]
HM = [("Cost", 30, [40, 38, 32, 27, 24, 20]), ("Charging", 26, [30, 32, 31, 27, 22, 18]),
      ("Range and battery", 16, [13, 14, 16, 17, 19, 20]), ("Not needed", 10, [4, 5, 8, 11, 17, 26]),
      ("Doubts about the technology", 8, [6, 7, 8, 9, 10, 10])]

def ramp_mix(v, overall):
    r = v / overall
    if r <= 1:
        return 8 + 22 * r
    return 30 + 60 * min(1, (r - 1) / 1.5)

def f_heatmap():
    g = '<div style="display:grid;grid-template-columns:250px repeat(6,minmax(0,1fr));gap:4px">'
    g += '<div></div>'
    for a, n in AGES:
        g += f'<div style="padding:0 0 8px;text-align:center"><div style="font-size:16px;font-weight:500">{a}</div><div style="font-size:13px;color:var(--muted)">n={fmt(n)}</div></div>'
    for name, ov, vals in HM:
        g += f'<div style="display:flex;flex-direction:column;justify-content:center;padding-right:12px"><div style="font-size:16px;font-weight:500;line-height:1.25">{esc(name)}</div><div style="font-size:13px;color:var(--muted)">overall {ov}%</div></div>'
        for j, v in enumerate(vals):
            m = ramp_mix(v, ov)
            tc = "var(--on-ramp)" if m >= 55 else "var(--ink)"
            hov = (name == "Not needed" and j == 5)
            ring = "outline:2px solid var(--ink);outline-offset:2px;" if hov else ""
            tip = ""
            if hov:
                tip = ('<div style="position:absolute;left:50%;bottom:calc(100% + 12px);transform:translateX(-72%);width:250px;padding:10px 14px;border-radius:8px;background:var(--ink);color:var(--bg);font-size:14px;line-height:1.35;z-index:3">'
                       'Age group "65+" mentions Not needed 2.6 times as often as the average respondent.</div>')
            g += (f'<div style="position:relative;height:66px;border-radius:4px;background:color-mix(in srgb,var(--ramp) {m:.0f}%,var(--surface));color:{tc};display:flex;align-items:center;justify-content:center;font-size:19px;font-weight:{600 if m >= 55 else 500};{ring}">{v}%{tip}</div>')
    g += "</div>"
    steps = "".join(f'<span style="width:34px;height:14px;background:color-mix(in srgb,var(--ramp) {m}%,var(--surface));display:inline-block"></span>' for m in (10, 30, 50, 70, 90))
    legend = (f'<div style="margin-top:28px;display:flex;align-items:center;gap:12px;font-size:14px;color:var(--muted)">'
              f'<span>At or below overall share</span><span style="display:inline-flex;gap:2px">{steps}</span><span>Above overall share</span></div>')
    body = (f'<div style="padding:56px 48px">{hdr("Who raises what?", "Share of each age group\'s answers. Darker means above the overall share.")}'
            f'<div style="height:64px"></div>{g}{legend}</div>')
    return body, 1180, 700

# ---------- trend ----------
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def series(a, b, noise, seed):
    rnd = random.Random(seed)
    out = []
    for i in range(12):
        base = a + (b - a) * i / 11
        n = 0 if i in (0, 11) else rnd.uniform(-noise, noise)
        out.append(base + n)
    return out

def f_trend():
    S = [("Cost", "t1", series(26, 34, 1.1, 3)), ("Charging", "t2", series(33, 22, 1.1, 5)),
         ("Range and battery", "t3", series(16, 16, 0.5, 7)), ("Not needed", "t4", series(10, 10, 0.4, 11)),
         ("Doubts about the technology", "t5", series(8, 8, 0.3, 13))]
    sent = series(-0.14, -0.07, 0.012, 17)
    x0, x1 = 56, 830
    dx = (x1 - x0) / 11
    ty0, ty1 = 34, 394      # 0..40 %
    by0, by1 = 462, 622     # 0 .. -0.20
    def X(i): return x0 + dx * i
    def Y(v): return ty1 - v / 40 * (ty1 - ty0)
    def YS(v): return by0 + (0 - v) / 0.2 * (by1 - by0)
    o = ['<svg width="1084" height="672" viewBox="0 0 1084 672" role="img" aria-label="Theme share and average sentiment by month">']
    o.append(T(0, 12, "Share of answers", 15, 600))
    for g in (0, 10, 20, 30, 40):
        o.append(f'<line x1="{x0}" y1="{Y(g):.1f}" x2="{x1}" y2="{Y(g):.1f}" style="stroke:var(--line);stroke-width:1"/>')
        o.append(T(x0 - 10, Y(g), f"{g}%", 13, 400, "var(--muted)", "end"))
    HV = 8
    for name, col, vals in S:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        o.append(f'<polyline points="{pts}" style="fill:none;stroke:var(--{col});stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round"/>')
        o.append(f'<circle cx="{X(11):.1f}" cy="{Y(vals[11]):.1f}" r="4" style="fill:var(--{col})"/>')
        o.append(T(x1 + 16, Y(vals[11]) - 0, f"{name} {vals[11]:.0f}%", 14, 600, "var(--ink)"))
        o.append(f'<circle cx="{X(0):.1f}" cy="{Y(vals[0]):.1f}" r="4" style="fill:var(--{col})"/>')
        o.append(T(X(0) + 8, Y(vals[0]) - 12, f"{vals[0]:.0f}%", 13, 500, "var(--muted)"))
    # hover crosshair
    o.append(f'<line x1="{X(HV):.1f}" y1="{ty0 - 6}" x2="{X(HV):.1f}" y2="{by1}" style="stroke:var(--ink);stroke-width:1;stroke-dasharray:3 3"/>')
    for name, col, vals in S:
        o.append(f'<circle cx="{X(HV):.1f}" cy="{Y(vals[HV]):.1f}" r="4.5" style="fill:var(--surface);stroke:var(--{col});stroke-width:2.5"/>')
        o.append(T(X(HV) + 10, Y(vals[HV]) - 11, f"{vals[HV]:.1f}%", 13, 600, "var(--ink)"))
    # bottom
    o.append(T(0, by0 - 28, "Average sentiment", 15, 600))
    for g in (0, -0.1, -0.2):
        o.append(f'<line x1="{x0}" y1="{YS(g):.1f}" x2="{x1}" y2="{YS(g):.1f}" style="stroke:var(--line);stroke-width:1"/>')
        o.append(T(x0 - 10, YS(g), f"{g:.2f}" if g else "0.00", 13, 400, "var(--muted)", "end"))
    pts = " ".join(f"{X(i):.1f},{YS(v):.1f}" for i, v in enumerate(sent))
    o.append(f'<polyline points="{pts}" style="fill:none;stroke:var(--ink);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round"/>')
    o.append(f'<circle cx="{X(0):.1f}" cy="{YS(sent[0]):.1f}" r="4" style="fill:var(--ink)"/>')
    o.append(T(X(0) + 8, YS(sent[0]) - 14, f"{sent[0]:.2f}", 13, 500, "var(--muted)"))
    o.append(f'<circle cx="{X(11):.1f}" cy="{YS(sent[11]):.1f}" r="4" style="fill:var(--ink)"/>')
    o.append(T(x1 + 16, YS(sent[11]), f"Average sentiment {sent[11]:.2f}", 14, 600))
    o.append(f'<circle cx="{X(HV):.1f}" cy="{YS(sent[HV]):.1f}" r="4.5" style="fill:var(--surface);stroke:var(--ink);stroke-width:2.5"/>')
    o.append(T(X(HV) + 10, YS(sent[HV]) - 12, f"{sent[HV]:.2f}", 13, 600))
    for i, m in enumerate(MONTHS):
        o.append(T(X(i), by1 + 26, m, 13, 500 if i == HV else 400, "var(--ink)" if i == HV else "var(--muted)", "middle"))
    o.append("</svg>")
    body = (f'<div style="padding:56px 48px">{hdr("What's rising or fading?".replace("What's", "What\'s"), "Monthly, January to December.")}'
            f'<div style="height:24px"></div>{"".join(o)}</div>')
    return body, 1180, 880

# ---------- freq ----------
OCC = [("Teacher", 9.3, True), ("Nurse", 6.6, False), ("Software engineer", 4.8, True), ("Accountant", 4.0, False),
       ("Sales assistant", 3.3, False), ("Manager", 2.9, False), ("Retail worker", 2.7, True), ("Student", 2.1, False),
       ("Electrician", 1.9, False), ("Retired", 1.8, False)]

def f_freq():
    rows = ""
    for i, (n, p, merged) in enumerate(OCC):
        bw = p / 9.3 * 560
        cnt = round(p / 100 * 47973)
        note = '<span style="font-size:13px;color:var(--muted);margin-left:16px">3 spellings merged</span>' if merged else ""
        bg = "background:var(--surface);" if n == "Nurse" else ""
        rows += (f'<div style="display:flex;align-items:center;height:52px;padding:0 16px;border-radius:8px;{bg}">'
                 f'<div style="width:220px;font-size:17px;font-weight:500;flex:none">{n}</div>'
                 f'<div style="flex:1;display:flex;align-items:center;gap:14px"><div style="width:{bw:.0f}px;height:26px;border-radius:3px;background:var(--accent)"></div>'
                 f'<div style="line-height:1.2"><span style="font-size:17px;font-weight:600">{p}%</span> <span style="font-size:13px;color:var(--muted);margin-left:6px">{fmt(cnt)}</span>{note}</div></div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What did people say most?", "What is your occupation? 47,973 answered.")}'
            f'<div style="height:20px"></div>{rows}'
            f'<div style="margin-top:28px;padding-top:20px;border-top:1px solid var(--line);font-size:16px;color:var(--muted);max-width:820px">1,461 different answers after merging spelling and plural variants. The ten most common cover 39% of answers, and 41% of the distinct answers were given only once.</div></div>')
    return body, 1180, 860

# ---------- phrases ----------
PH = [("worried", 4909, -0.25), ("home charger", 3638, -0.16), ("not enough", 3068, -0.02), ("public charger", 2964, -0.24),
      ("too expensive", 2815, -0.03), ("long trips", 2113, -0.02), ("no driveway", 1911, -0.12), ("can't afford", 1455, -0.10),
      ("range anxiety", 1200, -0.11), ("battery life", 1020, -0.18), ("resale value", 724, 0.01), ("waiting list", 720, 0.10)]

def ph_tint(s):
    if s < -0.03:
        p = 12 + min(1, abs(s) / 0.25) * 40
        return f"color-mix(in srgb,var(--neg) {p:.0f}%,var(--surface))"
    if s > 0.03:
        p = 12 + min(1, s / 0.12) * 40
        return f"color-mix(in srgb,var(--pos) {p:.0f}%,var(--surface))"
    return "color-mix(in srgb,var(--neu) 30%,var(--surface))"

def f_phrases():
    chips = ""
    for p, c, s in PH:
        fs = 15 + c / 4909 * 19
        ring = "border:2px solid var(--ink);" if p == "public charger" else "border:1px solid var(--line);"
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
Q = [("No driveway so can't install a home charger", "Charging", "negative"),
     ("Not enough public chargers near me", "Charging", "negative"),
     ("Worried about resale value", "Doubts about the technology", "negative"),
     ("The upfront price is too high", "Cost", "neutral"),
     ("I barely drive, my current car is fine", "Not needed", "neutral"),
     ("Still weighing it up, need more information", "Uncertainty", "neutral"),
     ("I'd love one, but there's a long waiting list for the models I want", "Availability", "positive")]
SC = {"negative": "var(--neg)", "neutral": "var(--neu)", "positive": "var(--pos)"}

def f_quotes():
    chips = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:20px">'
    for name in ["All"] + [t[0] for t in THEMES if t[0] != "Other"]:
        if name == "All":
            st = "background:var(--accent);color:var(--on-accent);border:1px solid var(--accent);font-weight:600;"
            dot = ""
        else:
            hv = "background:var(--surface);" if name == "Charging" else ""
            st = f"border:1px solid var(--line);{hv}font-weight:500;"
            dot = f'<span style="width:9px;height:9px;border-radius:50%;background:var(--{TCOL[name]})"></span>'
        chips += f'<span style="display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;font-size:14px;{st}">{dot}{esc(name)}</span>'
    chips += "</div>"
    rows = ""
    for i, (q, th, sn) in enumerate(Q):
        bg = "background:var(--surface);" if i == 1 else ""
        rows += (f'<div style="display:flex;align-items:center;gap:20px;min-height:62px;padding:8px 16px;border-top:1px solid var(--line);border-radius:{8 if i == 1 else 0}px;{bg}">'
                 f'<div style="width:100px;flex:none;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)"><span style="width:11px;height:11px;border-radius:50%;background:{SC[sn]}"></span>{sn}</div>'
                 f'<div style="flex:1;font-size:19px;line-height:1.4">{esc(q)}</div>'
                 f'<div style="width:230px;flex:none;text-align:right;font-size:14px;font-weight:500;color:var(--muted)">{esc(th)}</div></div>')
    body = (f'<div style="padding:56px 48px">{hdr("What does it sound like?", "Verbatim answers, with their theme and tone.")}'
            f'<div style="margin-top:22px">{seg(["Most typical", "Random", "Most negative", "Most positive"], "Most typical", "Random")}</div>'
            f'{chips}<div style="height:24px"></div><div style="border-bottom:1px solid var(--line)">{rows}</div></div>')
    return body, 1180, 800

# ---------- quality ----------
BINS = [("1", 1900), ("2", 3800), ("3", 5700), ("4-5", 9500), ("6-8", 11400), ("9-12", 9500), ("13-20", 4300), ("21-40", 1100), ("41+", 300)]

def f_quality():
    base = 350; maxh = 270; bw = 100; gap = 20; x0 = 12
    o = ['<svg width="1084" height="440" viewBox="0 0 1084 440" role="img" aria-label="Histogram of answer length in words">']
    for i, (lab, c) in enumerate(BINS):
        h = c / 11400 * maxh
        x = x0 + i * (bw + gap)
        typ = lab == "6-8"
        fill = "var(--accent)" if typ else "color-mix(in srgb,var(--accent) 55%,var(--bg))"
        o.append(f'<rect x="{x}" y="{base - h:.1f}" width="{bw}" height="{h:.1f}" rx="3" style="fill:{fill}"/>')
        o.append(T(x + bw / 2, base - h - 14, fmt(c), 15, 600, "var(--ink)", "middle"))
        o.append(T(x + bw / 2, base + 22, lab, 15, 500, "var(--ink)", "middle"))
        if typ:
            o.append(T(x + bw / 2, base - h - 44, "Typical length 8 words", 14, 500, "var(--accent)", "middle"))
    o.append(f'<line x1="0" y1="{base}" x2="1084" y2="{base}" style="stroke:var(--ink);stroke-width:1"/>')
    o.append(T(542, base + 58, "Words per answer", 14, 500, "var(--muted)", "middle"))
    o.append("</svg>")
    notes = ["2,475 blank, said nothing or n/a, or said they did not know. These are left out of the themes.",
             "12% of answers repeat an earlier answer word for word.",
             "Sentiment comes from a word-based scorer built for English. It reads wording, not intent, and can miss sarcasm."]
    nt = '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:40px;margin-top:20px">' + "".join(
        f'<div style="border-top:1px solid var(--line);padding-top:14px;font-size:16px;line-height:1.55">{esc(n)}</div>' for n in notes) + "</div>"
    body = (f'<div style="padding:56px 48px">{hdr("Can I trust this?", "Answer length in words, for the 47,525 answers analysed.")}'
            f'<div style="height:40px"></div>{"".join(o)}{nt}</div>')
    return body, 1180, 880

# ---------- context ----------
def f_context():
    opts = ["reasons", "improvements", "experiences", "facts", "anything else", "opinions"]
    menu = ('<span style="position:absolute;left:-14px;top:calc(100% + 12px);width:270px;padding:6px;background:var(--surface);border:1px solid var(--line);border-radius:12px;z-index:5;'
            'font-size:18px;font-weight:400;line-height:1.3;display:block;text-align:left">')
    for o_ in opts:
        if o_ == "reasons":
            st = "background:color-mix(in srgb,var(--accent) 14%,var(--surface));color:var(--accent);font-weight:600;"
        elif o_ == "facts":
            st = "background:var(--bg);"
        else:
            st = ""
        menu += f'<span style="display:block;padding:10px 14px;border-radius:8px;{st}">{o_}</span>'
    menu += "</span>"
    ctl = "color:var(--accent);border-bottom:2px dotted var(--accent);"
    body = (f'<div style="padding:72px 80px">'
            f'<div style="font-size:48px;font-weight:300;line-height:1.25;max-width:1020px">This question asks for '
            f'<span style="position:relative;display:inline-block;{ctl}">reasons{menu}</span>, framed '
            f'<span style="{ctl}">negatively</span>, and answers run '
            f'<span style="{ctl}">a sentence or two</span>.</div>'
            f'<div style="margin-top:340px;font-size:19px;line-height:1.55;max-width:820px;color:var(--ink)">47,525 of 50,000 responses had an answer to analyse. Also found a score column (Likelihood to buy), a date column (Survey date, grouped by month), and a segment column (Age group).</div>'
            f'<details style="margin-top:36px;max-width:820px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)">'
            f'<summary style="display:flex;justify-content:space-between;align-items:center;padding:16px 0;font-size:18px;font-weight:500;list-style:none;cursor:pointer">How the charts were chosen<span style="font-size:24px;font-weight:300;color:var(--muted)">+</span></summary></details></div>')
    return body, 1180, 760

# ---------- tokens ----------
def f_tokens():
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


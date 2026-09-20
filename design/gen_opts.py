from gen_pages import *
import json as _j

SIDE = '<div style="flex:1;background:var(--bg);border-left:1px solid var(--line);display:flex;flex-direction:column;justify-content:center;padding:0 80px">{}</div>'
HEAD = '<div style="font-size:30px;font-weight:300;line-height:1.25;margin-top:28px;max-width:460px">{}</div><div style="font-size:16px;color:var(--muted);margin-top:8px;max-width:460px">{}</div>'

def with_side(content):
    body, w, h = f_signin()
    i = body.index('<div style="flex:1;background:var(--bg);border-left')
    return body[:i] + SIDE.format(content) + "</div>", w, h

def opt_a():
    svg = sunburst(500, 500, 250, 250, 225, 13, 11.5, None, None, False, 30, 14)
    svg = svg.replace(">47,525<", ">Every answer<").replace(">answered<", ">by theme<")
    svg = svg.replace("font-size:30px;font-weight:300", "font-size:20px;font-weight:300")
    return with_side(svg + HEAD.format("Read every answer in a minute, and trust what you see.", "Themes and sub-themes, straight from the text."))

def opt_b():
    rnd = random.Random(5)
    n = 24
    dests = ["t1"] * 8 + ["t2"] * 7 + ["t3"] * 5 + ["t4"] * 4
    rnd.shuffle(dests)
    names = {"t1": "Cost", "t2": "Charging", "t3": "Range and battery", "t4": "Not needed"}
    order = ["t1", "t2", "t3", "t4"]
    W, H = 500, 470
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Lines of text flowing into themes">']
    o.append(T(0, 8, "Open-ended answers", 14, 500, "var(--muted)"))
    o.append(T(W - 110, 8, "Themes", 14, 500, "var(--muted)"))
    y0, lh = 30, 17.5
    xs, xe = 118, 372
    gap = 14
    ends = {}
    y = 30
    for d in order:
        ends[d] = [y, 0]
        y += dests.count(d) * lh + gap
    for i, d in enumerate(dests):
        ys = y0 + i * lh + 6
        ln = rnd.uniform(60, 112)
        o.append(f'<rect x="{xs - ln:.1f}" y="{ys - 3:.1f}" width="{ln:.1f}" height="6" rx="3" style="fill:var(--muted);fill-opacity:.4"/>')
        ye = ends[d][0] + ends[d][1] * lh + 6
        ends[d][1] += 1
        mx = (xs + xe) / 2
        o.append(f'<path d="M{xs} {ys:.1f}C{mx} {ys:.1f} {mx} {ye:.1f} {xe} {ye:.1f}" style="fill:none;stroke:var(--{d});stroke-opacity:.55;stroke-width:6"/>')
    for d in order:
        top = ends[d][0]
        h = dests.count(d) * lh
        o.append(f'<rect x="{xe}" y="{top:.1f}" width="12" height="{h - 2:.1f}" rx="3" style="fill:var(--{d})"/>')
        o.append(T(xe + 24, top + h / 2 - 1, names[d], 15, 600))
    o.append("</svg>")
    return with_side("".join(o) + HEAD.format("From words to themes, in one pass.", "Bring an open question. Get back the pattern."))

def opt_c():
    Qs = [("Not enough public chargers near me", "Charging", "t2", False), ("The upfront price is too high", "Cost", "t1", False),
          ("No driveway so can't install a home charger", "Charging", "t2", True), ("Worried about resale value", "Doubts about the technology", "t5", False),
          ("I barely drive, my current car is fine", "Not needed", "t4", False)]
    rows = ""
    for q, th, c, hl in Qs:
        bg = "background:color-mix(in srgb,var(--accent) 10%,var(--surface));" if hl else ""
        op = 1 if hl else 0.55
        rows += (f'<div style="display:flex;align-items:center;gap:16px;padding:16px 16px;border-top:1px solid var(--line);border-radius:{10 if hl else 0}px;{bg}opacity:{op}">'
                 f'<span style="flex:1;font-size:21px;font-weight:{500 if hl else 300};line-height:1.3">{esc(q)}</span>'
                 f'<span style="display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:500;white-space:nowrap"><span style="width:10px;height:10px;border-radius:50%;background:var(--{c})"></span>{esc(th)}</span></div>')
    rows = f'<div style="max-width:500px;border-bottom:1px solid var(--line)">{rows}</div>'
    return with_side(rows + HEAD.format("Every voice, grouped into what it means.", "Real answers stay one click away from every chart."))

def rr(x, y, w, h, tl, tr, br, bl):
    return (f"M{x + tl:.1f} {y:.1f}H{x + w - tr:.1f}A{tr:.1f} {tr:.1f} 0 0 1 {x + w:.1f} {y + tr:.1f}V{y + h - br:.1f}"
            f"A{br:.1f} {br:.1f} 0 0 1 {x + w - br:.1f} {y + h:.1f}H{x + bl:.1f}A{bl:.1f} {bl:.1f} 0 0 1 {x:.1f} {y + h - bl:.1f}"
            f"V{y + tl:.1f}A{tl:.1f} {tl:.1f} 0 0 1 {x + tl:.1f} {y:.1f}Z")

def opt_d():
    W, H = 500, 400
    items = [("Cost", 30, "t1"), ("Charging", 26, "t2"), ("Range and battery", 16, "t3"), ("Not needed", 10, "t4"), ("Doubts about the technology", 8, "t5"), ("Availability", 5, "t6")]
    rects = squarify([(n, s) for n, s, _ in items], 0, 0, W, H)
    big = {"Cost": "br", "Charging": "tr", "Range and battery": "bl", "Not needed": "tr", "Doubts about the technology": "br", "Availability": "tl"}
    o = [f'<svg width="{W}" height="{H + 50}" viewBox="0 0 {W} {H + 50}" role="img" aria-label="Mosaic of themes, bigger block means more people"><defs>']
    geo = {}
    for n, s, c in items:
        x, y, w, h = rects[n]
        x += 3; y += 3; w -= 6; h -= 6
        r = min(w, h) * 0.5
        k = {"tl": 10, "tr": 10, "br": 10, "bl": 10}
        k[big[n]] = r
        geo[n] = (x, y, w, h, k)
        o.append(f'<clipPath id="cp-{c}"><path d="{rr(x, y, w, h, k["tl"], k["tr"], k["br"], k["bl"])}"/></clipPath>')
    o.append("</defs>")
    for n, s, c in items:
        x, y, w, h, k = geo[n]
        on = TH_ON[c]
        o.append(f'<path d="{rr(x, y, w, h, k["tl"], k["tr"], k["br"], k["bl"])}" style="fill:var(--{c})"/>')
        # concentric rings anchored at the big-radius corner
        corner = big[n]
        ax = x if corner in ("tl", "bl") else x + w
        ay = y if corner in ("tl", "tr") else y + h
        m = min(w, h)
        ring = "".join(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="{m * f:.1f}" style="fill:none;stroke:{on};stroke-opacity:.28;stroke-width:2"/>' for f in (0.3, 0.55, 0.8) if m > 60)
        o.append(f'<g clip-path="url(#cp-{c})">{ring}</g>')
        # text on the opposite side of the rings
        tx = x + 16 if corner in ("tr", "br") else x + w - 16
        anc = "start" if corner in ("tr", "br") else "end"
        ty = y + 26 if corner in ("tr", "tl") is False else y + 26
        lines = wrap(n, w - 40, 17) or []
        for i, t in enumerate(lines):
            o.append(T(tx, y + 28 + i * 21, t, 17, 600, on, anc))
        if n == "Charging":
            o.append(f'<path d="{rr(x - 4, y - 4, w + 8, h + 8, k["tl"] + 4, k["tr"] + 4, k["br"] + 4, k["bl"] + 4)}" style="fill:none;stroke:var(--ink);stroke-width:2.5"/>')
            cx, cy = x + w / 2, y + h + 4
            o.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx:.1f}" y2="{H + 8}" style="stroke:var(--ink);stroke-width:1.5"/>')
            o.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" style="fill:var(--ink)"/>')
            o.append(f'<rect x="{cx - 104:.1f}" y="{H + 8}" width="208" height="34" rx="17" style="fill:var(--ink)"/>')
            o.append(T(cx, H + 25, "Sharpest tone in the answers", 14, 500, "var(--bg)", "middle"))
    o.append("</svg>")
    return with_side("".join(o) + HEAD.format("See what matters most, and how it feels.", "Bigger block, more people. Outlined block, the sharpest tone."))

OPTS = [("signin-a", "[signin] A, previous version", opt_a), ("signin-b", "[signin] B, words to themes", opt_b),
        ("signin-c", "[signin] C, quote wall", opt_c), ("signin-d", "[signin] D, mosaic", opt_d)]
body, w, h = opt_d()
open(f"{OUT2}/signin-d.dc.html", "w").write(page("[signin] D, mosaic", w, h, False, body))
print("ok")

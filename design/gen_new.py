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
def f_treemap():
    W, H = 1084, 580
    rects = squarify([(n, s) for n, s, _, _, _ in THEMES], 0, 0, W, H)
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Treemap of themes and sub-themes">']
    for name, share, sent, cnt, col in THEMES:
        x, y, w, h = rects[name]
        x += 1.5; y += 1.5; w -= 3; h -= 3
        o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="5" style="fill:var(--{col})"/>')
        lines = wrap(f"{name} {share}%", w - 18, 15) or [f"{share}%"]
        hh = len(lines) * 18 + 14
        for i, t in enumerate(lines):
            o.append(T(x + 10, y + 16 + i * 18, t, 15, 600, TH_ON[col]))
        subs = SUBS.get(name)
        if subs and h - hh - 5 > 20:
            sr = squarify(subs, x + 5, y + hh, w - 10, h - hh - 5)
            for k, (sn, sp) in enumerate(subs):
                sx, sy, sw, sh = sr[(sn, sp)] if (sn, sp) in sr else sr[sn]
                sx += 1.5; sy += 1.5; sw -= 3; sh -= 3
                o.append(f'<rect x="{sx:.1f}" y="{sy:.1f}" width="{sw:.1f}" height="{sh:.1f}" rx="3" style="fill:color-mix(in srgb,var(--{col}) {MIX[k] + 12}%,var(--surface))"/>')
                o.append(fit_label(sx, sy, sw, sh, sn, f"{sp:g}%", 14, "var(--ink)", False))
    o.append("</svg>")
    return frame("What are the themes?", "Block area is share of answered. Sub-themes sit inside their theme.", "".join(o), 800)

# fix: squarify keys must be hashable and unique; sub items are (name, share) tuples keyed by name
def _sub_items(subs):
    return [(sn, sp) for sn, sp in subs]

# ---- icicle
def f_icicle():
    W = 1084
    o = [f'<svg width="{W}" height="380" viewBox="0 0 {W} 380" role="img" aria-label="Icicle chart: themes above, sub-themes below">']
    o.append(T(0, 8, "Themes", 14, 500, "var(--muted)"))
    y1, h1, y2, h2 = 24, 130, 158, 210
    a = 0.0
    for name, share, sent, cnt, col in THEMES:
        x = a / 100 * W; w = share / 100 * W; a += share
        o.append(f'<rect x="{x + 1.5:.1f}" y="{y1}" width="{w - 3:.1f}" height="{h1}" rx="3" style="fill:var(--{col})"/>')
        o.append(fit_label(x + 1.5, y1, w - 3, h1, name, f"{share}%", 13, TH_ON[col]))
        aa = x
        for k, (sn, sp) in enumerate(SUBS.get(name, [])):
            sw = sp / 100 * W
            o.append(f'<rect x="{aa + 1.5:.1f}" y="{y2}" width="{sw - 3:.1f}" height="{h2}" rx="3" style="fill:color-mix(in srgb,var(--{col}) {MIX[k] + 12}%,var(--surface))"/>')
            o.append(fit_label(aa + 1.5, y2, sw - 3, h2, sn, f"{sp:g}%", 12.5, "var(--ink)"))
            aa += sw
    o.append(T(0, y2 + h2 + 22, "Sub-themes, as share of all answered. Uncertainty and Other have none.", 14, 400, "var(--muted)"))
    o.append("</svg>")
    return frame("What are the themes?", "Width is share of answered. Read down from a theme to its sub-themes.", "".join(o), 620)

# ---- sentiment sunburst
def f_sentsun():
    W = H = 580
    cx = cy = 290
    R = 280
    hole, r1, r2 = 0.34 * R, 0.62 * R, 0.64 * R
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Sentiment sunburst: themes inside, tone split outside">']
    a = 0.0
    tones = {n: (ng, nu, ps) for n, ng, nu, ps in DIV}
    for name, share, sent, cnt, col in THEMES:
        span = share * 3.6
        a0, a1 = a, a + span
        a = a1
        o.append(f'<path d="{wedge(cx, cy, hole, r1, a0, a1)}" style="fill:var(--{col});stroke:var(--surface);stroke-width:3"/>')
        o.append(arc_label(cx, cy, (hole + r1) / 2, r1 - hole, a0, a1, name, f"{share}%", 13.5, TH_ON[col]))
        aa = a0
        for v, c, on in zip(tones[name], ("neg", "neu", "pos"), ("var(--on-neg)", "var(--on-neu)", "var(--on-pos)")):
            sp = span * v / 100
            o.append(f'<path d="{wedge(cx, cy, r2, R, aa, aa + sp)}" style="fill:var(--{c});stroke:var(--surface);stroke-width:2.5"/>')
            o.append(arc_label(cx, cy, (r2 + R) / 2, R - r2, aa, aa + sp, None, f"{v}%", 13, on))
            aa += sp
    o.append(T(cx, cy - 12, "47,525", 32, 300, "var(--ink)", "middle"))
    o.append(T(cx, cy + 16, "answered", 15, 400, "var(--muted)", "middle"))
    o.append("</svg>")
    tbl = ('<div style="flex:1;padding-top:12px"><div style="display:flex;align-items:center;gap:10px;height:30px;font-size:13px;font-weight:500;color:var(--muted)">'
           '<span style="width:12px"></span><span style="flex:1">Theme</span>'
           '<span style="width:72px;text-align:right">Negative</span><span style="width:72px;text-align:right">Neutral</span><span style="width:72px;text-align:right">Positive</span></div>')
    for name, share, sent, cnt, col in THEMES:
        ng, nu, ps = tones[name]
        tbl += (f'<div style="display:flex;align-items:center;gap:10px;height:44px;border-top:1px solid var(--line);font-size:15px">'
                f'<span style="width:12px;height:12px;border-radius:3px;background:var(--{col})"></span><span style="flex:1;line-height:1.2">{esc(name)}</span>'
                f'<span style="width:72px;text-align:right;font-weight:600">{ng}%</span><span style="width:72px;text-align:right">{nu}%</span><span style="width:72px;text-align:right">{ps}%</span></div>')
    def sw(c, t):
        return f'<span style="display:inline-flex;align-items:center;gap:8px;margin-right:20px;font-size:14px;color:var(--muted)"><span style="width:14px;height:14px;border-radius:3px;background:{c}"></span>{t}</span>'
    tbl += f'<div style="margin-top:20px">{sw("var(--neg)", "Negative")}{sw("var(--neu)", "Neutral")}{sw("var(--pos)", "Positive")}</div></div>'
    inner = f'<div style="display:flex;gap:40px;align-items:flex-start"><div style="flex:none">{"".join(o)}</div>{tbl}</div>'
    return frame("Which themes sound negative or positive?", "Inner ring is the theme. Outer ring splits each theme by tone.", inner, 800)

# ---- marimekko
def f_mekko():
    W = 1084
    gap = 3
    avail = W - gap * 7
    Hc = 440
    o = [f'<svg width="{W}" height="600" viewBox="0 0 {W} 600" role="img" aria-label="Marimekko: theme width is share, height is tone split">']
    x = 0.0
    tones = {n: (ng, nu, ps) for n, ng, nu, ps in DIV}
    for name, share, sent, cnt, col in THEMES:
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
def f_sankey():
    W, H = 1084, 620
    names = [t[0] for t in THEMES]
    tcol = [t[4] for t in THEMES]
    tones = {n: (ng, nu, ps) for n, ng, nu, ps in DIV}
    L = []
    for lab, vals, sent, n in BYS:
        L.append([n * v / 100 for v in vals])
    M = [sum(L[b][i] for b in range(3)) for i in range(8)]
    tot = sum(M)
    R_ = [[M[i] * tones[names[i]][t] / 100 for i in range(8)] for t in range(3)]
    RT = [sum(r) for r in R_]
    s = (560 - 7 * 12) / tot
    xl, xm, xr, nw = 170, 520, 900, 14
    y0l = (H - (tot * s + 2 * 36)) / 2
    y0m = (H - (tot * s + 7 * 12)) / 2
    y0r = y0l
    ly = []; y = y0l
    for b in range(3):
        ly.append(y); y += sum(L[b]) * s + 36
    my = []; y = y0m
    for i in range(8):
        my.append(y); y += M[i] * s + 12
    ry = []; y = y0r
    for t in range(3):
        ry.append(y); y += RT[t] * s + 36
    def link(x0, ya, x1, yb, h, fill, op):
        xm_ = (x0 + x1) / 2
        return (f'<path d="M{x0} {ya:.1f}C{xm_} {ya:.1f} {xm_} {yb:.1f} {x1} {yb:.1f}L{x1} {yb + h:.1f}C{xm_} {yb + h:.1f} {xm_} {ya + h:.1f} {x0} {ya + h:.1f}Z" style="fill:{fill};fill-opacity:{op}"/>')
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Flow from score band to theme to tone">']
    o.append(T(xl, 8, "Likelihood to buy", 14, 500, "var(--muted)", "start"))
    o.append(T(xm, 8, "Theme", 14, 500, "var(--muted)", "start"))
    o.append(T(xr, 8, "Tone", 14, 500, "var(--muted)", "start"))
    inm = [my[i] for i in range(8)]
    for b in range(3):
        yy = ly[b]
        for i in range(8):
            h = L[b][i] * s
            o.append(link(xl + nw, yy, xm, inm[i], h, f"var(--{tcol[i]})", 0.55))
            inm[i] += h; yy += h
    outm = [my[i] for i in range(8)]
    inr = list(ry)
    for i in range(8):
        for t, c in enumerate(("neg", "neu", "pos")):
            h = R_[t][i] * s
            o.append(link(xm + nw, outm[i], xr, inr[t], h, f"var(--{c})", 0.6))
            outm[i] += h; inr[t] += h
    for b, (lab, vals, sent, n) in enumerate(BYS):
        h = sum(L[b]) * s
        o.append(f'<rect x="{xl}" y="{ly[b]:.1f}" width="{nw}" height="{h:.1f}" rx="2" style="fill:var(--ink)"/>')
        o.append(T(xl - 12, ly[b] + h / 2 - 10, lab, 16, 600, anchor="end"))
        o.append(T(xl - 12, ly[b] + h / 2 + 10, f"{fmt(n)} answers", 14, 400, "var(--muted)", "end"))
    for i in range(8):
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
PAIRS = [(0, 1, 1900), (1, 2, 1600), (0, 2, 1100), (0, 4, 800), (2, 4, 700), (0, 5, 400), (1, 5, 350), (1, 3, 300), (4, 6, 200), (3, 5, 150)]

def f_arc():
    W, base = 1084, 400
    xs = [70 + i * (W - 140) / 7 for i in range(8)]
    o = [f'<svg width="{W}" height="560" viewBox="0 0 {W} 560" role="img" aria-label="Arc diagram of themes that appear in the same answer">']
    sel = 1
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
    for i, (name, share, sent, cnt, col) in enumerate(THEMES):
        r = 7 * math.sqrt(share)
        dim = 1 if i in (1,) or any(sel in (a, b) and i in (a, b) for a, b, c in PAIRS) else 0.35
        o.append(f'<circle cx="{xs[i]:.1f}" cy="{base}" r="{r:.1f}" style="fill:var(--{col});stroke:var(--bg);stroke-width:2;opacity:{dim}"/>')
        lines = (wrap(name, 128, 14) or [name]) + [f"{share}%"]
        for k, t in enumerate(lines):
            o.append(T(xs[i], base + 46 + k * 18, t, 14, 500 if k < len(lines) - 1 else 600, "var(--ink)" if dim == 1 else "var(--muted)", "middle"))
    o.append("</svg>")
    return frame("Which themes come up together?", "Each arc joins two themes mentioned in the same answer. Arc thickness is the number of answers. Charging is selected.", "".join(o), 760)

# ---- answer map
def f_map():
    rnd = random.Random(42)
    W, Hh = 1084, 620
    px0, pw, py0, ph = 60, 960, 40, 520
    o = [f'<svg width="{W}" height="{Hh}" viewBox="0 0 {W} {Hh}" role="img" aria-label="Map of answers: each dot is about 50 answers, placed near answers with similar wording">']
    sel = "Charging"
    labels = ""
    tip = ""
    for name, share, sent, cnt, col in THEMES:
        g = f'<g style="opacity:{1 if name == sel else DIM}">'
        n = round(share * 9.5)
        if name == "Other":
            pts = [(px0 + rnd.random() * pw, py0 + rnd.random() * ph) for _ in range(n)]
            cxy = None
        else:
            cx0, cy0 = px0 + BUB[name][0] * pw, py0 + BUB[name][1] * ph
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
                       + T(cxy[0] + 44, cxy[1] - 66, "No driveway so can't install a home charger", 14, 500, "var(--bg)")
                       + T(cxy[0] + 44, cxy[1] - 44, "Charging, negative", 13, 400, "var(--bg)"))
    o.append(labels)
    o.append(tip)
    o.append("</svg>")
    return frame("What does the whole pool of answers look like?", "Each dot is about 50 answers, placed near answers with similar wording. Charging is selected.", "".join(o), 820)

# ---------- build ----------
BASE = [
    ("overview", f_overview), ("sunburst", f_sunburst), ("treemap", f_treemap), ("icicle", f_icicle),
    ("sentsun", f_sentsun), ("rank", f_rank), ("diverge", f_diverge), ("mekko", f_mekko), ("bubbles", f_bubbles),
    ("sankey", f_sankey), ("arc", f_arc), ("map", f_map), ("byScore", f_byscore), ("heatmap", f_heatmap),
    ("trend", f_trend), ("quality", f_quality), ("context", f_context),
]
MOBILE = {"sunburst": f_sunburst_m, "rank": f_rank_m}

boards, order = {}, []
y = 300

def add(fname, title, w, h, x, yy, body):
    with open(f"{OUT}/{fname}", "w") as f:
        f.write(page(title, w, h, False, body))
    boards[fname] = {"x": x, "y": yy, "w": w, "h": h, "title": title}
    order.append(fname)

for f in os.listdir(OUT):
    if f.endswith(".dc.html"):
        os.remove(f"{OUT}/{f}")

body, w, h = f_tokens()
add("Main.dc.html", "Tokens", w, h, 0, y, body)
y += h + 120
for fid, fn in BASE:
    body, w, h = fn()
    rowh = h
    add(f"{fid}.dc.html", f"[{fid}]", w, h, 0, y, body)
    if fid in MOBILE:
        mb, mw, mh = MOBILE[fid]()
        add(f"{fid}-mobile.dc.html", f"[{fid}] Mobile 390", mw, mh, 1260, y, mb)
        rowh = max(rowh, mh)
    y += rowh + 120

canvas = {
    "v": 3, "createdOnFiles": {"v": 1, "at": "2026-09-19T12:00:00Z"},
    "title": "Verbatim Visual System", "launch": {"view": "canvas"}, "pages": [],
    "boards": boards, "order": order,
    "notes": {"t": {"x": 0, "y": 0, "text": "Verbatim: visuals for open-ended answers, light theme", "kind": "title1", "maxW": 1650}},
    "designSystems": [],
}
with open(f"{OUT}/canvas.json", "w") as f:
    json.dump(canvas, f, indent=1)
print(len(order), "boards")

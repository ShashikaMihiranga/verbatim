from gen_pages import *
from gen_reports import inner

def badge(kind):
    if kind == "Solid":
        st = "border:1px solid var(--pos);color:var(--ink);background:color-mix(in srgb,var(--pos) 12%,var(--surface));"
    else:
        st = "border:1px solid var(--line);color:var(--muted);background:var(--surface);"
    return f'<span style="display:inline-flex;align-items:center;height:26px;padding:0 12px;border-radius:999px;font-size:13px;font-weight:600;white-space:nowrap;{st}">{kind}</span>'

def block(headline, inner_html, kind="Solid", note=""):
    n = f'<div style="margin-top:14px;font-size:13px;color:var(--muted)">{esc(note)}</div>' if note else ""
    return (f'<div style="margin-top:56px;padding-top:32px;border-top:1px solid var(--line)"><div style="display:flex;justify-content:space-between;align-items:flex-start;gap:32px">'
            f'<div style="font-size:28px;font-weight:300;line-height:1.3;max-width:800px">{headline}</div>'
            f'<div style="display:flex;align-items:center;gap:20px;padding-top:6px">{badge(kind)}<span style="font-size:14px;font-weight:500;color:var(--accent);white-space:nowrap">See the answers</span></div></div>'
            f'<div style="margin-top:28px">{inner_html}</div>{n}</div>')

def report(title, meta, used, glance, blocks, also):
    chips = "".join(f'<span style="display:inline-flex;align-items:center;height:32px;padding:0 12px;border-radius:8px;background:var(--surface);border:1px solid var(--line);font-size:14px;font-weight:500">{esc(c)}<span style="color:var(--muted);font-weight:400;margin-left:6px">{esc(r)}</span></span>' for c, r in used)
    head = (f'<div style="display:flex;justify-content:space-between;align-items:center;font-size:14px;color:var(--muted)"><span>Report</span>'
            f'<span style="display:flex;gap:24px;font-weight:500;color:var(--accent)"><span>Filter</span><span>Share</span><span>Export</span></span></div>'
            f'<div style="font-size:44px;font-weight:300;line-height:1.15;margin-top:12px">{esc(title)}</div>'
            f'<div style="font-size:16px;color:var(--muted);margin-top:6px">{esc(meta)}</div>'
            f'<div style="margin-top:20px;font-size:13px;font-weight:500;color:var(--muted)">Columns used</div>'
            f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">{chips}</div>')
    gl = ""
    for i, (s, k) in enumerate(glance, 1):
        gl += (f'<div style="display:flex;align-items:center;gap:20px;padding:18px 0;border-top:1px solid var(--line)"><span style="width:24px;font-size:20px;font-weight:600;color:var(--accent)">{i}</span>'
               f'<span style="flex:1;font-size:24px;font-weight:300;line-height:1.35">{s}</span>{badge(k)}</div>')
    glance_html = f'<div style="margin-top:48px"><div style="font-size:22px;font-weight:600;margin-bottom:10px">What stands out</div><div style="border-bottom:1px solid var(--line)">{gl}</div></div>'
    alsoh = (f'<div style="margin-top:56px;padding-top:24px;border-top:1px solid var(--line);font-size:16px;line-height:1.5"><span style="font-weight:600">Also checked, nothing notable:</span> <span style="color:var(--muted)">{esc(also)}</span></div>'
             f'<details style="margin-top:24px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)"><summary style="display:flex;justify-content:space-between;align-items:center;padding:16px 0;font-size:18px;font-weight:500;list-style:none;cursor:pointer">See more charts<span style="font-size:24px;font-weight:300;color:var(--muted)">+</span></summary></details>')
    return f'{nav("Projects")}<div style="padding:40px 98px 64px">{head}{glance_html}{blocks}{alsoh}</div>'

def hm_grid(rows, ages, hi=None):
    g = f'<div style="display:grid;grid-template-columns:200px repeat({len(ages)},minmax(0,1fr));gap:4px"><div></div>'
    for a, n in ages:
        g += f'<div style="text-align:center;padding-bottom:6px"><div style="font-size:16px;font-weight:500">{a}</div><div style="font-size:13px;color:var(--muted)">n={fmt(n)}</div></div>'
    for name, ov, vals in rows:
        g += f'<div style="display:flex;flex-direction:column;justify-content:center"><div style="font-size:16px;font-weight:500">{esc(name)}</div><div style="font-size:13px;color:var(--muted)">overall {ov}%</div></div>'
        for j, v in enumerate(vals):
            m = ramp_mix(v, ov)
            tc = "var(--on-ramp)" if m >= 55 else "var(--ink)"
            ring = "outline:2px solid var(--ink);outline-offset:2px;" if hi == (name, j) else ""
            g += f'<div style="height:56px;border-radius:4px;background:color-mix(in srgb,var(--ramp) {m:.0f}%,var(--surface));color:{tc};display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:{600 if m >= 55 else 500};{ring}">{v}%</div>'
    return g + "</div>"

def hbars(rows, maxv, color, unit="%", w=560, ref=None):
    o = ""
    for lab, v, sub in rows:
        o += (f'<div style="display:flex;align-items:center;height:52px"><div style="width:220px"><div style="font-size:16px;font-weight:500">{esc(lab)}</div><div style="font-size:13px;color:var(--muted)">{esc(sub)}</div></div>'
              f'<div style="display:flex;align-items:center;gap:12px"><div style="width:{v / maxv * w:.0f}px;height:26px;border-radius:3px;background:{color}"></div><span style="font-size:18px;font-weight:600">{v}{unit}</span></div></div>')
    return o

def gbars(groups, series, H=300):
    W = 1084
    o = [f'<svg width="{W}" height="{H + 50}" viewBox="0 0 {W} {H + 50}" role="img" aria-label="Grouped bars by income group">']
    gw = W / len(groups)
    base = H
    sc = (H - 50) / 40
    for i, g in enumerate(groups):
        x0 = i * gw + gw / 2
        for k, (nm, col, vals) in enumerate(series):
            v = vals[i]
            bw = 64
            x = x0 + (k - len(series) / 2) * (bw + 8) + 4
            o.append(f'<rect x="{x:.1f}" y="{base - v * sc:.1f}" width="{bw}" height="{v * sc:.1f}" rx="3" style="fill:var(--{col})"/>')
            o.append(T(x + bw / 2, base - v * sc - 14, f"{v}%", 16, 600, "var(--ink)", "middle"))
        o.append(T(x0, base + 24, g, 15, 500, "var(--ink)", "middle"))
    ly = 10
    for k, (nm, col, vals) in enumerate(series):
        o.append(f'<rect x="{k * 110}" y="{ly - 6}" width="12" height="12" rx="3" style="fill:var(--{col})"/>')
        o.append(T(k * 110 + 20, ly, nm, 14, 500))
    o.append(f'<line x1="0" y1="{base}" x2="{W}" y2="{base}" style="stroke:var(--ink);stroke-width:1"/>')
    o.append("</svg>")
    return "".join(o)

def mini_trend():
    S = [("Cost", "t1", series(26, 34, 1.0, 3)), ("Charging", "t2", series(33, 22, 1.0, 5))]
    W, H = 1084, 260
    x0, x1 = 44, 830
    dx = (x1 - x0) / 11
    def X(i): return x0 + dx * i
    def Y(v): return 230 - v / 40 * 200
    o = [f'<svg width="{W}" height="{H + 30}" viewBox="0 0 {W} {H + 30}" role="img" aria-label="Cost and Charging share by month">']
    for g in (0, 20, 40):
        o.append(f'<line x1="{x0}" y1="{Y(g):.1f}" x2="{x1}" y2="{Y(g):.1f}" style="stroke:var(--line)"/>')
        o.append(T(x0 - 8, Y(g), f"{g}%", 13, 400, "var(--muted)", "end"))
    for nm, col, vals in S:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        o.append(f'<polyline points="{pts}" style="fill:none;stroke:var(--{col});stroke-width:2.5;stroke-linejoin:round"/>')
        o.append(f'<circle cx="{X(11):.1f}" cy="{Y(vals[11]):.1f}" r="4" style="fill:var(--{col})"/>')
        o.append(T(x1 + 16, Y(vals[11]), f"{nm} {vals[11]:.0f}%", 15, 600))
        o.append(T(X(0) + 8, Y(vals[0]) - 14, f"{vals[0]:.0f}%", 13, 500, "var(--muted)"))
    for i, m in enumerate(MONTHS):
        o.append(T(X(i), 250, m, 13, 400, "var(--muted)", "middle"))
    o.append("</svg>")
    return "".join(o)

# ---------- A ----------
def rep_a():
    hm = hm_grid([(n, ov, v) for n, ov, v in HM if n != "Doubts about the technology"], AGES, ("Not needed", 5))
    score = hbars([("Low (0-6)", 18, "least likely to buy"), ("Middle (7-8)", 3, ""), ("High (9-10)", 1, "most likely to buy")], 18, "var(--t4)")
    inc = gbars(["Lowest quarter", "Second", "Third", "Highest quarter"], [("Cost", "t1", [38, 33, 27, 22]), ("Charging", "t2", [22, 25, 28, 31])])
    b = (block("Cost and Charging make up more than half of the reasons.", inner(f_treemap))
         + block('Age group "65+" mentions Not needed 2.6 times as often as the average respondent.', hm)
         + block("People less likely to buy talk far more about Not needed.", score, "Solid", "Share of each score group's answers that are about Not needed.")
         + block("Lower-income households name Cost more. Higher-income households name Charging more.", inc, "Tentative", "Income figures are sample data for illustration.")
         + block("Cost is rising through the year while Charging is fading.", mini_trend()))
    glance = [("Cost is the largest theme at 30% of answers, led by \"Upfront price\".", "Solid"),
              ("Age group \"65+\" mentions Not needed 2.6 times as often as the average respondent.", "Solid"),
              ("Lower-income households name Cost more. Higher-income households name Charging more.", "Tentative")]
    used = [("Response", "open-ended text"), ("Age group", "6 groups"), ("Likelihood to buy", "score"), ("Income", "4 bands"), ("Survey date", "by month"), ("Sex", "2 groups")]
    return report("Why haven't you bought an electric vehicle yet?", "Reasons, framed negatively. Answers run a sentence or two.", used, glance, b, "Sex."), 1280, 3500

# ---------- B ----------
def rep_b():
    import gen_reports as g0
    body, w, h = g0.rep_b()
    return body, w, h

def rep_b2():
    from gen_reports import OCC_
    W, H = 1084, 440
    rects = squarify(OCC_, 0, 0, W, H)
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Treemap of the ten most common occupations">']
    for i, (n, p) in enumerate(OCC_):
        x, y, w, h = rects[n]
        x += 2; y += 2; w -= 4; h -= 4
        m = 92 - i * 6.5
        tc = "var(--on-accent)" if m >= 55 else "var(--ink)"
        o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" style="fill:color-mix(in srgb,var(--accent) {m:.0f}%,var(--surface))"/>')
        o.append(fit_label(x, y, w, h, n, f"{p}%", 15 if w > 90 else 13, tc, False))
    o.append("</svg>")
    # income index bars around 100
    rows = [("Software engineer", 138), ("Manager", 127), ("Accountant", 118), ("Electrician", 104), ("Nurse", 92), ("Teacher", 90), ("Sales assistant", 71), ("Retail worker", 68)]
    sc = 3.6
    ix = 220 + 100 * sc
    r = ""
    for n, v in rows:
        above = v >= 100
        col = "var(--accent)" if above else "color-mix(in srgb,var(--accent) 45%,var(--surface))"
        x = ix if above else ix - (100 - v) * sc
        wd = abs(v - 100) * sc
        r += (f'<div style="position:relative;height:44px"><div style="position:absolute;left:0;top:0;height:44px;display:flex;align-items:center;width:210px;font-size:16px;font-weight:500">{n}</div>'
              f'<div style="position:absolute;left:{x:.0f}px;top:8px;width:{wd:.0f}px;height:28px;border-radius:3px;background:{col}"></div>'
              f'<div style="position:absolute;left:{(ix + wd + 12) if above else (x - 46):.0f}px;top:0;height:44px;display:flex;align-items:center;font-size:17px;font-weight:600">{v}</div></div>')
    r = (f'<div style="position:relative">{r}<div style="position:absolute;left:{ix:.0f}px;top:0;bottom:0;width:1px;background:var(--ink)"></div>'
         f'<div style="position:absolute;left:{ix - 60:.0f}px;top:-26px;width:120px;text-align:center;font-size:13px;font-weight:500;color:var(--muted)">Average is 100</div></div>')
    def stat(big, txt, pct):
        bar = f'<div style="height:8px;border-radius:4px;background:var(--line);margin-top:14px"><div style="width:{pct}%;height:8px;border-radius:4px;background:var(--accent)"></div></div>' if pct else '<div style="height:8px;margin-top:14px"></div>'
        return f'<div style="flex:1"><div style="font-size:64px;font-weight:300;line-height:1.1">{big}</div><div style="font-size:16px;color:var(--muted);margin-top:6px;max-width:300px">{txt}</div>{bar}</div>'
    strip = ('<div style="display:flex;gap:48px">' + stat("1,461", "different answers after merging spelling and plural variants", 0)
             + stat("39%", "of answers are covered by the ten most common", 39) + stat("41%", "of the distinct answers were given only once", 41) + "</div>")
    b = (block("Teacher and Nurse are the most common jobs, at nearly one answer in six.", "".join(o))
         + block("Software engineers and managers earn well above average. Retail and sales roles earn well below.", r, "Tentative", "Typical income compared with all respondents, where 100 is the average. Sample data for illustration.")
         + block("A long tail sits behind the top ten.", strip))
    glance = [("Teacher and Nurse are the most common jobs, at nearly one answer in six.", "Solid"),
              ("Software engineers and managers earn well above average. Retail and sales roles earn well below.", "Tentative"),
              ("41% of the distinct answers were given only once.", "Solid")]
    used = [("Occupation", "short text"), ("Income", "number, compared with average"), ("Age group", "6 groups"), ("Sex", "2 groups")]
    return report("What is your occupation?", "Short factual answers. 47,973 answered.", used, glance, b, "Age group, Sex."), 1280, 2500

# ---------- C ----------
def rep_c2():
    from gen_reports import IMP, IMP_AVG, SEG, IMP_HM
    rows = ""
    for name, sh, s in IMP:
        d = s - IMP_AVG
        if abs(d) < 0.03:
            col = "var(--neu)"
        else:
            t = min(1, (abs(d) - 0.03) / 0.09)
            col = f"color-mix(in srgb,{'var(--neg)' if d < 0 else 'var(--pos)'} {45 + 55 * t:.0f}%,var(--neu))"
        rows += (f'<div style="display:flex;align-items:center;height:60px"><div style="width:230px;font-size:17px;font-weight:500">{name}</div>'
                 f'<div style="display:flex;align-items:center;gap:14px;flex:1"><div style="width:{sh / 28 * 520:.0f}px;height:28px;border-radius:3px;background:{col}"></div><span style="font-size:18px;font-weight:600">{sh}%</span></div>'
                 f'<div style="width:90px;text-align:right;font-size:17px">{s:+.2f}</div></div>')
    legend = ('<div style="display:flex;gap:22px;font-size:14px;color:var(--muted);margin-bottom:8px">'
              + "".join(f'<span style="display:inline-flex;align-items:center;gap:8px"><span style="width:16px;height:16px;border-radius:3px;background:{c}"></span>{t}</span>' for c, t in
                        (("var(--neg)", "More negative than average"), ("var(--neu)", "About average"), ("var(--pos)", "Milder than average"))) + "</div>")
    g = '<div style="display:grid;grid-template-columns:230px repeat(3,minmax(0,1fr));gap:4px"><div></div>'
    for sname in SEG:
        g += f'<div style="text-align:center;font-size:16px;font-weight:500;padding-bottom:6px">{sname}</div>'
    for (name, sh, s), vals in zip(IMP, IMP_HM):
        g += f'<div style="display:flex;align-items:center;font-size:16px;font-weight:500">{name}</div>'
        for v in vals:
            m = ramp_mix(v, sh)
            tc = "var(--on-ramp)" if m >= 55 else "var(--ink)"
            g += f'<div style="height:56px;border-radius:4px;background:color-mix(in srgb,var(--ramp) {m:.0f}%,var(--surface));color:{tc};display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:{600 if m >= 55 else 500}">{v}%</div>'
    g += "</div>"
    # order value vs sentiment
    ov = [("Lowest quarter", -0.12), ("Second", -0.17), ("Third", -0.23), ("Highest quarter", -0.29)]
    sv = ""
    for lab, s in ov:
        p = 45 + min(1, abs(s) / 0.3) * 55
        sv += (f'<div style="display:flex;align-items:center;height:56px"><div style="width:230px;font-size:16px;font-weight:500">{lab}</div>'
               f'<div style="width:520px;display:flex;justify-content:flex-end"><div style="width:{abs(s) / 0.3 * 480:.0f}px;height:28px;border-radius:3px;background:color-mix(in srgb,var(--neg) {p:.0f}%,var(--neu))"></div></div>'
               f'<span style="margin-left:14px;font-size:18px;font-weight:600">{s:+.2f}</span></div>')
    sv = f'<div style="font-size:13px;font-weight:500;color:var(--muted);margin-bottom:6px">Order value, and average sentiment of the answers (more negative to the left)</div>{sv}'
    Qs = [("Deliveries keep arriving a day late", "Delivery speed", "t2"), ("Nobody answers the phone after five", "Customer support", "t1"), ("The app logs me out constantly", "Website and app", "t7")]
    ql = '<div style="display:flex;gap:48px">' + "".join(
        f'<div style="flex:1;border-top:2px solid var(--{c});padding-top:16px"><div style="font-size:26px;font-weight:300;line-height:1.3">"{esc(q)}"</div><div style="margin-top:12px;font-size:14px;font-weight:500;color:var(--muted)">{esc(t)}</div></div>' for q, t, c in Qs) + "</div>"
    b = (block("Delivery speed is the first thing to fix, and it sounds the most negative.", legend + rows)
         + block("Business customers ask for better support. New customers ask for faster delivery.", g)
         + block("The more customers spend, the more negative they sound.", sv, "Tentative", "Sample data for illustration.")
         + block("In their own words.", ql, "Solid"))
    glance = [("Delivery speed is the first thing to fix, and it sounds the most negative.", "Solid"),
              ("Business customers ask for better support. New customers ask for faster delivery.", "Solid"),
              ("The more customers spend, the more negative they sound.", "Tentative")]
    used = [("Response", "open-ended text"), ("Customer type", "3 groups"), ("Order value", "4 bands"), ("Order date", "by month"), ("Age group", "6 groups"), ("Sex", "2 groups")]
    return report("What one thing should we improve?", "Improvements. Answers run a sentence. Sample data for illustration.", used, glance, b, "Age group, Sex, Order date."), 1280, 2900

R = [("report-ev", "[report] A, reasons question", rep_a), ("report-occupation", "[report] B, short factual answers", rep_b2), ("report-improve", "[report] C, improvements question", rep_c2)]
sizes = {}
for fid, title, fn in R:
    body, w, h = fn()
    open(f"{OUT2}/{fid}.dc.html", "w").write(page(title, w, h, False, body))
    sizes[fid] = h
print("ok", sizes)

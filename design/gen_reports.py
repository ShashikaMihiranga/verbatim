from gen_pages import *

def inner(fn):
    body, w, h = fn()
    part = body.split('<div style="height:24px"></div>', 1)[1]
    return part[:-len("</div>")]

def block(headline, inner_html):
    return (f'<div style="margin-top:56px;padding-top:32px;border-top:1px solid var(--line)"><div style="display:flex;justify-content:space-between;align-items:baseline;gap:32px">'
            f'<div style="font-size:28px;font-weight:300;line-height:1.3;max-width:820px">{headline}</div>'
            f'<div style="font-size:14px;font-weight:500;color:var(--accent);white-space:nowrap">See the answers</div></div><div style="margin-top:28px">{inner_html}</div></div>')

def report(title, meta, chips, blocks):
    ch = ""
    for i, c in enumerate(chips):
        st = "background:var(--accent);color:var(--on-accent);border:1px solid var(--accent);font-weight:600;" if i == 0 else "border:1px solid var(--line);background:var(--surface);font-weight:500;"
        ch += f'<span style="display:inline-flex;align-items:center;height:34px;padding:0 14px;border-radius:999px;font-size:14px;{st}">{esc(c)}</span>'
    head = (f'<div style="display:flex;justify-content:space-between;align-items:center;font-size:14px;color:var(--muted)"><span>Report</span>'
            f'<span style="display:flex;gap:24px;font-weight:500;color:var(--accent)"><span>Share</span><span>Export</span></span></div>'
            f'<div style="font-size:44px;font-weight:300;line-height:1.15;margin-top:12px">{esc(title)}</div>'
            f'<div style="font-size:16px;color:var(--muted);margin-top:6px">{esc(meta)}</div>'
            f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:20px">{ch}</div>')
    return f'{nav("Projects")}<div style="padding:40px 98px 64px">{head}{blocks}</div>'

# ---------- A: EV reasons ----------
def rep_a():
    b = (block('Cost is the largest theme at 30% of answers, led by "Upfront price".', inner(f_treemap))
         + block("Charging carries the most negative wording.", inner(f_mekko))
         + block("People less likely to buy talk more about Not needed.", inner(f_sankey)))
    return report("Why haven't you bought an electric vehicle yet?", "Reasons, framed negatively. Answers run a sentence or two.",
                  ["All respondents", "Age group", "Likelihood to buy", "Survey date"], b), 1280, 2600

# ---------- B: occupation ----------
OCC_ = [("Teacher", 9.3), ("Nurse", 6.6), ("Software engineer", 4.8), ("Accountant", 4.0), ("Sales assistant", 3.3), ("Manager", 2.9),
        ("Retail worker", 2.7), ("Student", 2.1), ("Electrician", 1.9), ("Retired", 1.8)]

def rep_b():
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
    def stat(big, txt, pct):
        bar = f'<div style="height:8px;border-radius:4px;background:var(--line);margin-top:14px"><div style="width:{pct}%;height:8px;border-radius:4px;background:var(--accent)"></div></div>' if pct else '<div style="height:8px;margin-top:14px"></div>'
        return f'<div style="flex:1"><div style="font-size:64px;font-weight:300;line-height:1.1">{big}</div><div style="font-size:16px;color:var(--muted);margin-top:6px;max-width:300px">{txt}</div>{bar}</div>'
    strip = ('<div style="display:flex;gap:48px">'
             + stat("1,461", "different answers after merging spelling and plural variants", 0)
             + stat("39%", "of answers are covered by the ten most common", 39)
             + stat("41%", "of the distinct answers were given only once", 41) + "</div>")
    b = (block("Teacher and Nurse are the most common jobs, at nearly one answer in six.", "".join(o))
         + block("A long tail sits behind the top ten.", strip))
    return report("What is your occupation?", "Short factual answers. 47,973 answered.", ["All respondents", "Age group", "Survey date"], b), 1280, 1320

# ---------- C: improvements (illustrative data) ----------
IMP = [("Delivery speed", 28, -0.31), ("Customer support", 22, -0.22), ("Pricing", 18, -0.12), ("Product quality", 14, -0.08), ("Website and app", 10, -0.05), ("Other", 8, -0.02)]
IMP_AVG = -0.19
SEG = ["New customers", "Returning", "Business"]
IMP_HM = [[30, 27, 24], [18, 23, 30], [22, 17, 12], [12, 15, 17], [12, 10, 8], [6, 8, 9]]

def rep_c():
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
              '<span style="display:inline-flex;align-items:center;gap:8px"><span style="width:16px;height:16px;border-radius:3px;background:var(--neg)"></span>More negative than average</span>'
              '<span style="display:inline-flex;align-items:center;gap:8px"><span style="width:16px;height:16px;border-radius:3px;background:var(--neu)"></span>About average</span>'
              '<span style="display:inline-flex;align-items:center;gap:8px"><span style="width:16px;height:16px;border-radius:3px;background:var(--pos)"></span>Milder than average</span></div>')
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
    Qs = [("Deliveries keep arriving a day late", "Delivery speed", "t2"), ("Nobody answers the phone after five", "Customer support", "t1"), ("The app logs me out constantly", "Website and app", "t7")]
    ql = '<div style="display:flex;gap:48px">' + "".join(
        f'<div style="flex:1;border-top:2px solid var(--{c});padding-top:16px"><div style="font-size:26px;font-weight:300;line-height:1.3">"{esc(q)}"</div><div style="margin-top:12px;font-size:14px;font-weight:500;color:var(--muted)">{esc(t)}</div></div>' for q, t, c in Qs) + "</div>"
    b = (block("Delivery speed is the first thing to fix, and it sounds the most negative.", legend + rows)
         + block("Business customers ask for better support. New customers ask for faster delivery.", g)
         + block("In their own words.", ql))
    return report("What one thing should we improve?", "Improvements. Sample data for illustration.", ["All respondents", "Customer type", "Order date"], b), 1280, 1800

R = [("report-ev", "[report] A, reasons question", rep_a), ("report-occupation", "[report] B, short factual answers", rep_b), ("report-improve", "[report] C, improvements question", rep_c)]
for fid, title, fn in R:
    body, w, h = fn()
    open(f"{OUT2}/{fid}.dc.html", "w").write(page(title, w, h, False, body))
print("ok")

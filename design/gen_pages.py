import sys, os, json
sys.path.insert(0, "/Users/shashikamihiranga/Desktop/Open Ended Response Visualation/verbatim-app/app")
from charts import *

OUT2 = "/private/tmp/claude-501/-Users-shashikamihiranga-Desktop-Open-Ended-Response-Visualation/b43e4e41-12a4-427b-a057-edeefdfe52a1/scratchpad/verbatim/project"

def field(label, value="", ph="", state="", suffix="", hint=""):
    if state == "focus":
        bd = "border:2px solid var(--accent);"
    elif state == "error":
        bd = "border:2px solid var(--neg);"
    else:
        bd = "border:1px solid var(--line);"
    txt = (f'<span style="flex:1;font-size:16px;color:var(--ink)">{esc(value)}</span>' if value
           else f'<span style="flex:1;font-size:16px;color:var(--muted)">{esc(ph)}</span>')
    suf = f'<span style="font-size:14px;font-weight:500;color:var(--accent)">{esc(suffix)}</span>' if suffix else ""
    msg = f'<div style="font-size:14px;color:var(--neg);margin-top:6px">{esc(hint)}</div>' if state == "error" else (
        f'<div style="font-size:14px;color:var(--muted);margin-top:6px">{esc(hint)}</div>' if hint else "")
    return (f'<div style="margin-bottom:18px"><div style="font-size:14px;font-weight:500;margin-bottom:6px">{esc(label)}</div>'
            f'<div style="display:flex;align-items:center;height:48px;padding:0 14px;border-radius:10px;background:var(--surface);{bd}">{txt}{suf}</div>{msg}</div>')

def btn(label, kind="primary", w="100%"):
    if kind == "primary":
        st = "background:var(--accent);color:var(--on-accent);border:1px solid var(--accent);font-weight:600;"
    else:
        st = "background:var(--surface);color:var(--ink);border:1px solid var(--line);font-weight:500;"
    return f'<div style="display:flex;align-items:center;justify-content:center;height:48px;width:{w};border-radius:10px;font-size:16px;{st}">{esc(label)}</div>'

def wordmark():
    return '<div style="font-size:24px;font-weight:600;letter-spacing:-0.01em">Verbatim</div>'


def story_svg():
    rnd = random.Random(11)
    W, H = 500, 540
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Scattered answers grouped into themes">']
    o.append(T(0, 8, "Everyone's own words", 14, 500, "var(--muted)"))
    for _ in range(230):
        o.append(f'<circle cx="{rnd.uniform(6, 494):.1f}" cy="{rnd.uniform(28, 150):.1f}" r="3.4" style="fill:var(--muted);fill-opacity:.38"/>')
    o.append(f'<line x1="0" y1="176" x2="176" y2="176" style="stroke:var(--line);stroke-width:1"/><line x1="324" y1="176" x2="500" y2="176" style="stroke:var(--line);stroke-width:1"/>')
    o.append(T(250, 176, "Grouped by meaning", 14, 500, "var(--accent)", "middle"))
    cl = [("Cost", "t1", 120, 320, 26, 70), ("Charging", "t2", 330, 330, 24, 60), ("Range and battery", "t3", 135, 462, 20, 36), ("Not needed", "t4", 350, 455, 17, 24)]
    for name, col, cx, cy, sg, n in cl:
        for _ in range(n):
            o.append(f'<circle cx="{rnd.gauss(cx, sg):.1f}" cy="{rnd.gauss(cy, sg * .85):.1f}" r="3.8" style="fill:var(--{col});fill-opacity:.9"/>')
        o.append(Th(cx, cy + sg * 2.1 + 6, name, 15, 600, "var(--ink)", "middle"))
    o.append('<rect x="240" y="200" width="250" height="54" rx="10" style="fill:var(--ink)"/>')
    o.append('<path d="M330 254 L340 266 L350 254 Z" style="fill:var(--ink)"/>')
    o.append(T(254, 218, "No driveway so can't install", 14, 500, "var(--bg)"))
    o.append(T(254, 238, "a home charger", 14, 500, "var(--bg)"))
    o.append("</svg>")
    return "".join(o)

def preview_side(mode):
    if mode == "signin":
        content = (f'{story_svg()}'
                   f'<div style="font-size:30px;font-weight:300;line-height:1.25;margin-top:28px;max-width:460px">Every answer, sorted by what it means.</div>'
                   f'<div style="font-size:16px;color:var(--muted);margin-top:8px">Ask an open question. See the story in the answers.</div>')
    else:
        items = ["Upload a spreadsheet", "Themes and sentiment, grouped for you", "Share a report with your team"]
        content = ('<div style="font-size:30px;font-weight:300;line-height:1.25;max-width:460px">Turn open-ended answers into a report people can read at a glance.</div>'
                   '<div style="margin-top:40px;max-width:460px">' + "".join(
                       f'<div style="display:flex;gap:16px;padding:16px 0;border-top:1px solid var(--line);font-size:18px"><span style="width:24px;font-weight:600;color:var(--accent)">{i + 1}</span><span>{esc(t)}</span></div>' for i, t in enumerate(items))
                   + '<div style="border-top:1px solid var(--line)"></div></div>')
    return f'<div style="flex:1;background:var(--bg);border-left:1px solid var(--line);display:flex;flex-direction:column;justify-content:center;padding:0 80px">{content}</div>'

def f_signin():
    form = (f'<div style="width:400px">{wordmark()}<div style="font-size:44px;font-weight:300;line-height:1.15;margin:56px 0 8px">Sign in</div>'
            f'<div style="font-size:16px;color:var(--muted);margin-bottom:32px">Welcome back. Your projects are private to your workspace.</div>'
            f'{field("Email", "", "you@company.com")}'
            f'{field("Password", "", "Your password", "focus", "Show")}'
            f'<div style="display:flex;justify-content:space-between;font-size:14px;margin:-4px 0 24px"><span style="display:inline-flex;align-items:center;gap:8px"><span style="width:18px;height:18px;border:1px solid var(--line);border-radius:4px;background:var(--surface)"></span>Keep me signed in</span><span style="color:var(--accent);font-weight:500">Forgot password?</span></div>'
            f'{btn("Sign in")}'
            f'<div style="display:flex;align-items:center;gap:12px;margin:24px 0;font-size:14px;color:var(--muted)"><span style="flex:1;height:1px;background:var(--line)"></span>or<span style="flex:1;height:1px;background:var(--line)"></span></div>'
            f'<div style="display:flex;flex-direction:column;gap:10px">{btn("Continue with Google", "secondary")}{btn("Continue with Microsoft", "secondary")}</div>'
            f'<div style="margin-top:32px;font-size:15px;color:var(--muted)">New to Verbatim? <span style="color:var(--accent);font-weight:600">Create an account</span></div></div>')
    body = f'<div style="display:flex;height:820px"><div style="width:640px;display:flex;align-items:center;justify-content:center;background:var(--surface)">{form}</div>{preview_side("signin")}</div>'
    return body, 1280, 820

def f_signup():
    rules = [("At least 12 characters", True), ("Letters and numbers", True), ("Not a common password", False)]
    rl = "".join(f'<div style="display:flex;justify-content:space-between;font-size:14px;color:{"var(--ink)" if ok else "var(--muted)"}"><span>{esc(t)}</span><span style="font-weight:600;color:{"var(--pos)" if ok else "var(--muted)"}">{"Met" if ok else "Not yet"}</span></div>' for t, ok in rules)
    form = (f'<div style="width:400px">{wordmark()}<div style="font-size:44px;font-weight:300;line-height:1.15;margin:40px 0 8px">Create your account</div>'
            f'<div style="font-size:16px;color:var(--muted);margin-bottom:28px">Free to start. No card needed.</div>'
            f'{field("Full name", "", "Your name")}'
            f'{field("Work email", "sam@company", "", "error", "", "Enter a valid work email")}'
            f'{field("Password", "Summer-Ridge-2041", "", "focus", "Hide")}'
            f'<div style="margin:-6px 0 20px;display:flex;flex-direction:column;gap:4px">'
            f'<div style="height:6px;border-radius:3px;background:var(--line);margin-bottom:8px"><div style="width:66%;height:6px;border-radius:3px;background:var(--pos)"></div></div>{rl}</div>'
            f'<div style="display:flex;gap:10px;font-size:14px;margin-bottom:20px"><span style="width:18px;height:18px;border-radius:4px;background:var(--accent);flex:none;margin-top:2px"></span><span>I agree to the <span style="color:var(--accent);font-weight:500">Terms</span> and <span style="color:var(--accent);font-weight:500">Privacy Policy</span></span></div>'
            f'{btn("Create account")}'
            f'<div style="margin-top:14px;font-size:14px;color:var(--muted)">We will email a link to verify your address.</div>'
            f'<div style="margin-top:20px;font-size:15px;color:var(--muted)">Already have an account? <span style="color:var(--accent);font-weight:600">Sign in</span></div></div>')
    body = f'<div style="display:flex;height:900px"><div style="width:640px;display:flex;align-items:center;justify-content:center;background:var(--surface)">{form}</div>{preview_side("signup")}</div>'
    return body, 1280, 900

def nav(active):
    items = ["Projects", "Team", "Help"]
    it = "".join(f'<span style="font-size:15px;font-weight:{600 if x == active else 500};color:{"var(--ink)" if x == active else "var(--muted)"};{"border-bottom:2px solid var(--accent);padding-bottom:4px;" if x == active else ""}">{x}</span>' for x in items)
    return (f'<div style="height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 48px;background:var(--surface);border-bottom:1px solid var(--line)">'
            f'<div style="display:flex;align-items:center;gap:48px">{wordmark().replace("24px", "20px")}<div style="display:flex;gap:28px">{it}</div></div>'
            f'<div style="display:flex;align-items:center;gap:12px;font-size:14px;color:var(--muted)">Your workspace<span style="width:36px;height:36px;border-radius:50%;background:var(--accent);color:var(--on-accent);display:inline-flex;align-items:center;justify-content:center;font-weight:600">You</span></div></div>')

def steps(n):
    labels = ["Upload", "Check columns", "Report"]
    o = '<div style="display:flex;gap:28px;font-size:15px">'
    for i, t in enumerate(labels, 1):
        on = i == n
        o += (f'<span style="display:inline-flex;align-items:center;gap:10px;color:{"var(--ink)" if on else "var(--muted)"};font-weight:{600 if on else 500}">'
              f'<span style="width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:13px;'
              f'{"background:var(--accent);color:var(--on-accent);" if on else "border:1px solid var(--line);"}">{i}</span>{t}</span>')
    return o + "</div>"

def f_upload():
    drop = ('<div style="border:2px dashed var(--accent);border-radius:16px;background:color-mix(in srgb,var(--accent) 6%,var(--surface));height:280px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px">'
            '<div style="font-size:28px;font-weight:300">Drop your spreadsheet here</div>'
            '<div style="font-size:16px;color:var(--muted)">or</div>'
            '<div style="display:inline-flex;align-items:center;height:44px;padding:0 24px;border-radius:10px;background:var(--accent);color:var(--on-accent);font-weight:600">Browse files</div>'
            '<div style="font-size:14px;color:var(--muted);margin-top:8px">.xlsx, .xls or .csv. Built for large files.</div></div>')
    alt = ('<div style="display:flex;gap:16px;margin-top:16px">'
           '<div style="flex:1;border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:16px 20px"><div style="font-weight:600">Link a Google Sheet</div><div style="font-size:14px;color:var(--muted)">Paste a share link. We read it, and never change it.</div></div>'
           '<div style="flex:1;border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:16px 20px"><div style="font-weight:600">Connect a database</div><div style="font-size:14px;color:var(--muted)">Read-only access to one table.</div></div></div>')
    rows = [("Why haven't you bought an electric vehicle yet?", "50,000 responses", "Report ready"),
            ("What is your occupation?", "47,973 answered", "Report ready")]
    rl = "".join(f'<div style="display:flex;align-items:center;height:56px;border-top:1px solid var(--line);font-size:16px"><span style="flex:1;font-weight:500">{esc(a)}</span><span style="width:180px;color:var(--muted)">{b}</span><span style="width:120px;text-align:right;color:var(--accent);font-weight:500">{c}</span></div>' for a, b, c in rows)
    body = (f'{nav("Projects")}<div style="padding:48px 48px 0;max-width:1280px"><div style="display:flex;justify-content:space-between;align-items:flex-end">'
            f'<div style="font-size:44px;font-weight:300;line-height:1.15">New project</div>{steps(1)}</div>'
            f'<div style="height:32px"></div>{drop}{alt}'
            f'<div style="margin-top:48px;font-size:20px;font-weight:600;margin-bottom:12px">Recent projects</div><div style="border-bottom:1px solid var(--line)">{rl}</div></div>')
    return body, 1280, 920

def f_columns():
    cols = [("Response", "Open-ended text", "Question column", True), ("Likelihood to buy", "Score", "0 to 10", False),
            ("Survey date", "Date", "Grouped by month", False), ("Age group", "Segment", "6 groups", False), ("Respondent ID", "Ignored", "", False)]
    rows = ""
    for name, typ, note, main in cols:
        chip = (f'<span style="display:inline-flex;align-items:center;height:36px;padding:0 14px;border-radius:8px;font-size:15px;font-weight:{600 if main else 500};'
                f'{"background:var(--accent);color:var(--on-accent);" if main else "background:var(--surface);border:1px solid var(--line);"}">{typ}</span>')
        rows += (f'<div style="display:flex;align-items:center;height:60px;border-top:1px solid var(--line);font-size:16px"><span style="width:280px;font-weight:500">{esc(name)}</span>'
                 f'<span style="width:240px">{chip}</span><span style="flex:1;color:var(--muted);font-size:14px">{esc(note)}</span></div>')
    sample = ["No driveway so can't install a home charger", "Not enough public chargers near me", "Worried about resale value"]
    sl = "".join(f'<div style="padding:10px 0;border-top:1px solid var(--line);font-size:15px">{esc(s)}</div>' for s in sample)
    body = (f'{nav("Projects")}<div style="padding:48px"><div style="display:flex;justify-content:space-between;align-items:flex-end">'
            f'<div style="font-size:44px;font-weight:300;line-height:1.15">Check columns</div>{steps(2)}</div>'
            f'<div style="margin-top:12px;display:inline-flex;align-items:center;gap:10px;font-size:15px;color:var(--muted)"><span style="font-weight:600;color:var(--ink)">ev-survey.xlsx</span>50,000 rows, 5 columns</div>'
            f'<div style="height:32px"></div>'
            f'<div style="display:flex;gap:64px"><div style="flex:1.6"><div style="font-size:14px;font-weight:500;color:var(--muted);margin-bottom:8px">We guessed each column type. Change any that look wrong.</div>{rows}<div style="border-top:1px solid var(--line)"></div></div>'
            f'<div style="flex:1"><div style="font-size:14px;font-weight:500;margin-bottom:6px">Question asked</div>'
            f'<div style="display:flex;align-items:center;min-height:48px;padding:10px 14px;border-radius:10px;background:var(--surface);border:2px solid var(--accent);font-size:16px">Why haven\'t you bought an electric vehicle yet?</div>'
            f'<div style="font-size:14px;color:var(--muted);margin:6px 0 28px">Taken from the file. Edit it if it is not the exact wording.</div>'
            f'<div style="font-size:14px;font-weight:500;color:var(--muted);margin-bottom:4px">First answers</div>{sl}<div style="border-top:1px solid var(--line)"></div></div></div>'
            f'<div style="display:flex;justify-content:flex-end;align-items:center;gap:16px;margin-top:40px"><span style="font-size:15px;color:var(--muted)">Your file stays private to your workspace.</span>'
            f'<div style="width:140px">{btn("Back", "secondary")}</div><div style="width:200px">{btn("Build report")}</div></div></div>')
    return body, 1280, 860

FR = [("signin", f_signin), ("signup", f_signup), ("upload", f_upload), ("columns", f_columns)]
new = {}
for fid, fn in FR:
    body, w, h = fn()
    fname = f"{fid}.dc.html"
    with open(f"{OUT2}/{fname}", "w") as f:
        f.write(page(f"[{fid}]", w, h, False, body))
    new[fname] = (w, h)
json.dump(new, open("/private/tmp/claude-501/-Users-shashikamihiranga-Desktop-Open-Ended-Response-Visualation/b43e4e41-12a4-427b-a057-edeefdfe52a1/scratchpad/newpages.json", "w"))
print(new)

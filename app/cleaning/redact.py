"""Mask personal details in free text before it can reach any model or shared report.

Regex only, no network. Masks emails, URLs, phone numbers, obvious ID numbers (Luhn-valid card numbers, US-style
SSNs), and, best effort, names and street addresses:

- names: only after a cue ("my name is", "I am", "I'm", "this is", "call me", Mr/Mrs/Ms/Miss/Mx/Dr/Prof) and only
  when followed by capitalised words. A name written without a cue ("Sarah told me...") is NOT caught.
- addresses: a number, capitalised street-name words and a street word (Street, Rd, Avenue, ...), plus postcodes
  next to an AU state, a US state or in UK format. Lowercase addresses and bare postcodes are NOT caught.

This is a heuristic, not a guarantee (see docs/DECISIONS.md). Every pattern uses bounded quantifiers so a hostile
cell cannot cause catastrophic backtracking.
"""
from __future__ import annotations

import re
from typing import Iterable

LABELS = ("email", "phone", "url", "id", "name", "address")
PLACEHOLDER = {"email": "[email]", "phone": "[phone]", "url": "[link]", "id": "[id]", "name": "[name]",
               "address": "[address]"}
MAX_SCAN_CHARS = 20_000  # the rest of an enormous cell is cut, never scanned

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63}){1,6}")
_URL = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\"']{1,300}"
    r"|\b[a-z0-9\-]{1,63}(?:\.[a-z0-9\-]{1,63}){0,3}\.(?:com|net|org|io|co|au|uk|nz|us|ca|info|biz|app|dev|me)\b(?:/[^\s<>\"']{0,200})?"
)
_CARD = re.compile(r"(?<![\d\-])(?:\d[ \-]?){12,18}\d(?![\d\-])")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d\s().\-]{6,18}\d(?![\w])")
_LONG_ID = re.compile(r"(?<![\w.])\d{9,15}(?![\w])")
_DATEISH = re.compile(r"^\d{4}[-.]\d{1,2}[-.]\d{1,2}$|^\d{1,2}[-.]\d{1,2}[-.]\d{2,4}$")

# ---- names (cue phrase, then capitalised words)
_CAP = r"[A-ZÀ-ÖØ-Þ](?:['’][A-ZÀ-ÖØ-Þ])?[a-zà-öø-ÿ'’\-]{1,24}"
_NAME_TAIL = rf"({_CAP}(?:[ ]{_CAP}){{0,2}})"
_NAME_CUE = re.compile(
    r"(?i:\b(?:my name is|my name's|i am|i'm|i’m|this is|call me|name is))[ ]+" + _NAME_TAIL)
_NAME_TITLE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?[ ]+" + _NAME_TAIL)
# capitalised words that follow a cue but are not names ("I am Very happy", "This is Monday")
NOT_NAMES = frozenset(w.lower() for w in (
    "I The A An Not Very So Just Really Also Still Currently Always Never Now Here There Quite Too Sure Happy "
    "Sad Tired Worried Concerned Interested Unsure Confused Australian American British Canadian European Monday "
    "Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September "
    "October November December My Our Your This That These Those It He She They We You No Yes Ok Okay Fine Good Great "
    "Bad Unable Able Looking Thinking Waiting Planning Trying Hoping Told Getting Going Having Being "
    "Electric Tesla Toyota Ford Hyundai Kia Nissan Rivian Lucid Honda Mazda Subaru Volvo Polestar").split())

# ---- addresses
_STREET_WORDS = (r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Court|Ct|Place|Pl|Blvd|Boulevard|Highway|Hwy|"
                 r"Terrace|Crescent)")
_STREET = re.compile(
    rf"\b\d{{1,5}}(?:[/\-]\d{{1,5}})?[A-Za-z]?[ ]+(?:{_CAP}[ ]+){{1,4}}(?i:{_STREET_WORDS})\b\.?")
_AU_STATES = "NSW|VIC|QLD|SA|WA|TAS|NT|ACT"
_US_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|"
              "OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC")
_POSTCODE = re.compile(
    rf"\b(?:(?:{_AU_STATES})[ ]+\d{{4}}|(?:{_US_STATES})[ ]+\d{{5}}(?:-\d{{4}})?|[A-Z]{{1,2}}\d[A-Z\d]?[ ]?\d[A-Z]{{2}})\b")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _shown(m: str, label: str, partial: bool) -> str:
    return (m[:2] + "…" + PLACEHOLDER[label]) if partial else PLACEHOLDER[label]


def bare_digits_for_kind(kind: str) -> str:
    """Bare digit runs are IDs only in id_or_junk and numeric columns; in text columns they are phone numbers."""
    return "id" if kind in ("id_or_junk", "numeric") else "phone"


def redact_text(text: str, partial: bool = False, bare_digits: str = "phone") -> tuple[str, dict[str, int]]:
    """Return (masked text, counts per label). partial=True keeps two characters so a person can recognise
    what was masked in a review screen; never use partial output for anything sent to a model.

    bare_digits says what a 9 to 15 digit run without separators is: "phone" (free-text and short-text columns,
    the default) or "id" (id_or_junk and numeric columns). See bare_digits_for_kind."""
    if bare_digits not in ("phone", "id"):
        raise ValueError("bare_digits must be 'phone' or 'id'")
    counts = {k: 0 for k in LABELS}
    if not isinstance(text, str) or not text:
        return text, counts
    if len(text) > MAX_SCAN_CHARS:
        text = text[:MAX_SCAN_CHARS]

    def sub(rx: re.Pattern, label: str, s: str, ok=None) -> str:
        def repl(m: re.Match) -> str:
            g = m.group(0)
            if ok is not None and not ok(g):
                return g
            counts[label] += 1
            return _shown(g, label, partial)

        return rx.sub(repl, s)

    text = sub(_EMAIL, "email", text)
    text = sub(_URL, "url", text)
    text = sub(_CARD, "id", text, ok=lambda g: 13 <= len(re.sub(r"\D", "", g)) <= 19 and _luhn(re.sub(r"\D", "", g)))
    text = sub(_SSN, "id", text)
    text = sub(_POSTCODE, "address", text)  # before phones: a ZIP+4 such as 97201-1234 looks like a number

    def phone_ok(g: str) -> bool:
        digits = re.sub(r"\D", "", g)
        if not 8 <= len(digits) <= 15 or _DATEISH.match(g.strip()):
            return False
        if g.lstrip().startswith("+") or re.search(r"[\s().\-]", g):
            return True
        return bare_digits == "phone" and len(digits) == 10 and digits.startswith("0")  # a bare 0412345678

    text = sub(_PHONE, "phone", text, ok=phone_ok)
    text = sub(_LONG_ID, "phone" if bare_digits == "phone" else "id", text)
    text = sub(_STREET, "address", text)

    def names(rx: re.Pattern, s: str) -> str:
        def repl(m: re.Match) -> str:
            n = m.group(1)
            if n.split()[0].lower().strip("'’-") in NOT_NAMES:
                return m.group(0)
            counts["name"] += 1
            return m.group(0)[: m.start(1) - m.start(0)] + _shown(n, "name", partial)

        return rx.sub(repl, s)

    text = names(_NAME_CUE, text)
    text = names(_NAME_TITLE, text)
    return text, counts


def redact_many(texts: Iterable[str], bare_digits: str = "phone") -> tuple[list[str], dict[str, int]]:
    total = {k: 0 for k in LABELS}
    out = []
    for t in texts:
        r, c = redact_text(t, bare_digits=bare_digits)
        out.append(r)
        for k, v in c.items():
            total[k] += v
    return out, total


def summarise(counts: dict[str, int]) -> str:
    names = {"email": ("email", "emails"), "phone": ("phone number", "phone numbers"),
             "url": ("link", "links"), "id": ("ID number", "ID numbers"), "name": ("name", "names"),
             "address": ("address", "addresses")}
    parts = [f"{n} {names[k][0] if n == 1 else names[k][1]}" for k, n in counts.items() if n]
    return ("We masked " + ", ".join(parts) + "." if parts else
            "We found no emails, phone numbers, links, ID numbers, names or addresses we could recognise.")

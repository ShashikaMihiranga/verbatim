"""Mask personal details in free text before it can reach any model or shared report.

Regex only, no network. Masks emails, URLs, phone numbers and obvious ID numbers (card numbers that pass
the Luhn check, US-style SSNs, long digit runs). Names and addresses are NOT detected (see docs/DECISIONS.md).
Every pattern uses bounded quantifiers so a hostile cell cannot cause catastrophic backtracking.
"""
from __future__ import annotations

import re
from typing import Iterable

LABELS = ("email", "phone", "url", "id")
PLACEHOLDER = {"email": "[email]", "phone": "[phone]", "url": "[link]", "id": "[id]"}
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


def redact_text(text: str, partial: bool = False) -> tuple[str, dict[str, int]]:
    """Return (masked text, counts per label). partial=True keeps two characters so a person can recognise
    what was masked in a review screen; never use partial output for anything sent to a model."""
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

    def phone_ok(g: str) -> bool:
        digits = re.sub(r"\D", "", g)
        if not 8 <= len(digits) <= 15 or _DATEISH.match(g.strip()):
            return False
        return g.lstrip().startswith("+") or bool(re.search(r"[\s().\-]", g)) or len(digits) >= 9

    text = sub(_PHONE, "phone", text, ok=phone_ok)
    text = sub(_LONG_ID, "id", text)
    return text, counts


def redact_many(texts: Iterable[str]) -> tuple[list[str], dict[str, int]]:
    total = {k: 0 for k in LABELS}
    out = []
    for t in texts:
        r, c = redact_text(t)
        out.append(r)
        for k, v in c.items():
            total[k] += v
    return out, total


def summarise(counts: dict[str, int]) -> str:
    names = {"email": ("email", "emails"), "phone": ("phone number", "phone numbers"),
             "url": ("link", "links"), "id": ("ID number", "ID numbers")}
    parts = [f"{n} {names[k][0] if n == 1 else names[k][1]}" for k, n in counts.items() if n]
    return "We masked " + ", ".join(parts) + "." if parts else "We found no emails, phone numbers, links or ID numbers."

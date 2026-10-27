"""Optional Claude refinement of a column profile.

No-op unless ANTHROPIC_API_KEY is set (or a client is passed in, for tests).
One call with headers plus up to 30 sample values per column, never the full data.
Sensitive columns send the header only, no values. Every sample is masked first, the same way the cleaning
step masks text for a model (emails, phone numbers, links, ID numbers, cued names, addresses; BUG-063).
The `anthropic` SDK is imported lazily and is not a hard requirement.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any

from ..claude_models import light_model
from ..cleaning.redact import bare_digits_for_kind, redact_text
from .columns import KINDS

MAX_SAMPLES = 30

SYSTEM = (
    "You help a non-expert understand a survey spreadsheet. For each column you get its header and a few "
    "sample values, plus our automatic guess, and whether the header cell itself looks like a data value "
    "rather than a label (\"looks_headerless\"). Reply with JSON only: "
    '{"columns": [{"name": str, "kind": one of ' + ", ".join(KINDS) + ', "unit": str or null, '
    '"reason": one plain sentence, "suggested_name": str or null}], "question": str or null}. '
    "Only include columns where you disagree with the guess or can add a unit, UNLESS a column's "
    "looks_headerless is true - always include those, and set suggested_name to a short label (1 to 4 "
    "words, Title Case, no punctuation) for what that column's sample values represent, e.g. \"Age\" or "
    "\"Region\". Never set suggested_name for a column whose looks_headerless is not true. Never invent "
    "values."
)


def collect_samples(df, profile: dict[str, Any], n: int = MAX_SAMPLES) -> dict[str, list[str]]:
    """Up to n distinct sample values per column, masked. Sensitive columns get none."""
    out: dict[str, list[str]] = {}
    for c in profile["columns"]:
        if c.get("sensitive"):
            out[c["name"]] = []
            continue
        vals = df[c["name"]].dropna().astype(str).drop_duplicates().head(n)
        bare = bare_digits_for_kind(c.get("kind", ""))
        out[c["name"]] = [redact_text(v, bare_digits=bare)[0][:200] for v in vals]
    return out


def _build_prompt(profile: dict[str, Any], samples: dict[str, list[str]]) -> str:
    cols = [
        {"name": c["name"], "guess": c["kind"], "unit": c.get("unit"),
         "looks_headerless": c.get("looks_headerless", False),
         "samples": samples.get(c["name"], [])[:MAX_SAMPLES]}
        for c in profile["columns"]
    ]
    return json.dumps({"columns": cols, "current_question": (profile.get("question") or {}).get("text")})


def _parse_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def refine_profile(profile: dict[str, Any], samples: dict[str, list[str]], client: Any = None,
                   model: str | None = None) -> dict[str, Any]:
    """Return a refined copy of the profile, or the profile unchanged when Claude is not available."""
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return profile
        try:
            import anthropic  # lazy: not a hard requirement
        except ImportError:
            return profile
        client = anthropic.Anthropic()
    try:
        msg = client.messages.create(
            model=model or light_model(),  # column hints are a small task: app/claude_models.py
            max_tokens=1500,
            system=SYSTEM,
            # thinking disabled - see labeling.py::AnthropicClaudeClient.complete's own comment: a
            # structured-JSON task, and adaptive thinking competes with the reply itself for max_tokens.
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": _build_prompt(profile, samples)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
    except Exception:
        return profile  # refinement is best-effort; the local guess stands
    data = _parse_json(text)
    if not data:
        return profile

    refined = copy.deepcopy(profile)
    by_name = {c["name"]: c for c in refined["columns"]}
    for item in data.get("columns", []):
        col = by_name.get(item.get("name")) if isinstance(item, dict) else None
        if col is None:
            continue
        kind = item.get("kind")
        if kind in KINDS and kind != col["kind"]:
            col["kind"] = kind
            col["confidence"] = 0.8
            col["refined_by"] = "claude"
        if isinstance(item.get("unit"), str) and item["unit"]:
            col["unit"] = item["unit"][:30]
        if isinstance(item.get("reason"), str) and item["reason"].strip() and col.get("refined_by"):
            col["reason"] = item["reason"].strip()[:240]
        # Only ever attached to a column we ourselves flagged as headerless - Claude cannot smuggle a
        # rename suggestion onto an ordinary column even if it tries. Never touches col["name"] itself;
        # this is advisory metadata the frontend pre-fills into an editable field, nothing more.
        if col.get("looks_headerless") and isinstance(item.get("suggested_name"), str) and item["suggested_name"].strip():
            col["suggested_name"] = item["suggested_name"].strip()[:60]
    q = data.get("question")
    if isinstance(q, str) and q.strip() and not refined.get("question"):
        refined["question"] = {"text": q.strip()[:300], "source": "claude", "column": None}
    return refined

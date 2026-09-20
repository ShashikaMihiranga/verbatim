"""Optional Claude refinement of a column profile.

No-op unless ANTHROPIC_API_KEY is set (or a client is passed in, for tests).
One call to a small model with headers plus up to 30 sample values per column,
never the full data. Sensitive columns send the header only, no values.
The `anthropic` SDK is imported lazily and is not a hard requirement.
"""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any

from .columns import KINDS

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_SAMPLES = 30

SYSTEM = (
    "You help a non-expert understand a survey spreadsheet. For each column you get its header and a few "
    "sample values, plus our automatic guess. Reply with JSON only: "
    '{"columns": [{"name": str, "kind": one of ' + ", ".join(KINDS) + ', "unit": str or null, '
    '"reason": one plain sentence}], "question": str or null}. '
    "Only include columns where you disagree with the guess or can add a unit. Never invent values."
)


def collect_samples(df, profile: dict[str, Any], n: int = MAX_SAMPLES) -> dict[str, list[str]]:
    """Up to n distinct sample values per column. Sensitive columns get none."""
    out: dict[str, list[str]] = {}
    for c in profile["columns"]:
        if c.get("sensitive"):
            out[c["name"]] = []
            continue
        vals = df[c["name"]].dropna().astype(str).drop_duplicates().head(n)
        out[c["name"]] = [v[:200] for v in vals]
    return out


def _build_prompt(profile: dict[str, Any], samples: dict[str, list[str]]) -> str:
    cols = [
        {"name": c["name"], "guess": c["kind"], "unit": c.get("unit"), "samples": samples.get(c["name"], [])[:MAX_SAMPLES]}
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
            model=model or os.environ.get("VERBATIM_CLAUDE_MODEL", DEFAULT_MODEL),
            max_tokens=1500,
            system=SYSTEM,
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
    q = data.get("question")
    if isinstance(q, str) and q.strip() and not refined.get("question"):
        refined["question"] = {"text": q.strip()[:300], "source": "claude", "column": None}
    return refined

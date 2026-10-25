"""Theme grouping with Claude (design/handoffs/ThemeGrouping_UIHandoff.md).

One Claude call for a column's theme list: it proposes groups of themes that mean the same thing and the
near-misses it kept apart. Claude only sees, per theme, its name, answer count, share and 3 sample answers
masked through `app.cleaning.payload.model_safe_rows`; never the dataset, row ids or other columns. The
reply is validated here and never trusted: unknown ids, overlaps, groups under 2 members and "Other" are
dropped, not fatal. Each group gets a confidence band, checked against the themes' stored embedding
centroids: Claude's "High" becomes "Medium" when the themes' answers are not close in meaning.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import pandas as pd

from .cleaning import CleaningPlan
from .cleaning.payload import model_safe_rows
from .models import Theme

SYSTEM = (
    "You group survey themes that mean the same thing. You get a numbered list of themes, each with a name, "
    "answer count and three sample answers. Propose groups of two or more themes that should be merged "
    "because their answers are about the same topic. Do not group themes that only share a word. Do not put "
    'a theme in more than one group. Leave "Other" out. For each group give a short plain name, the member '
    "ids, a confidence from 0 to 100, and one or two sentences saying why, mentioning anything that argues "
    "against merging (for example, different tone or a different cause). Also list near-misses you chose to "
    "keep apart, with the reason. Reply with JSON only, no prose before or after it: "
    '{"groups": [{"name": str, "members": [int, ...], "confidence": int, "reason": str}], '
    '"kept_apart": [{"members": [int, int], "reason": str}]}.'
)

SAMPLES_PER_THEME = 3
SAMPLE_MIN_WORDS, SAMPLE_MAX_WORDS = 4, 60
HIGH, MEDIUM = 85, 60  # confidence bands; proposals in the hand-off, to tune on real datasets
# Cosine similarity of two themes' centroids below which Claude's "High" is shown as "Medium". Voyage
# document embeddings of answers on one topic sit well above this; to tune on real datasets.
SIMILARITY_CUTOFF = 0.6
MAX_THEMES = 150  # past this one request is too long; neighbourhood batching is not built yet


class GroupingRefused(Exception):
    """The column cannot be grouped (too few or too many themes)."""


def _samples(masked: dict[int, str], refs: list[int]) -> list[str]:
    """`SAMPLES_PER_THEME` readable masked answers, in row order: 4-60 words where possible."""
    good, spare = [], []
    for r in refs:
        text = masked.get(r)
        if not text or not text.strip():
            continue
        (good if SAMPLE_MIN_WORDS <= len(text.split()) <= SAMPLE_MAX_WORDS else spare).append(text.strip())
        if len(good) >= SAMPLES_PER_THEME:
            break
    return (good + spare)[:SAMPLES_PER_THEME]


def build_payload(themes: list[Theme], clean_df: pd.DataFrame, plan: CleaningPlan, column: str) -> tuple[dict, dict[int, int]]:
    """What Claude is sent, and the map from the payload's numbers (1..N) back to theme ids. "Other" is
    left out. Samples come only through `model_safe_rows`."""
    real = sorted((t for t in themes if t.label != "Other"), key=lambda t: -t.size)
    if len(real) < 2:
        raise GroupingRefused("There are fewer than two themes to group.")
    if len(real) > MAX_THEMES:
        raise GroupingRefused(f"Grouping works on up to {MAX_THEMES} themes at a time; this column has {len(real)}.")
    total = sum(t.size for t in themes) or 1
    # Only the first few usable answers of each theme are ever read and masked.
    wanted = [r for t in real for r in (t.answer_refs or [])[:40]]
    masked = model_safe_rows(clean_df, plan, column, wanted)
    numbered, id_of = [], {}
    for n, t in enumerate(real, start=1):
        id_of[n] = t.id
        numbered.append({"id": n, "name": t.label, "answers": t.size, "share": round(t.size / total * 100, 1),
                         "samples": _samples(masked, list(t.answer_refs or [])[:40])})
    return {"themes": numbered}, id_of


def payload_words(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False).split())


def payload_hash(payload: dict) -> str:
    """Cache key: the theme names, counts and samples sent. Any change to them asks Claude again."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def band(confidence: int) -> str:
    return "High" if confidence >= HIGH else "Medium" if confidence >= MEDIUM else "Low"


def _cosine(a: list[float], b: list[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else None


def min_similarity(members: list[Theme]) -> float | None:
    """The lowest pairwise centroid similarity in a group; None when any member has no stored centroid."""
    if any(not t.centroid for t in members):
        return None
    sims = [_cosine(a.centroid, b.centroid) for i, a in enumerate(members) for b in members[i + 1:]]
    return None if any(s is None for s in sims) else round(min(sims), 3)


def _extract_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None


def validate(raw: str, id_of: dict[int, int], themes_by_id: dict[int, Theme]) -> tuple[list[dict], list[dict], int]:
    """Groups and near-misses that survive the checks, and how many proposed groups were dropped. A group
    is kept only if its members are known numbers, not "Other", not already in a kept group, and at least
    2; groups are considered strongest first so a weaker overlapping one is the one dropped."""
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return [], [], 0
    proposed = [g for g in data.get("groups") or [] if isinstance(g, dict)]

    def conf(g: dict) -> int:
        c = g.get("confidence")
        return max(0, min(100, int(c))) if isinstance(c, (int, float)) and not isinstance(c, bool) else 0

    used: set[int] = set()
    groups, dropped = [], 0
    for g in sorted(proposed, key=lambda g: -conf(g)):
        members = g.get("members")
        ids = []
        if isinstance(members, list):
            ids = [id_of.get(m) for m in members if isinstance(m, int) and not isinstance(m, bool)]
        ids = list(dict.fromkeys(i for i in ids if i is not None))
        ok = (isinstance(members, list) and len(ids) == len(members) and len(ids) >= 2
              and not any(themes_by_id[i].label == "Other" for i in ids) and not used & set(ids))
        if not ok:
            dropped += 1
            continue
        used |= set(ids)
        members_t = [themes_by_id[i] for i in ids]
        c = conf(g)
        sim = min_similarity(members_t)
        shown = band(c)
        if shown == "High" and sim is not None and sim < SIMILARITY_CUTOFF:
            shown = "Medium"  # Claude is sure, but the answers are not close in meaning
        name = g.get("name") if isinstance(g.get("name"), str) and g.get("name").strip() else max(members_t, key=lambda t: t.size).label
        reason = g.get("reason") if isinstance(g.get("reason"), str) else ""
        groups.append({"name": name.strip()[:120], "member_ids": ids, "confidence": c, "band": shown,
                       "similarity": sim, "reason": reason.strip()[:600],
                       "share_answers": sum(t.size for t in members_t)})
    groups.sort(key=lambda g: (-g["confidence"], -g["share_answers"]))

    kept = []
    for k in data.get("kept_apart") or []:
        if not isinstance(k, dict) or not isinstance(k.get("members"), list):
            continue
        ids = [id_of.get(m) for m in k["members"] if isinstance(m, int) and not isinstance(m, bool)]
        if len(ids) >= 2 and all(i is not None for i in ids):
            kept.append({"names": [themes_by_id[i].label for i in ids[:2]],
                         "reason": (k.get("reason") if isinstance(k.get("reason"), str) else "").strip()[:400]})
    return groups, kept, dropped

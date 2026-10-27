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

import numpy as np
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


# ---------------------------------------------------------------- graph grouping (DECISIONS 2026-10-28)
# The themes' stored centroids find the candidates; one Claude call checks every candidate against sample
# answers, may drop a theme that does not belong, and names the groups it keeps (user's decision: the
# graph alone let through wrong merges such as parking cost + parking safety, tools/eval_grouping.py).
# Each theme is a node; two themes are linked by how close their answers are in meaning (cosine of the
# centred centroids). Complete linkage keeps a group only when EVERY pair in it clears the cutoff, so
# chains (A like B, B like C, A not like C) never become one group. Cutoffs from tools/eval_grouping.py
# on datasets 12 and 13 (centred similarity: median about 0, 99th percentile about 0.6).
CUTOFF = 0.70  # every pair in a candidate group at least this similar
BORDER = 0.60  # two units whose weakest pair is from here up to CUTOFF are a "close call" candidate
HIGH_SIM = 0.80  # a kept group whose weakest pair is at or above this: band High
TONE_SPLIT = 0.3  # sentiment at or above +this vs at or below -this: opposite tone, never linked
MAX_GROUP = 20  # the merge endpoint's own limit (api_themes.MergeGroup)
MAX_BORDERLINE = 30
MIN_CENTRED = 6  # fewer themes than this: no reliable shared mean to remove, so no groups, only close calls
RAW_BORDER = 0.9  # ... and those close calls use raw similarity
CENTROID_ANSWERS = 200  # answers embedded per theme when its centroid has to be filled in


def graph_nodes(themes: list[Theme]) -> list[Theme]:
    """The themes the graph can compare: not "Other", with a stored centroid. Largest first, then by id,
    so the same themes always give the same groups."""
    return sorted((t for t in themes if t.label != "Other" and t.centroid), key=lambda t: (-t.size, t.id))


def similarity_matrix(nodes: list[Theme], centre: bool | None = None) -> "np.ndarray":
    """Cosine similarity of the themes' centroids AFTER removing what all of them share. Answers to one
    survey question all sit close together in meaning (raw centroid similarity is about 0.9 for almost
    every pair on the workplace surveys, tools/eval_grouping.py), so the column's size-weighted mean
    centroid is subtracted first and only what sets each theme apart is compared. Needs a handful of
    themes to mean anything: below MIN_CENTRED the raw similarity is returned (see graph_suggestions)."""
    m = _unit(np.asarray([t.centroid for t in nodes], dtype=float))
    if len(nodes) >= MIN_CENTRED if centre is None else centre:
        w = np.asarray([max(t.size, 1) for t in nodes], dtype=float)
        m = _unit(m - (w[:, None] * m).sum(axis=0) / w.sum())
    return np.clip(m @ m.T, -1.0, 1.0)


def _unit(m: "np.ndarray") -> "np.ndarray":
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


def tone_blocked(a: Theme, b: Theme) -> bool:
    """Opposite tone: one theme clearly positive and the other clearly negative (e.g. "pay is fair" and
    "pay is too low" are about the same topic and should not merge). Unknown tone never blocks."""
    sa, sb = getattr(a, "sentiment", None), getattr(b, "sentiment", None)
    if sa is None or sb is None:
        return False
    return (sa >= TONE_SPLIT and sb <= -TONE_SPLIT) or (sb >= TONE_SPLIT and sa <= -TONE_SPLIT)


def _blocked_matrix(nodes: list[Theme]) -> "np.ndarray":
    n = len(nodes)
    out = np.zeros((n, n), dtype=bool)
    for i in range(n):
        for j in range(i + 1, n):
            out[i, j] = out[j, i] = tone_blocked(nodes[i], nodes[j])
    return out


def _unit_similarity(sim: "np.ndarray", a: list[int], b: list[int]) -> float:
    """Complete linkage: two sets of themes are only as close as their least similar pair."""
    return float(sim[np.ix_(a, b)].min())


def _weakest_pair(sim: "np.ndarray", g: list[int]) -> float:
    """The least similar pair inside one group (the diagonal, a theme with itself, does not count)."""
    return float(min(sim[i, j] for k, i in enumerate(g) for j in g[k + 1:]))


def tight_groups(sim: "np.ndarray", blocked: "np.ndarray", cutoff: float) -> list[list[int]]:
    """Indexes of the nodes in each group of 2..MAX_GROUP whose every pair is at least `cutoff` similar
    and not tone-blocked. Complete-linkage clustering (scipy), cut at distance 1 - cutoff."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    n = len(sim)
    if n < 2:
        return []
    dist = 1.0 - sim
    dist[blocked] = 3.0  # farther than any cutoff: a blocked pair can never end up in one group
    np.fill_diagonal(dist, 0.0)
    dist = np.clip((dist + dist.T) / 2, 0.0, None)
    labels = fcluster(linkage(squareform(dist, checks=False), method="complete"), t=1.0 - cutoff + 1e-9,
                      criterion="distance")
    by_label: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        by_label.setdefault(int(lab), []).append(i)
    groups = [g for g in by_label.values() if 2 <= len(g) <= MAX_GROUP]
    return sorted(groups, key=lambda g: g[0])


def borderline_pairs(sim: "np.ndarray", blocked: "np.ndarray", groups: list[list[int]],
                     border: float, cutoff: float) -> list[tuple[list[int], list[int], float]]:
    """Close calls: two units (a group or a single theme) whose least similar pair is in [border, cutoff),
    with no tone-blocked pair between them. The closest MAX_BORDERLINE, closest first."""
    grouped = {i for g in groups for i in g}
    units = [list(g) for g in groups] + [[i] for i in range(len(sim)) if i not in grouped]
    out = []
    for x in range(len(units)):
        for y in range(x + 1, len(units)):
            a, b = units[x], units[y]
            if len(a) + len(b) > MAX_GROUP or blocked[np.ix_(a, b)].any():
                continue
            s = _unit_similarity(sim, a, b)
            if border <= s < cutoff:
                out.append((a, b, round(s, 3)))
    out.sort(key=lambda p: (-p[2], p[0][0], p[1][0]))
    return out[:MAX_BORDERLINE]


def graph_suggestions(themes: list[Theme], cutoff: float = CUTOFF, border: float = BORDER,
                      centre: bool | None = None) -> dict:
    """The graph's answer for a column: groups (theme ids, weakest-pair similarity), close calls, and
    tone-blocked pairs that would otherwise have been linked. No network. `centre` None: centre when there
    are at least MIN_CENTRED themes (tests pass it explicitly)."""
    nodes = graph_nodes(themes)
    missing = sum(1 for t in themes if t.label != "Other" and not t.centroid)
    if len(nodes) < 2:
        return {"groups": [], "borderline": [], "tone_blocked": [], "missing_centroids": missing, "_sim": {}}
    sim = similarity_matrix(nodes, centre)
    blocked = _blocked_matrix(nodes)
    if centre is None and len(nodes) < MIN_CENTRED:
        cutoff, border = 1.01, RAW_BORDER  # too few themes to trust a group: Claude judges the close calls
    groups = tight_groups(sim, blocked, cutoff)
    ids = lambda idx: [nodes[i].id for i in idx]  # noqa: E731
    out_groups = [{"member_ids": ids(g), "similarity": round(_weakest_pair(sim, g), 3)} for g in groups]
    out_groups.sort(key=lambda g: (-g["similarity"], -len(g["member_ids"])))
    near = borderline_pairs(sim, blocked, groups, border, cutoff)
    tone = [(nodes[i].id, nodes[j].id, round(float(sim[i, j]), 3))
            for i in range(len(nodes)) for j in range(i + 1, len(nodes)) if blocked[i, j] and sim[i, j] >= border]
    return {"groups": out_groups,
            "borderline": [{"a": ids(a), "b": ids(b), "similarity": s} for a, b, s in near],
            "tone_blocked": sorted(tone, key=lambda p: -p[2]), "missing_centroids": missing,
            "_sim": {(a.id, b.id): float(sim[i, j]) for i, a in enumerate(nodes) for j, b in enumerate(nodes) if i < j}}


def candidates(graph: dict) -> list[dict]:
    """What Claude is asked to check: every graph group, then every close call as the union of its two
    sides, strongest first. Ids "c1".."cN"."""
    out = [{"member_ids": g["member_ids"], "similarity": g["similarity"], "close_call": False} for g in graph["groups"]]
    out += [{"member_ids": b["a"] + b["b"], "similarity": b["similarity"], "close_call": True} for b in graph["borderline"]]
    out.sort(key=lambda c: (-c["similarity"], c["close_call"]))
    for i, c in enumerate(out, start=1):
        c["id"] = f"c{i}"
    return out


def weakest_similarity(graph: dict, ids: list[int]) -> float | None:
    """The least similar pair among `ids`, from the graph's own (centred) similarities."""
    sim = graph.get("_sim") or {}
    vals = [sim.get((a, b), sim.get((b, a))) for k, a in enumerate(ids) for b in ids[k + 1:]]
    return None if not vals or any(v is None for v in vals) else round(min(vals), 3)


CHECK_SYSTEM = (
    "You check suggested merges of survey themes. You get a numbered list of themes (name, answer count, "
    "two sample answers) and a list of candidates, each a set of theme numbers that are close in meaning. "
    "For each candidate decide whether its themes are about the same issue and should be merged. Same topic "
    "is not enough: different causes, places, or opposite views (for example parking cost versus parking "
    "safety, or enough space versus not enough space) mean they stay apart. You may drop themes that do not "
    "belong from a candidate, but never add any. For each candidate kept, give a short plain name (at most "
    "6 words) and one sentence saying why the themes belong together. For each candidate rejected, give one "
    "sentence saying why. Reply with JSON only, no prose before or after it: "
    '{"candidates": [{"id": str, "merge": bool, "drop": [int, ...], "name": str, "reason": str}]}.'
)
CHECK_SAMPLES = 2


def build_check_payload(cands: list[dict], themes: list[Theme], clean_df: pd.DataFrame, plan: CleaningPlan,
                        column: str) -> tuple[dict, dict[int, int]]:
    """What Claude is sent to check `cands`: only the themes that appear in a candidate, numbered 1..N, each
    with its name, answer count, share and CHECK_SAMPLES masked answers (`model_safe_rows`), and the
    candidates as lists of those numbers. Never row ids, other columns or the other themes."""
    by_id = {t.id: t for t in themes}
    used = list(dict.fromkeys(i for c in cands for i in c["member_ids"]))
    total = sum(t.size for t in themes) or 1
    wanted = [r for i in used for r in (by_id[i].answer_refs or [])[:40]]
    masked = model_safe_rows(clean_df, plan, column, wanted) if wanted else {}
    number_of, id_of, listed = {}, {}, []
    for n, i in enumerate(used, start=1):
        t = by_id[i]
        number_of[i], id_of[n] = n, i
        listed.append({"id": n, "name": t.label, "answers": t.size, "share": round(t.size / total * 100, 1),
                       "samples": _samples(masked, list(t.answer_refs or [])[:40])[:CHECK_SAMPLES]})
    return ({"themes": listed,
             "candidates": [{"id": c["id"], "themes": [number_of[i] for i in c["member_ids"]]} for c in cands]},
            id_of)


def _names(by_id: dict[int, Theme], ids: list[int]) -> str:
    return " + ".join(by_id[i].label for i in ids)


def apply_check(raw: str, cands: list[dict], id_of: dict[int, int], by_id: dict[int, Theme],
                graph: dict) -> tuple[list[dict], list[dict], int]:
    """Groups and near-misses from Claude's verdicts. Claude can only keep, reject or shrink a candidate;
    anything it adds, or a verdict that cannot be read, counts as rejected. Kept candidates are taken
    strongest first; one overlapping an accepted group is taken only when it contains that whole group
    (a close call extending it), else skipped. Returns (groups, kept_apart, rejected)."""
    data = _extract_json(raw)
    verdicts = {}
    if isinstance(data, dict):
        for v in data.get("candidates") or []:
            if isinstance(v, dict) and isinstance(v.get("id"), str):
                verdicts.setdefault(v["id"], v)
    groups: list[dict] = []
    owner: dict[int, dict] = {}
    kept_apart, rejected = [], 0
    for c in cands:
        v = verdicts.get(c["id"])
        reason = v.get("reason").strip()[:600] if v and isinstance(v.get("reason"), str) else ""
        if not v or v.get("merge") is not True:
            rejected += 1
            if v:  # a candidate Claude skipped is just not suggested
                kept_apart.append({"names": [_names(by_id, c["member_ids"][:1]), _names(by_id, c["member_ids"][1:])],
                                   "reason": reason})
            continue
        drop_nums = v.get("drop") if isinstance(v.get("drop"), list) else []
        drop = {id_of.get(n) for n in drop_nums if isinstance(n, int) and not isinstance(n, bool)}
        ids = [i for i in c["member_ids"] if i not in drop]
        if len(ids) < 2:
            rejected += 1
            continue
        hit = {id(owner[i]) for i in ids if i in owner}
        if hit:
            g = owner[next(i for i in ids if i in owner)]
            if len(hit) > 1 or not set(g["member_ids"]) <= set(ids) or len(ids) > MAX_GROUP:
                continue  # overlaps a kept group without simply extending it
            g["member_ids"] = list(dict.fromkeys(g["member_ids"] + ids))
            for i in ids:
                owner[i] = g
            continue
        name = v.get("name") if isinstance(v.get("name"), str) and v.get("name").strip() else max(
            (by_id[i] for i in ids), key=lambda t: t.size).label
        g = {"name": name.strip()[:120], "member_ids": ids, "reason": reason}
        groups.append(g)
        for i in ids:
            owner[i] = g
    out = []
    for g in groups:
        sim = weakest_similarity(graph, g["member_ids"])
        out.append({**g, "similarity": sim, "confidence": round((sim or 0) * 100),
                    "band": "High" if sim is not None and sim >= HIGH_SIM else "Medium",
                    "share_answers": sum(by_id[i].size for i in g["member_ids"])})
    out.sort(key=lambda g: (-(g["similarity"] or 0), -g["share_answers"]))
    for a, b, _s in graph["tone_blocked"][:5]:
        kept_apart.append({"names": [by_id[a].label, by_id[b].label], "reason": "Similar topic, opposite tone."})
    return out, kept_apart, rejected


def unchecked_groups(graph: dict, by_id: dict[int, Theme]) -> list[dict]:
    """When Claude cannot be reached: only the graph's strongest groups, marked Low because nobody checked
    them, named after their biggest theme."""
    out = []
    for g in graph["groups"]:
        if g["similarity"] < HIGH_SIM:
            continue
        ids = g["member_ids"]
        out.append({"name": max((by_id[i] for i in ids), key=lambda t: t.size).label, "member_ids": ids,
                    "similarity": g["similarity"], "confidence": round(g["similarity"] * 100), "band": "Low",
                    "reason": f"Not checked: Claude could not be reached. Every theme here is at least "
                              f"{round(g['similarity'] * 100)}% alike in meaning.",
                    "share_answers": sum(by_id[i].size for i in ids)})
    return out


def ensure_centroids(themes: list[Theme], clean_df: pd.DataFrame, plan: CleaningPlan, column: str,
                     embedding_client: Any) -> int:
    """Fills in `centroid` for themes built before it was stored: the mean embedding of up to
    CENTROID_ANSWERS of the theme's answers, masked through `model_safe_rows` exactly like the theme build,
    in one batched embed call. Returns how many answers were embedded (0: nothing to do, no call)."""
    todo = [t for t in themes if t.label != "Other" and not t.centroid and t.answer_refs]
    if not todo:
        return 0
    wanted = [r for t in todo for r in list(t.answer_refs)[:CENTROID_ANSWERS]]
    masked = model_safe_rows(clean_df, plan, column, wanted)
    texts, owner = [], []
    for t in todo:
        for r in list(t.answer_refs)[:CENTROID_ANSWERS]:
            text = masked.get(r)
            if text and text.strip():
                texts.append(text)
                owner.append(t)
    if not texts:
        return 0
    vectors = np.asarray(embedding_client.embed(texts), dtype=float)
    for t in todo:
        idx = [i for i, o in enumerate(owner) if o is t]
        if idx:
            t.centroid = [round(float(v), 4) for v in vectors[idx].mean(axis=0)]
    return len(texts)

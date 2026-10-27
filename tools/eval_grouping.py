"""Compare graph theme grouping with Claude's last grouping, to pick the cutoffs (DECISIONS 2026-10-27).

    PYTHONPATH=. .venv/bin/python tools/eval_grouping.py <dataset_id> [<dataset_id> ...] [--fill]

For each column with themes, runs the graph at several cutoffs and prints its groups, close calls and
timing; where Claude grouped the column before (profile.theme_grouping_cache), its groups are shown too,
with pair agreement.
Makes no Claude call. Themes built before centroids were stored have none: --fill embeds up to
200 masked answers per such theme with Voyage (paid, small; the count is printed first) and saves them.
"""
from __future__ import annotations

import sys
import time

import numpy as np
from dotenv import load_dotenv

CUTOFFS = (0.66, 0.70, 0.72, 0.75, 0.78)


def pairs(groups: list[list[int]]) -> set[tuple[int, int]]:
    return {(a, b) for g in groups for i, a in enumerate(sorted(g)) for b in sorted(g)[i + 1:]}


def main(ids: list[int], fill: bool) -> None:
    load_dotenv(".env")
    from app import db as _db
    from app import theme_grouping as tg
    from app.api_themes import _load_clean_df, _stored_themes
    from sqlalchemy import select

    from app.models import Dataset, Theme

    with _db.SessionLocal() as s:
        for dataset_id in ids:
            ds = s.get(Dataset, dataset_id)
            cache = (ds.profile or {}).get("theme_grouping_cache") or {}
            columns = sorted(set(s.scalars(select(Theme.column_name).where(Theme.dataset_id == ds.id))))
            for column in columns:
                entry = cache.get(column) or {}
                themes = _stored_themes(s, ds.id, column)
                if not themes:
                    continue
                by_id = {t.id: t for t in themes}
                clean_df, plan = _load_clean_df(ds, s)
                missing = [t for t in themes if t.label != "Other" and not t.centroid]
                if missing:
                    n = sum(min(len(t.answer_refs or []), tg.CENTROID_ANSWERS) for t in missing)
                    print(f"\nDataset {ds.id} {column!r}: {len(missing)} themes have no centroid ({n} answers to embed).")
                    if not fill:
                        print("  Skipped: run again with --fill to embed them (Voyage, paid).")
                        continue
                    from app.api_themes import get_embedding_client
                    t0 = time.perf_counter()
                    done = tg.ensure_centroids(themes, clean_df, plan, column, get_embedding_client())
                    s.commit()
                    print(f"  Embedded {done} answers in {time.perf_counter() - t0:.1f}s; centroids saved.")

                if len(tg.graph_nodes(themes)) < 2:
                    continue
                claude, fresh = [], False
                if entry:
                    payload, id_of = tg.build_payload(themes, clean_df, plan, column)
                    fresh = entry.get("hash", "").endswith(tg.payload_hash(payload))
                    claude, _kept, _dropped = tg.validate(entry.get("reply") or "", id_of, by_id)
                claude_groups = [g["member_ids"] for g in claude]
                name = lambda i: by_id[i].label  # noqa: E731

                nodes = tg.graph_nodes(themes)
                sim = tg.similarity_matrix(nodes)
                upper = sim[np.triu_indices(len(nodes), 1)]
                adaptive = round(max(0.66, float(np.percentile(upper, 99))), 3)
                print(f"\n=== Dataset {ds.id}, column {column!r}: {len(nodes)} themes")
                print(f"Pair similarity: median {np.median(upper):.2f}, 90th {np.percentile(upper, 90):.2f}, "
                      f"97th {np.percentile(upper, 97):.2f}, 99th {np.percentile(upper, 99):.2f}, max {upper.max():.2f}. Adaptive cutoff: {adaptive}")
                if not entry:
                    print("Claude has not grouped this column: no comparison.")
                else:
                    print(f"Claude's cached groups ({'matches the current themes' if fresh else 'THEMES CHANGED since, mapping may be off'}):")
                for g in claude:
                    print(f"  [{g['band']} {g['confidence']}%, sim {g['similarity']}] {g['name']}: "
                          f"{', '.join(name(i) for i in g['member_ids'])}")

                for cutoff in sorted({*CUTOFFS, adaptive}):
                    border = round(cutoff - 0.1, 2)
                    t0 = time.perf_counter()
                    out = tg.graph_suggestions(themes, cutoff=cutoff, border=border)
                    ms = (time.perf_counter() - t0) * 1000
                    graph_groups = [g["member_ids"] for g in out["groups"]]
                    gp, cp = pairs(graph_groups), pairs(claude_groups)
                    both = len(gp & cp)
                    prec = f"{both / len(gp):.0%}" if gp else "-"
                    rec = f"{both / len(cp):.0%}" if cp else "-"
                    tag = " (adaptive)" if cutoff == adaptive else ""
                    print(f"\n-- cutoff {cutoff}{tag}, close calls from {border}: {len(graph_groups)} groups, "
                          f"{len(out['borderline'])} close calls, {len(out['tone_blocked'])} tone-blocked, {ms:.1f} ms. "
                          f"Agreement with Claude: {prec} of the graph's pairs, {rec} of Claude's pairs.")
                    for g in out["groups"]:
                        print(f"   group sim {g['similarity']}: {', '.join(name(i) for i in g['member_ids'])}")
                    for b in out["borderline"][:8]:
                        print(f"   close {b['similarity']}: {' + '.join(name(i) for i in b['a'])}  <>  "
                              f"{' + '.join(name(i) for i in b['b'])}")
                    for a, b, sv in out["tone_blocked"][:5]:
                        print(f"   tone-blocked {sv}: {name(a)} <> {name(b)}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--fill"]
    if not args:
        sys.exit(__doc__)
    main([int(a) for a in args], "--fill" in sys.argv)

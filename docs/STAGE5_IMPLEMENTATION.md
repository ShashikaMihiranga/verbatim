# Stage 5: medium chart connections

Owner: Codex. Shared task: STAGE5-WIRE-01. Date: 2026-10-24.

## Boundaries agreed for parallel work

Claude owns Stage 3's `findings.py`, `findings_structured.py`, `report_blocks.py` and their existing
unit tests. Codex owns the report adapter, chart presentation, API response wiring and related UI.
The shared board records exact reservations. No replacement scoring engine, changed finding gates,
extra headline/model call, migration or change to the existing top-five candidate cap is required.

## Investigation

The claim that every item is entirely unwired is too broad: sunburst/icicle already exist as theme
tabs. The other existing renderers have real data producers but cannot be reached from their matching
finding on the report. Two gaps need special care: `mekko` shows **themes by sentiment**, not **group
size by theme mix**; and `binnedGrid` describes two numeric columns, not an existing theme finding.
The production segment context caps groups at eight. The Stage 5 presentation adapter reads the
confirmed winning segment column for the same filtered answer rows to recover 8–20 eligible groups
for dot comparisons, preserving the heatmap cap and candidate pool. Likewise, it reuses the existing
grid producer to cover a numeric column paired with a score, which the numeric-only producer loop skips.

## Implementation

| Capability | Connection | Eligibility / fallback |
| --- | --- | --- |
| theme_hierarchy / compact | Existing overview tabs and canonical hierarchy findings, with responsive sunburst → icicle display | Shared sub-theme gate; use the overview's fluid HTML icicle at a 390px design width so mobile labels stay readable |
| theme_flow | Alternate view of score-correlation or segment-skew finding | At least three real themes and valid positive group counts/mixes; segment data adapted explicitly to score-band shape |
| group_mix | New Marimekko renderer; alternate view of segment-skew finding | Width is surviving group n; height is that group's theme percentages; residual share clearly labeled Other / not shown |
| group_split_bars | Alternate view of segment-skew finding | Exactly two surviving groups |
| compare_dots | Alternate view of segment-skew finding | Eight to twenty surviving groups; compare the finding's theme, not an unrelated largest theme |
| slope_change | Alternate view of trend-shift finding | Two valid aligned endpoints; current production trend input still requires three surviving periods |
| binned_grid | Collapsed numeric exploration after findings, before quotes/quality | At least two non-suppressed cells across both numeric axes; no confidence badge or generated finding claim |

One finding keeps one sentence, confidence badge and answer drill-down. Chart choices replace its
visual rather than appending duplicate story blocks. The original chart stays the default, preserving
Claude's selection and stored report/export behavior. Options are recomputed from current filtered
data on every report view and disappear when their requirements no longer hold. Selection falls back
when filtering removes an option. Existing clients can ignore the additive response fields.

Sankey group-to-theme weights are derived from rounded cross-tab percentages, and its theme-to-tone
weights use each theme's overall tone split. Label this estimate explicitly, rather than claiming a
known per-answer path. The numeric grid similarly uses the already-implemented theme-average tone
estimate; small cells remain withheld. These charts do not establish a causal relationship.

The numeric grid exploration is not a new candidate kind. Promoting a particular grid contrast into
a scored finding would need a separately reviewed effect threshold, confidence rule and headline
schema change. The grid is still available now through a clearly labeled exploration, without silently
replacing the user's chosen ranking logic.

## Validation and handoff

Exercise live-data fixtures through report GET/build, empty/filtered data, thin hierarchies, two/eight
group selection, correct finding-theme comparison, segment-only flow, fully suppressed grids and
escaping. Check responsive UI and tab replacement after a filter update. Run existing backend report,
chart and sharing/export checks plus frontend tests/build. Record results on the shared task board.
No paid API calls or existing user datasets need rebuilding to make the new choices appear.

## Completed validation and integration notes

- Integrates with Claude's completed Stage 3 (`49af78c`) and Stage 4 theme-mix choice (`aa67adf`).
  Those owned source files and their scoring tests were not modified by this task.
- Additive API fields: `block.chart_variants` sits alongside the block's existing `finding`;
  `compact_chart_id` pairs hierarchy views; top-level `explorations` carries grids.
  The saved canonical chart, headline, confidence, candidate count and raw-score order remain intact.
  Selecting another view is local UI state; exports continue using the saved canonical report view.
- Filter checks recompute all options from current rows. A source-column fallback cannot silently
  attach an alternative for a different measure. A discovered existing empty-trend crash is guarded.
- Full backend regression: **867 passed, 1 skipped, 5 pre-existing local auth/security configuration
  failures** (the same `.env`/Clerk configuration cases recorded before this task). No Stage 5 failure
  remains. Final focused report/chart/API run: **159 passed**, plus the final adapter run **14 passed**.
- PNG/PPTX/PDF export checks: **3 passed** with Chromium. No export behavior change was introduced.
- Frontend: **106 passed**; production build passed. Lint has the six pre-existing warnings and no errors.
- Browser fixture verification: real tab clicks, estimation note, desktop Sunburst/mobile Icicle at
  1280px/390px, and no JavaScript errors. Compact labels retain font size; a numeric key covers thin cells.
- Renderer registry now has **34** entries. `groupMix` has its own golden fixture and `test_frame_count`
  was intentionally updated. Future renderer additions must update these same compatibility checks.

The numeric grid is deliberately available as an exploration, not a newly scored finding. The
remaining Stage 4 small-multiple/sparse renderers and unrelated composer work are separate tasks.

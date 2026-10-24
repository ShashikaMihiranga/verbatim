# Report UI fixes — shared Claude / Codex backlog

Created 2026-10-24 from the user's screenshots of `/report?dataset=11` at an 888px viewport.
This is a separate UI workstream. Tasks were initially Ready/unassigned; Codex subsequently claimed
and implemented UI-REPORT-01 through UI-REPORT-05. Live status and ownership are on the shared task board, under `UI-REPORT-*`.

## Scope boundary

Frontend presentation and interaction only. Use the existing report response and existing data.
Do not edit backend routes, Python chart generators, database models, APIs, finding selection,
thresholds, sentiment, saved headlines, report generation or chart-assignment logic.
Do not change statistical meaning or silently hide findings to make the report appear less repetitive.
If a fix requires new server metadata or a renderer change, record the dependency separately; do not
extend these UI tasks into backend development. This backlog authorizes no deployment or paid rebuild.

The screenshots confirm tooltip collisions, excess spacing and repetitive presentation. They do not
confirm a sunburst defect: the marked element's description and attached image do not match. Treat
sunburst/tablet behavior as an investigation until reproduced with authorized browser access.

## Ordered to-do list

### UI-REPORT-01 — P1: selected-cell explanations and tooltip collisions

- [x] Stop the persistent dark heatmap callout from covering group headers and sample counts.
- [x] Preserve the selected-cell outline and its actual data.
- [x] Present the selected comparison as an inline caption; any transient tooltip must support
      hover and keyboard focus, stay in bounds, and clear when interaction ends.
- [x] Use stable semantic hooks in the fragment integration; no generated React IDs, nth-child
      selectors, copied dataset values or replacement of server-provided text with invented values.
- [ ] Verify long labels and a selected cell at both left and right edges.

Acceptance: every group label, n and percentage remains readable without dismissing an overlay;
the explanation is accessible without a mouse. If semantic hooks are insufficient, document the
renderer dependency rather than editing Python as part of this task.

### UI-REPORT-02 — P1: compact chart sizing and consistent section spacing

- [x] Remove unnecessary minimum-height blank space for short, single-row finding charts.
- [x] Reconcile wrapper spacing with existing fragment padding; avoid stacking several independent
      sets of margins around the same chart.
- [ ] Align the finding headline, controls, plot and caption to a coherent report grid.
- [x] Preserve space needed by large charts and avoid fixed-height clipping.
- [x] Keep the continuous page layout and existing design tokens.

Acceptance: a one-row comparison occupies its content height, without a large empty canvas; longer
charts remain fully visible. Desktop, tablet and mobile screenshots show consistent section rhythm.

### UI-REPORT-03 — P1: tablet and mobile chart behavior

- [ ] Reproduce the reported sunburst problem before calling it confirmed.
- [ ] Inspect widths 390, 640, 888, 1024 and 1280px, including long theme/group names.
- [x] Provide a readable compact hierarchy view where the existing response supplies one; choose
      its breakpoint from the chart's available width rather than a phone-only assumption.
- [ ] Prevent chart/list collisions, compressed heatmap labels and page-level horizontal overflow.
- [ ] When scrolling is necessary, confine it to the chart and make it apparent; retain label readability.
- [ ] Verify score-group bars, tabs, badges and See answers controls at narrow widths.

Acceptance: labels and values are readable at each target width, with no unintended overlap or clipped
controls. Do not manufacture a new compact chart or change server rendering in this UI task.

### UI-REPORT-04 — P2: big picture first and fewer repeated introductions

- [x] Put the broad overview before detailed findings in the reading order.
- [x] Replace the full duplicate What stands out list with a concise linked outline, or another
      presentation that avoids repeating every finding sentence verbatim.
- [x] Make the finding sentence the primary heading; reduce redundant Focus/generic question/subtitle
      layers while retaining the theme identity, denominator and method where needed.
- [x] Keep all saved findings, confidence labels and See answers links available.
- [x] Use meaningful heading elements and stable section anchors.

Acceptance: the report reads from broad context to specific evidence without several introductions
before each small chart. No backend ranking, candidate selection or headline rewriting.

### UI-REPORT-05 — P2: reduce repeated full-context controls

- [x] Present equivalent All themes exploration views in one shared place using existing response data.
- [x] Distinguish shared overview/exploration controls from finding-specific evidence controls.
- [x] Make repeated comparison sections more compact; use presentation grouping only where existing
      metadata establishes the relationship. Do not infer relationships by parsing headline prose.
- [x] Preserve access to every finding and its source answers; do not drop equal-looking charts solely
      because they share a chart type.
- [x] Keep Other visibly identifiable as a catch-all/display bucket; do not relabel it as a specific
      discovered topic. Correcting generated claims or classifying its contents is outside this UI scope.

Acceptance: users can distinguish a new insight from another way to explore the same broad data;
equivalent full-context tabs are not repeated in every finding section.

### UI-REPORT-06 — P1 release gate: UI verification and handoff

- [ ] Capture before/after screenshots at the target widths using authorized browser access.
- [ ] Check tooltip/caption behavior, tab switching, filter updates, focus visibility, See answers,
      compact hierarchy switching and empty/filtered comparison states.
- [ ] Test keyboard navigation and check for console errors and page overflow.
- [x] Run relevant existing frontend tests, build and lint; add focused coverage for actual regressions
      rather than tests that merely assert HTML strings differ.
- [x] Record screenshot paths, commands/results, remaining limitations and the reviewed commit.
- [x] Confirm no backend files, data contracts, findings or stored numbers changed.

Acceptance: visual evidence demonstrates the fixes, not merely passing data tests. Do not claim a live
or mobile check passed when browser access was unavailable. No push/deploy is included.

## Coordination

Open `python3 tools/agentboard.py`, then choose Tasks, or run `python3 tools/taskboard.py list`.
Both Claude and Codex can read the same board in this checkout. Claim a task before implementation,
check current Git changes and follow `docs/COLLABORATION.md`. Tasks are sequential because they touch
shared chart wrappers and CSS. Split scopes explicitly before attempting parallel implementation.

The checklist is the acceptance specification; the task board is the source of current status and
ownership. Update checklist items and attach validation evidence when completing each task.


## Implementation handoff — 2026-10-24

UI-REPORT-01 through 05 are implemented locally by Codex. UI-REPORT-06 remains in Review: automated
checks pass, but live visual acceptance has not passed and no screenshots are claimed.

Changes: existing selected heatmap text moves into an inline accessible note; gallery minimum heights
are removed from the page; fragment padding is normalized; hierarchy uses its provided compact view
below a 1000px container width; heatmaps retain readable columns with local keyboard-scrollable regions;
score rows wrap on narrow containers; nested viewport breakout is removed. The overview comes first,
headlines appear once, generic finding chart questions are visually suppressed, and identical full-context
views appear once in a collapsed exploration area. Distinct context data and all findings remain available.

Validation:
- `cd frontend && npm test`: 117 passed across 18 files.
- `cd frontend && npm run build`: TypeScript and Vite production build passed.
- `cd frontend && npm run lint`: zero errors, six existing warnings in unrelated files.
- `git diff --check`: passed. No Python, API, data contract or database files changed.
- DOM regressions cover caption relocation/refresh, left/right selected cells, intrinsic plot height,
  compact-view boundaries, overview order, single headlines, retained badges/answer buttons,
  broad-context deduplication and input non-mutation.

Live check limitation: user explicitly approved a retry, but the browser tool still returned
"A saved user permission setting blocks this action" for localhost:8000. No alternate browser or raw
network workaround was attempted. A user must change the saved site permission before the live
888px report and 390/640/1024/1280px viewport screenshots can be verified. The sunburst overlap remains
an unconfirmed reported defect; a responsive fallback was implemented but not visually signed off.

Exports still use the unchanged backend rendering path, so these frontend presentation improvements
do not alter exported PNG/PDF/PPTX layout. Any export parity work belongs to a separately scoped task.

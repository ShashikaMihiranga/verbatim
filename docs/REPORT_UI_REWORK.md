# Report UI rework: match the Other-Flow design, less text, one question per chart

Hand-off document and live checklist. Written 2026-10-24, before any UI code, so either Claude or Codex can
continue from here without the conversation that produced it. **Keep the checkboxes current. Tick a box
only when its acceptance criteria and tests pass.**

## How to resume (read this first)

1. Read this file top to bottom. Then read the decision entries in `docs/DECISIONS.md` dated 2026-10-24:
   "decisions before work…" (commit `c96d2df`) and "RACE-GUARD-01 done" (commit `182c891`).
2. Run `python3 tools/taskboard.py list`. Claim the next unticked phase's task ID before editing anything
   (`docs/COLLABORATION.md`), and use the exact file scope listed for that phase.
3. Run `git status`. If `frontend/src/{ThemeChart,FindingChartTabs,Report}.tsx` or `report.css` show as
   modified, or `report-ui.test.tsx` shows as deleted, **stop and resolve Phase 0 first**.
4. Do the phase, then run the verification commands at the bottom.
5. Commit to `staging` with explicit file names (never `git add -A`). Add a `docs/DECISIONS.md` entry.
6. Tick the boxes here and close the board task.

## Status

| Phase | Task ID | What | Status |
|---|---|---|---|
| 0 | (user) | Restore 34919df frontend files, release `UI-REPORT-07` | [x] done by the user |
| bug | `RACE-GUARD-01` | Report build and theme rebuild can't overlap | [x] done, `182c891` |
| doc | `REPORT-UI-DOC` | This document | [x] done |
| 1 | `REPORT-UI-1` | Backend data for Inside Other, live progress, honest step names, treemap Other labels | [x] done |
| 2 | `REPORT-UI-2` | Inside Other UI (flow, three columns, step rail, done state, charts) | [ ] |
| 3 | `REPORT-UI-3` | Page order and text trim; overview without tabs | [ ] |
| 4 | `REPORT-UI-4` | Visual / interaction / accessibility gate at 1280, 888 and 390px | [ ] |
| 5 | `REPORT-UI-5` | Follow-ups (audit finding variants; catch-all new theme), user approval needed | [ ] |
| – | – | Add a pointer to this doc from `docs/UI_FIXES.md` | [x] done |

## Why this work exists

- **Too much text, too little picture.** The report page stacks about 15 sections, many with helper
  paragraphs. The design shows about 8 short helper lines in total. The user has spent three days trying
  to get it to match the design.
- **Inside Other doesn't match the design:**
  - Its ribbons and step list disappear when the run finishes.
  - "Known themes" shows only a total.
  - "Still in Other" doesn't say what it was before the run.
  - A bar chart is labelled "Sankey".
  - An "Arc" tab shows only an apology.
- **The overview repeats itself.** It offers six tabs drawing the same theme data in different shapes.

## User decisions (2026-10-24) — do not reopen without the user

1. **Ownership.** The user restores Codex's committed `34919df` frontend files (the working copies were an
   accidental rollback) and releases `UI-REPORT-07`. The report UI then belongs to this rework.
2. **Live counts.** While "Look inside Other" runs, the per-theme numbers must tick up from **real job
   progress**. A simulated count-up is not acceptable.
3. **No Arc.** Each answer belongs to exactly one theme, so there is no co-occurrence to draw. Remove the Arc
   tab and the design's "map how themes connect" step.
4. **No tab rows for the overview, and one question per chart.** Lay the charts out below the treemap, but
   keep only charts that show *different* information. The user's words: "if is show the same data in the
   different chart that doesn't make sense, each chart needs to show data that chart can show to get the
   better idea not the every chart for same data".

## Rules every phase must follow

**Text budget**
- Each section has at most **one heading** and **one one-clause subtitle**.
- No paragraphs, no "how to read this" blurbs.
- Every value is printed on the visual. Colour never carries a value alone (`CLAUDE.md`).

**One question per chart**
- Before adding a chart, write the one question it answers.
- If another chart on the page already answers that question with the same data, don't add it.

**Design system (`CLAUDE.md`, `design/HANDOFF.md` §6)**
- Jost only. Light theme tokens (`--bg --surface --ink --muted --line --accent`, `--t1..--t7`, `--other`,
  `--neg --neu --pos`).
- No gradients, shadows, pies or donuts.
- One continuous page on `--bg` with content about 1084px wide. Dividers (1px `--line` top borders), not
  boxed cards. Sections 44–56px apart.

**Motion**
- Animations stop under `prefers-reduced-motion`.

**Honesty**
- Never draw a chart from invented data.
- If something can't be computed, show nothing or one short line saying why.

## Design references

| File | Role |
|---|---|
| `verbatim-visual-system/generator/gen_otherflow.py` | **Source of truth**: markup, geometry, script |
| `verbatim-visual-system/generator/gen_otherflow_variants.py` | Produces the Mid and Done snapshots |
| `verbatim-visual-system/project/Other-Flow.dc.html` | Idle state |
| `verbatim-visual-system/project/Other-Flow-Mid.dc.html` | Running state |
| `verbatim-visual-system/project/Other-Flow-Done.dc.html` | Finished state |
| `design/HANDOFF.md` §3, §4.2, §6 | Report page anatomy, `inside_other` placement |

The `.dc.html` files only render inside the Claude Design canvas. Read the generator instead. Its numbers
are demo data (5,830 answers, Other 75.5% → 63.7%). Build from real job data.

**Not to ship from the design:**
- the "Snapshot" pills
- "Reset this demo"
- "Everything it found, five ways" (a static gallery in the Done file only)

## Target page, top to bottom

| # | Section | Component(s) | What it shows | Text allowed |
|---|---|---|---|---|
| 1 | Title and summary | `Report.tsx` | The question; "N themes found, overall tone x" | as now |
| 2 | Question context | `QuestionContext.tsx` | Sentence with the question-type dropdown | **Remove** the meta line "Framing and answer length are measured…" |
| 3 | Columns and filters | `Report.tsx`, `ReportFilters.tsx` | Column chips and filter selects in **one row** | none |
| 4 | **What are the themes?** | overview treemap (`ThemeChart`, server `overview`) | Share of each theme and its sub-themes. Other block: "Look inside ↓"; "Drawn smaller than its real share" only when its area is capped | "Block area is share of answered. Sub-themes sit inside their theme." |
| 5 | **Inside Other** | new `InsideOther*` components (Phase 2) | Flow from Other → known themes / new themes / Still in Other, three columns, step rail; when done a banner and the result charts | status line plus "Each ribbon is a group of answers. Wider ribbon, more answers." |
| 6 | **How does each theme sound?** | server `diverge` | Negative / neutral / positive per theme | one subtitle |
| 7 | **What stands out** | `FindingBlock`, `FindingChartTabs` | Per finding: sentence, Solid/Tentative badge, See answers, its chart | none |
| 8 | Quotes, phrases, "Can I trust this?" | `SupplementBlock`, quality | as now | existing one-line subtitles |

### One question per chart: overview

| Chart | Question it answers | Decision |
|---|---|---|
| Treemap (with sub-themes) | What are the themes, how big, what's inside them? | **Keep** |
| Tone split (`diverge`) | How does each theme sound? | **Keep** |
| Icicle | Same hierarchy as the treemap | Remove; keep only as the treemap's phone layout under 640px |
| Sunburst | Same hierarchy | Remove |
| Sentiment sun | Same tone as the tone split | Remove |
| Rank | Share is already in the treemap, tone in the tone split | Remove |

### Text to remove

| Text | Where |
|---|---|
| "Themes for {column}. Every theme links back to real answers…" | `.th-summary`, `Themes.tsx` around line 547 (report view only) |
| "{x}% of answers aren't in the 7 themes shown above.", "We found N distinct topics…", the two stat tiles | `OtherExploration.tsx`. The numbers move into Inside Other's columns; the "See all N themes" list moves under Still in Other. |
| "Other is a catch-all bucket, not a single topic…" | `Report.tsx`, `.rp-method-note` after OtherExploration |
| "These views show the broader context under the current filters…" | `Report.tsx`, "Explore all themes" |
| "Framing and answer length are measured from the answers…" | `QuestionContext.tsx` |

## Inside Other spec (built from the design, mapped to real data)

### Header
- "Inside Other" (30px/600), then the button:
  - idle: **"Look inside →"**
  - running: hidden
  - done: **"Look inside again"**
- Status row with a blinking `--accent` dot while running, and `aria-live="polite"` text. It shows the
  current step's label, or "Done. Everything is updated above."
- One helper line: "Each ribbon is a group of answers. Wider ribbon, more answers."

### Flow SVG (design viewBox 1328×316, `width:100%`)

**Source.** Ribbons start at the bottom edge of the Other block, stacked left to right across its width.

**Width.** `answers × usableWidth / otherBeforeCount`, at least 3.6px. Still in Other takes the remainder.

**Leaves and colours**

| Leaf group | Colour | Leaves |
|---|---|---|
| Known themes | `--t1..--t7` | one per known theme, in the same order as the treemap |
| New themes | accent ladder `color-mix(--accent N%, --surface)`, N = 100/82/68/56/44/34 | up to 6 |
| Still in Other | `--other` at opacity .5 | one |

Numbered circles under each leaf match the numbered rows in the columns below.

**States**

| State | Ribbons | Motion |
|---|---|---|
| Idle | Only Still in Other (full width) | none |
| Running | Widths from `job.progress` (Phase 1) | moving dots (`animateMotion`); a dash on wide ribbons; pulsing leaf rings |
| Done | Static final picture from `job.result` | none |

Under `prefers-reduced-motion`: no dots, dashes or pulses.

**Phones.** On narrow screens the flow may be replaced by the three columns alone. The numbers must stay.

### Three columns (grid 36% / 36% / 28%, aligned under the leaf groups)

Each column has a 3px top border in its colour, a 20px/600 title, a 13.5px muted subtitle, and a 44px/300
number.

**Known themes** (border `--t1`)
- Subtitle: "Answers that match a theme already in the chart"
- Number: "+{known total} answers"
- Rows: number chip in `--tN`, name, mini bar (90×8, relative to the largest gain), then "+x.x%"
  (gain ÷ answered total).

**New themes found** (border `--accent`)
- Subtitle: "Patterns no known theme covered"
- Number: "{new total} answers, {k} themes"
- Rows: accent-tint chip, name, mini bar, share.

**Still in Other** (border `--other`)
- Subtitle: "Varied answers that don't repeat enough to group"
- Number: "{still} answers"
- Line: "{x}% of all answers. It was {y}% before this run."
- Bar: width = current share ÷ share before.
- A "See all N themes" link that opens the full theme list (moved from `OtherExploration`).

### Step rail (four honest steps; these replace the old labels)

| # | Label | Real work (`app/api_themes.py` look_inside_other `_work`) |
|---|---|---|
| 1 | Finding patterns in Other | embed and re-cluster Other's answers |
| 2 | Naming new themes | label and consolidate the new clusters |
| 3 | Matching answers to themes | Jev classification, **with live progress** |
| 4 | Updating the report | `_apply_other_classification` |

- Each step reads Done (accent dot showing "ok"), Running (accent ring), or Waiting (muted).
- Connector bars fill as steps finish. Step 3's bar follows `progress.done / progress.total`.

### Done state
- Banner: a check circle, then "Done. {k} new themes found. Other went from {y}% to {x}%.", then "new"
  chips (badge + name + share).
- Result charts **laid out one after another, no tabs**, each answering a different question:

| Chart | Question | Source |
|---|---|---|
| Known-theme gains | How many answers did each existing theme gain? | React bars from `known_gains` |
| New themes, ranked and tone-coloured | Which new themes are biggest, and how do they sound? | server `rank` in `result.charts` |
| Sub-themes of the new themes | What's inside each new theme? | server `icicle`, **only when at least one new theme has sub-themes** |

- **Remove:** `othergrowth` (it's a bar chart labelled "Sankey"), `sentsun`, and Arc.
- **Keep:** the treemap's "Looking inside…" ring while running (`ThemeChart` `highlightOtherRunning`).

## Data contract (Phase 1 adds the new fields)

**Current `job.result` for `look_inside_other`**
- Built in `_apply_other_classification`, `app/api_themes.py` around lines 417-594.
- Fields: `known_added`, `new_themes: [{label, count, sentiment, tone}]`, `still_other_count`,
  `failed_classification_count`, and `charts` (`othergrowth`, `rank`, `icicle`, `sentsun`).

**Fields to add**

| Field | Type | Source |
|---|---|---|
| `other_before_count` | int | `len(other.answer_refs)` before Other is changed (capture near the top of the function) |
| `answered_total` | int | answers analysed for the column (denominator for every share) |
| `known_gains` | `[{label, count}]` | from the local `matched_known` dict, largest first |
| `new_themes[].sub_themes` | optional | only if the icicle needs it from the frontend; otherwise keep the server `icicle` chart |
| `charts` | | keep `rank` and `icicle`, drop `othergrowth` and `sentsun` |

**New `Job.progress`** (nullable JSON column, Alembic migration, returned by `job_dict` in `app/jobs.py`)
- Written only during step 3:

```json
{"done": 1240, "total": 20684, "known": {"Temperature control": 310, "...": 0},
 "new": {"Office layout": 120}, "still_other": 45}
```

- Where to hook it:
  - `classify_other_answers` (`app/text_pipeline/other_classify.py` around line 145) maps rows through a
    `ThreadPoolExecutor` (`pool.map`, around line 183) and writes `out.by_row[row] = answer.choice`
    (around line 188).
  - Add an optional `on_progress(done, total, by_row)` callback, **throttled to about once a second**.
  - In the route, turn `by_row` into the known / new / still-other counts using the known label set, the
    new label set and `NONE_OF_THESE`. Count failed rows as still in Other.
  - Write it through a `set_progress(job_id, payload)` helper next to `_set_step` in `app/jobs.py` (its
    own short-lived session, same pattern).
- The frontend already polls the job (`pollJob` in `frontend/src/jobsApi.ts`), so the new field just needs
  adding to the `Job` type.

## Phases

### Phase 0: prerequisite, done by the user

```
git checkout HEAD -- frontend/src/ThemeChart.tsx frontend/src/FindingChartTabs.tsx frontend/src/Report.tsx frontend/src/report.css frontend/src/report-ui.test.tsx
python3 tools/taskboard.py release UI-REPORT-07 --agent user --message "Restored 34919df; report UI handed to Claude (REPORT-UI-REWORK)"
```

- [x] `git status` shows none of those files modified, and the board shows `UI-REPORT-07` released.

### Phase 1 — `REPORT-UI-1`: backend data

**Scope**
- `app/api_themes.py` (look_inside_other `_work`, `_apply_other_classification`, `_build_other_result_charts`)
- `app/text_pipeline/other_classify.py`
- `app/jobs.py`, `app/models.py`, a new `migrations/versions/*_job_progress.py`
- `app/charts.py` (`treemap_html` Other cell)
- `tests/test_api_themes.py`, `tests/test_other_classify.py`, `tests/test_charts_data.py`, `tests/golden/*`

**Tasks**
- [x] Result fields `other_before_count`, `answered_total`, `known_gains`. Drop `othergrowth` and `sentsun`.
- [x] `Job.progress` column, migration, `job_dict`.
- [x] Throttled `on_progress` in `classify_other_answers`, wired through `set_progress` during step 3.
- [x] Step labels renamed to the four honest names. Check the frontend for anything keyed on the old
      strings (`LookInsideOther.tsx` `STEPS`).
- [x] Treemap Other cell: "Look inside ↓" always when Other exists; "Drawn smaller than its real share"
      only when `_treemap_areas` capped Other's area. Regenerate goldens and review each diff.

**Acceptance and tests**
- Unit tests for the new result fields against a real `_apply_other_classification` run.
- Progress payload shape, and throttling (no more than one write per interval).
- Migration upgrade and downgrade.
- `job_dict` includes progress.
- Golden diffs show only the two labels.

### Phase 2 — `REPORT-UI-2`: Inside Other UI

**Scope**
- New `frontend/src/InsideOther.tsx` (plus `InsideOtherFlow.tsx`, `InsideOtherColumns.tsx`,
  `InsideOtherSteps.tsx` if that keeps files small), CSS in `report.css`
- `jobsApi.ts` types
- Delete `LookInsideOther.tsx`, `LookInsideOtherRibbons.tsx` and `LookInsideOtherCharts.tsx` and their
  tests once the new ones cover them
- `Report.tsx` (mount point only, in this phase)

**Tasks**
- [ ] Header, status, helper line, button states.
- [ ] Flow SVG: idle / running (from `job.progress`) / done (from `job.result`), reduced motion.
- [ ] Three columns with numbered rows, "It was y% before this run", "See all N themes".
- [ ] Step rail with step 3 progress.
- [ ] Done banner, chips, and the result charts laid out without tabs (gains, rank, icicle only when
      sub-themes exist).
- [ ] Failure state: one line showing `job.error`, plus "Look inside" again.
- [ ] Keep the existing warning for `failed_classification_count > 0`, shortened to one line.

**Acceptance and tests** (vitest with the `// @vitest-environment jsdom` docblock)
- Each state renders correctly.
- Ribbon widths are proportional to counts, with the 3.6px minimum.
- Live counts update when `job.progress` changes.
- No Arc, `othergrowth` or `sentsun`.
- Reduced motion removes the animations.
- No horizontal overflow at 390px.

### Phase 3 — `REPORT-UI-3`: page order and text trim

**Scope**
- `frontend/src/Report.tsx`, `Themes.tsx` (summary line only), `QuestionContext.tsx`, `ThemeChartTabs.tsx`
  (replace or retire), `OtherExploration.tsx` (retire; its list moves into Inside Other), `report.css`
- `report.test.tsx`, `report-ui.test.tsx`, `themechart-tabs.test.tsx`, `other-exploration.test.tsx`

**Tasks**
- [ ] Page order exactly as in the target table.
- [ ] Overview: treemap, then tone split, no tab row. The icicle is used only as the treemap's phone
      layout.
- [ ] Remove every line in the text-to-remove table.
- [ ] Spacing per the design system rules.

**Acceptance and tests**
- Page order test.
- None of the removed strings render.
- No `role="tablist"` in the overview.
- Each overview chart is distinct.
- Existing tests still pass, or are updated to match a decision recorded here.

### Phase 4 — `REPORT-UI-4`: visual and accessibility gate

- [ ] Screenshots at 1280, 888 and 390px of: dataset 11 report; Inside Other idle, running and done
      (run it on dataset 11, which is smaller); dataset 12 after the user's rebuild.
- [ ] Keyboard pass: buttons, dropdown, See answers. Focus visible.
- [ ] Console clean. No horizontal page overflow.
- [ ] Compare side by side with `Other-Flow-Done.dc.html` / `-Mid` (from the generator). List any
      intentional differences here.

### Phase 5 — `REPORT-UI-5`: follow-ups (only with the user's approval)

- [ ] Audit the alternative views on each finding (Codex Stage 5, `chart_variants`) against the
      one-question-per-chart rule. List what to keep or drop for the user to decide.
- [ ] Investigate dataset 12's look-inside result: 5,833 of 6,041 new answers went into one broad theme
      ("Office Layout and Facility Condition").
  - Likely cause: Jev classification against a broad merged label, with no size or confidence cap.
    `confidence_by_row` is computed but unused (`other_classify.py`); union-find merging can chain labels
    (`merging.py`).
  - Propose a fix; don't change it without the user.

## Known traps

- **The rollback.** Phase 0 exists because the working copies of four report files plus a deleted test were
  an exact copy of the state before `34919df`. Don't build on those working copies.
- **Chart fragments are server HTML** (`app/charts.py`), inserted with `dangerouslySetInnerHTML` by
  `ThemeChart.tsx`.
  - Python chart changes need a **backend restart**:
    `pkill -f "uvicorn app.main:app"; .venv/bin/python -m uvicorn app.main:app --port 8000`
  - Golden files in `tests/golden/` pin the gallery frames. Regenerate deliberately and review the diffs.
  - Report-only rendering goes through `render_report_parts` (single-panel sunburst, context sentence).
    Don't change gallery frames for report needs.
- **The vitest environment is `node`.** DOM tests need `// @vitest-environment jsdom` at the top. Static
  render tests use `renderToStaticMarkup`.
- **`:8000` serves the built `frontend/dist`,** which can be stale. Check UI work on the Vite dev server
  `:5173`, or run `npm run build`.
- **Paid calls.** Building a report and look-inside-other call Claude/Jev; building themes calls the
  embedding service and Claude. Don't trigger them just to check something. Insert a test `Job` row (and
  delete it afterwards) to exercise job-state UI.
- **The build-race guard** (`RACE-GUARD-01`) returns 409 if you start a report while themes or look-inside
  jobs are running for the same column, and the reverse. That is expected.
- **Codex runs in the same working tree.** Before staging, check `git diff --stat` and stage only your own
  files.

## Verification commands

```
.venv/bin/python -m pytest -q                         # backend: all pass (901 at 182c891)
cd frontend && npm test -- --run                      # frontend: all pass (110 at 182c891)
cd frontend && npx tsc --noEmit                       # clean
cd frontend && npm run lint                           # 6 existing warnings, no new ones
```

## Change log

- 2026-10-24 — Document created (`REPORT-UI-DOC`). The bug fix (`RACE-GUARD-01`, `182c891`) landed before
  it. Phase 0 is waiting on the user. The pointer from `docs/UI_FIXES.md` waits for Phase 0, because that
  file is in `UI-REPORT-07`'s scope.
- 2026-10-24 — Phase 0 done by the user: the five files restored to `34919df`, `UI-REPORT-07` released.
  Pointer added to `docs/UI_FIXES.md`.
- 2026-10-24 — Phase 1 (`REPORT-UI-1`) done. Notes for Phase 2:
  - Result fields, `Job.progress` (migration `3c7e1f2a9b40`), throttled progress, renamed steps
    (`LookInsideOther.tsx` `STEPS` updated to match) and the result charts reduced to `rank` (+ `icicle` only
    when a new theme has sub-themes) are in.
  - The treemap hint is report-only: `render_report_parts("overview")` → `f_overview(report=True)` →
    `treemap_html(other_hint=True)`. Gallery frames and golden files are unchanged.
  - The hint is skipped when the Other box has no room (under 80×64; the "Drawn smaller…" line needs 120×84),
    and when the overview uses its icicle layout. On dataset 12 the capped Other box is a narrow column (about
    54×186), so no in-box hint shows there. Phase 2's ribbons must start from the Other block's real position
    (`[data-theme="Other"]` in the overview fragment) to make that link visually.
  - Live counts can fold slightly at the end: new groups smaller than `MIN_OTHER_NEW_THEME_SIZE` go back into
    Other in the final result. The done state reads `job.result`.

# Bug log

One checklist for every bug found in Verbatim, by Claude, Codex or the user. **Log a bug here as soon as it
is found, even if it gets fixed in the same session.** Tick it only when the fix is committed and tested.

## How to log a bug

Add a row under **Open** with the next free ID (`BUG-NNN`, never reused):

```
- [ ] **BUG-NNN — <one-line symptom, as a user would see it>**
  - Found: <date>, <who>, <where: dataset / screen / test>
  - Cause: <root cause, once known>
  - Fix: <commit> · Test: <test name or "live check only">
```

When it is fixed, fill in Cause and Fix, tick the box and move it to **Fixed** (newest first).
If it needs the user's decision or a paid call, say so on the Found line and leave it open.

## Open

- [ ] **BUG-041 — Region findings compare against the wrong baseline, so they are false (dataset 12)**
  - Found: 2026-10-25, Claude, from the user's dataset 12 screenshot. Three findings say "privacy, safety,
    and layout design for patient care" is almost never mentioned in regions 9, 11 and 3 ("about a thirtieth
    as often as overall").
  - Cause: only 24,961 of 40,000 rows have a Region. The theme has 1,351 answers but only 39 of them have a
    Region. The heatmap's "overall 3.4%" is the theme's share of *all* answers; each region cell is its share
    of that region's answers. Among rows that have a Region the theme is 0.16% overall, so no region is
    unusual. `build_segment_data` takes `SegmentRow.overall` from `ThemeNode.share` (docstring: "never a
    value recomputed from this subset"), which is wrong when many rows have no group.
  - Fix: proposed - compute `overall` over rows that have a group (`app/findings_structured.py`), and add a
    test with missing groups. Same check for score and date (`build_score_data`, `build_trend_data`).
- [ ] **BUG-042 — The same theme gets several near-identical findings (one per region)**
  - Found: 2026-10-25, Claude, dataset 12: three heatmap findings, same theme and chart, only the
    highlighted cell differs.
  - Fix: proposed - at most one segment finding per theme (keep the strongest). Recheck after BUG-041,
    which removes these three anyway.
- [ ] **BUG-043 — With 120 themes, the treemap shows 7 and folds 113 into "Other 50.7%"; Inside Other
  then says Other is 0%**
  - Found: 2026-10-25, user (screenshot) and Claude, dataset 12. The treemap's Other = 12 unthemed answers
    + 113 real themes that have no colour (`other_breakdown.hidden_real_share` 50.7). Inside Other only
    counts the 12 unthemed answers ("0% of all answers. It was 1.7% before"), so the two sections
    contradict each other.
  - Fix: needs a user decision - e.g. call the treemap block "113 more themes" instead of "Other", and/or
    show the folded themes in Inside Other's "See all 120 themes". Also why 120 themes: see BUG-048.
- [ ] **BUG-044 — The overview draws the icicle on desktop for dataset 12, with rotated, broken labels**
  - Found: 2026-10-25, user (screenshot). `_prefers_icicle` picks the icicle when the treemap can't fit;
    labels then rotate and break mid-word ("Temperat ure", "Privac y"), sub-themes hang below, there is a
    large empty area under the biggest theme, and no "Look inside ↓" hint.
  - Fix: proposed - in the report, keep the treemap on desktop and show tiny themes as labelled slivers;
    no mid-word breaks.
- [ ] **BUG-045 — Known themes in Inside Other show "+0%" for real gains**
  - Found: 2026-10-25, dataset 12: 18 answers out of 39,718 rounds to 0.0%, printed as "+0%".
  - Fix: proposed - print the answer count when the share rounds to 0 (e.g. "+18").
- [ ] **BUG-046 — "Done. Everything is updated above." while the report is stale**
  - Found: 2026-10-25, dataset 12: Look inside finished after the report was built; the findings are still
    the old ones (stale banner at the top).
  - Fix: proposed - when the report is stale say "Done. Rebuild the report to update the findings."
- [ ] **BUG-047 — While the report loads (about 6 s on dataset 12), the page shows the theme-editing view
  with "Build report"**
  - Found: 2026-10-25, user (second screenshot) and Claude. `GET /report` takes 5.7 s; until it returns the
    page shows the treemap, theme card, a 121-checkbox merge list and "Ready to build the report".
  - Fix: proposed - show a loading line for the report instead of the editing view; make the merge list
    a search box rather than 121 checkboxes.
- [ ] **BUG-048 — Dataset 12 has 120 themes, many of them junk ("No comment provided", "Survey not
  applicable or irrelevant", "Non-substantive or referential response")**
  - Found: 2026-10-25, Claude. Theme build gave 46 clusters; splits and repeated Look inside runs added the
    rest. Look inside creates new themes from non-answers.
  - Fix: needs a user decision; ties in with BUG-032.
- [ ] **BUG-049 — A heatmap opened scrolled sideways, with its theme-name column cut off**
  - Found: 2026-10-25, Claude, dataset 12 at 1568px: the first heatmap's scroll box was at its end
    (32 of 32px), hiding the left labels.
  - Cause: not found yet (no code scrolls it). Needs a repro.
- [ ] **BUG-031 — Dataset 12's report still shows findings for deleted themes**
  - Found: 2026-10-24, Claude, dataset 12 report. Leftover from BUG-022, which stops it happening again.
  - Cause: the report was built while a theme rebuild was running (BUG-022).
  - Fix: press Rebuild report on dataset 12. **User's call** (one paid Claude call).
- [ ] **BUG-032 — Look inside Other put 5,833 of 6,041 answers into one new theme on dataset 12**
  - Found: 2026-10-24, Claude, dataset 12 ("Office Layout and Facility Condition").
  - Cause (likely, not confirmed): Jev classifies against a broad merged label with no size or confidence
    cap. `confidence_by_row` is computed but unused (`other_classify.py`); union-find merging can chain
    labels (`merging.py`).
  - Fix: investigate in `REPORT-UI-5`. **Needs the user's approval** before any change.
- [ ] **BUG-033 — Curly apostrophes split words in the sentiment tokenizer ("don’t" → "don", "t")**
  - Found: 2026-10-24, Claude, during the phrase-apostrophe fix (BUG-003 only fixed phrases).
  - Fix: **needs a user decision** (it changes sentiment scores on existing datasets).
- [ ] **BUG-034 — Score-group sentiment is an approximation, not computed per answer**
  - Found: 2026-10-24, Claude, UI review of dataset 11.
  - Fix: **needs a user decision** on whether to compute it exactly.
- [ ] **BUG-035 — Before a run, Inside Other's ribbon area is mostly empty**
  - Found: 2026-10-25, Claude, dataset 11 at 1280px. One Still-in-Other ribbon on the right, blank space on
    the left.
  - Fix: compare with `Other-Flow.dc.html` in Phase 4 (`REPORT-UI-4`).
- [ ] **BUG-036 — On dataset 12 the treemap's Other block has no "Look inside ↓" hint**
  - Found: 2026-10-24, Claude. The capped Other box is about 54px wide, below the 80×64 the hint needs.
  - Fix: Phase 4 to decide (the Inside Other section sits right under it, so the link is still visible).
- [ ] **BUG-037 — The phone overview is headed "Themes and sub-themes", desktop "What are the themes?"**
  - Found: 2026-10-25, Claude, phone width. The phone layout reuses the icicle fragment and its header.
  - Fix: minor; align in Phase 4.
- [ ] **BUG-038 — The server still builds three overview charts the page no longer shows**
  - Found: 2026-10-25, Claude, Phase 3. `report_medium.theme_views` builds `sentsun`, `rank` and
    `sunburst`; only `icicle` and `diverge` are used. Wasted work and payload, nothing visible.
  - Fix: trim `theme_views` (check that no finding uses them first).
- [ ] **BUG-039 — `localhost:8000` serves an old frontend build**
  - Found: 2026-10-24, Claude. `:8000` serves `frontend/dist`, which isn't rebuilt automatically.
  - Fix: run `npm run build` before using `:8000`, or check UI on the Vite dev server `:5173`.

## Fixed

- [x] **BUG-040 — A Look inside run where every answer failed reported "Done. No new themes found"**
  - Found: 2026-10-25, user's real run on dataset 11 (job 47). All 314 answers failed with
    `Jev returned HTTP 402` (payment required: the Jev account looks out of credit).
  - Cause: `classify_other_answers` logged "EVERY row failed" but the job still finished as done.
  - Fix: `55d6ebd`; when every answer fails the job fails before anything is applied, with the reason
    and a hint ("…Jev returned HTTP 402 (payment required: check the Jev account's credit)."). The page shows
    it with the Look inside button. · Test:
    `test_look_inside_other_fails_with_the_real_reason_when_every_answer_fails`.
  - Still on the user: top up the Jev credit.
- [x] **BUG-030 — The overview showed the icicle instead of the treemap on desktop**
  - Found: 2026-10-25, Claude, live check during Phase 3 (before commit).
  - Cause: `ResponsiveChart` switches to the compact chart under a 1000px container (right for the
    sunburst); the page column is narrower, so it always switched.
  - Fix: `f3db8ce`, `compactOnPhoneOnly` (640px) · Test: live check at 1280px and phone width.
- [x] **BUG-029 — Inside Other showed an empty status row and "–" for Still in Other before a run**
  - Found: 2026-10-25, Claude, dataset 11.
  - Fix: `f3db8ce`; idle shows Other's real count from the report · Test: `inside-other.test.tsx`
    "idle: Still in Other shows the current count and share".
- [x] **BUG-028 — On phones the "Each ribbon is a group of answers" line showed with no ribbons**
  - Found: 2026-10-25, Claude, 390px check. Fix: `44ceb81` · Test: live check only.
- [x] **BUG-027 — Look inside Other's "What should we fix first?" chart said "Milder than average" for
  every new theme**
  - Found: 2026-10-25, Claude, Phase 2 live check.
  - Cause: the server rank chart compared each new theme's tone with a placeholder overall average of 0.00.
  - Fix: `44ceb81`; replaced by bars coloured by each theme's own tone · Test: `inside-other.test.tsx`
    "done: … '62% negative'".
- [x] **BUG-026 — Inside Other's ribbons and steps disappeared when a run finished; ribbon widths were
  theme shares, not answer counts; Known themes showed only a total**
  - Found: 2026-10-24, user and Claude, compared with `Other-Flow-Done.dc.html`.
  - Fix: `c3c9b48` (data) + `44ceb81` (panel) · Test: `inside-other.test.tsx`, `inside-other-model.test.ts`.
- [x] **BUG-025 — A bar chart in Look inside Other was labelled "Sankey", and an "Arc" tab showed only
  an apology**
  - Found: 2026-10-24, Claude. Fix: `c3c9b48` + `44ceb81` (both dropped) · Test: `inside-other.test.tsx`.
- [x] **BUG-024 — Look inside Other's step names didn't describe the real work**
  - Found: 2026-10-24, Claude. Fix: `c3c9b48` · Test: `tests/test_api_themes.py`.
- [x] **BUG-023 — After a reload, a running theme rebuild wasn't shown and Build report stayed enabled**
  - Found: 2026-10-24, Claude, dataset 12. Cause: `Themes.tsx` only resumed a themes job when no themes
    existed yet. Fix: `182c891` · Test: live check only.
- [x] **BUG-022 — A report could be built while themes were being rebuilt for the same column**
  - Found: 2026-10-24, Claude, dataset 12 (report job 11:32 ran inside themes job 11:30–11:35).
  - Cause: nothing linked the report and theme job slots.
  - Fix: `182c891`, 409 both ways via `blocking_job` · Test: 3 tests in `tests/test_api_themes.py`.
- [x] **BUG-021 — The same sentiment-sun chart repeated across several findings (dataset 12)**
  - Found: 2026-10-24, user (screenshot).
  - Cause: findings pointed at deleted themes (see BUG-022) and fell back to another theme's chart.
  - Fix: `5e30d11`; orphaned findings say the theme no longer exists · Test: `tests/test_api_report.py`.
- [x] **BUG-020 — Rebuilding themes left the old report in place**
  - Found: 2026-10-24, Claude. Fix: `5e30d11`, rebuild invalidates the report; stale notice in
    `Themes.tsx` · Test: `tests/test_api_themes.py`.
- [x] **BUG-019 — Footer buttons wrapped one by one instead of as groups**
  - Found: 2026-10-24, Claude, UI review of dataset 11. Fix: `b7aefac` · Test: live check only.
- [x] **BUG-018 — "See answers" listed each answer twice**
  - Found: 2026-10-24, Claude. Cause: AnswerList loaded twice. Fix: `b7aefac` · Test: live check.
- [x] **BUG-017 — The icicle tab didn't fill the width on desktop**
  - Found: 2026-10-24, Claude. Fix: `b7aefac` (container query) · Test: `tests/test_report_medium.py`.
- [x] **BUG-016 — A flat exploration grid (all cells nearly equal) was still shown**
  - Found: 2026-10-24, Claude. Fix: `b7aefac`, withheld below `GRID_MIN_SPREAD` 0.05 · Test:
    `tests/test_report_medium.py`.
- [x] **BUG-015 — ID columns were used as numbers in findings**
  - Found: 2026-10-24, Claude. Fix: `b7aefac`, `looks_like_identifier` · Test: `tests/test_findings.py`.
- [x] **BUG-014 — The overview's "typical length" wasn't the median**
  - Found: 2026-10-24, Claude. Fix: `b7aefac` · Test: golden `overview.html`.
- [x] **BUG-013 — Treemap labels split words mid-word instead of hyphenating**
  - Found: 2026-10-24, Claude. Fix: `b7aefac` · Test: golden `treemap.html`.
- [x] **BUG-012 — Small-theme sunburst callouts sat on the wrong side of their wedge**
  - Found: 2026-10-24, Claude. Fix: `b7aefac` · Test:
    `test_sunburst_callout_for_a_small_left_hand_theme_sits_on_the_left`.
- [x] **BUG-011 — Tone-split bars ran into the label column**
  - Found: 2026-10-24, Claude. Fix: `b7aefac`, scaled to free room · Test:
    `test_tone_split_bars_never_reach_the_label_column`.
- [x] **BUG-010 — Shares under 5% were clipped inside thin bars**
  - Found: 2026-10-24, Claude. Fix: `b7aefac`, printed below the bar · Test:
    `test_score_group_thin_segments_print_their_value_under_the_bar_not_clipped_inside`.
- [x] **BUG-009 — Score-group pills for positive groups were red**
  - Found: 2026-10-24, Claude. Fix: `b7aefac`, tone by sign · Test:
    `test_score_group_sentiment_pill_is_tinted_by_its_own_sign`.
- [x] **BUG-008 — The question-context block was a static mockup with its menu permanently open**
  - Found: 2026-10-24, user (screenshot). Fix: `f4555ad`, real dropdown that saves a correction ·
    Test: `tests/test_api_context.py`, frontend context tests.
- [x] **BUG-007 — The backend test suite read the developer's `.env` (5 "flaky" failures)**
  - Found: 2026-10-24, Claude. Fix: `f05c256`, conftest stops loading `.env` · Test: full suite.
- [x] **BUG-006 — Phrases showed stray apostrophes (from answers like "I'm 5'4")**
  - Found: 2026-10-24, Claude. Fix: `f05c256` · Test: `tests/test_text_pipeline_phrases.py`.
- [x] **BUG-005 — Quotes and phrases ignored the report filters**
  - Found: 2026-10-24, Claude. Fix: `f05c256` · Test: `tests/test_api_report.py`.
- [x] **BUG-004 — The report sunburst was drawn twice (gallery side-by-side panel)**
  - Found: 2026-10-24, Claude. Fix: `f05c256`, single-panel report sunburst · Test:
    `test_report_sunburst_is_one_panel_not_the_gallery_two_state_demo`.

IDs BUG-001 to BUG-003 are reserved for bugs fixed before this log existed; see `docs/DECISIONS.md` and
`docs/TODO.md` for those.

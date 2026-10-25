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

- [ ] **BUG-052 — A region finding can be about "Other", the catch-all**
  - Found: 2026-10-25, Claude, local check of the BUG-050 tests on dataset 11: "Other" is 41.7% in
    Initmates vs 15.7% overall, a real (q < 0.001) but unhelpful finding - it says Initmates answers are
    harder to theme, not what they talk about.
  - Fix: **needs a user decision**: drop Other from segment findings, or keep it reworded ("harder to
    group"). Not changed.
- [ ] **BUG-031 — Dataset 12's report still shows findings for deleted themes**
  - Found: 2026-10-24, Claude, dataset 12 report. Leftover from BUG-022, which stops it happening again.
  - Cause: the report was built while a theme rebuild was running (BUG-022).
  - Fix: press Rebuild report on dataset 12. **User's call** (one paid Claude call).
  - 2026-10-25: still open. Rebuild report on dataset 12 is a paid call; Claude's attempt was blocked by the permission check, so the user clicks Rebuild report.
- [ ] **BUG-034 — Score-group sentiment is an approximation, not computed per answer**
  - Found: 2026-10-24, Claude, UI review of dataset 11.
  - Fix: **needs a user decision** on whether to compute it exactly.
  - 2026-10-25: investigated. The pill is a count-weighted average of each theme's stored sentiment; per-answer sentiment is not stored (DECISIONS 2026-09-25). Exact values need Jev calls or a stored per-answer column. **User decision**; behaviour unchanged.

## Fixed

- [x] **BUG-057 — On Railway, theme builds fail at the end and Look inside Other can never start**
  - Found: 2026-10-25, the user (Jobs page on Railway devapp: tss_fy19_comments_10k.csv, Build themes,
    "Something went wrong while building this"). Railway log: `StringDataRightTruncation: value too long
    for type character varying(16)` on `INSERT INTO jobs ... kind='look_inside_other'`.
  - Cause: `jobs.kind` is VARCHAR(16) and "look_inside_other" is 17 characters. Postgres enforces it;
    SQLite (local and tests) does not, so every Look inside job had always failed on Railway, and since the
    automatic run (2026-10-25) the theme build that queues it failed too, after its themes were saved.
  - **Fixed:** (this commit). Migration `5d2b8e7c1f03` widens `jobs.kind` to VARCHAR(32) (Railway runs
    `alembic upgrade head` before each deploy). `_queue_auto_look_inside` now catches a failure to create
    the job: the theme build stays done and its result says Look inside could not start on its own.
    Tests: `test_theme_build_stays_done_when_look_inside_cannot_start`, and
    `test_every_job_kind_fits_the_kind_column`, which checks every kind passed to `create_job` against the
    column length, since SQLite will not.

- [x] **BUG-056 — Question-type menu opens as a huge system popup, and changing the type changes nothing**
  - Found: 2026-10-25, the user (screenshot of the macOS popup over "This question asks for ..."): "fix
    these formatting and change the rest of the themes or report according to this".
  - Cause: a native `<select>` set in the 36px sentence; macOS draws its menu at that size in the system
    font. The saved type was only displayed: theme naming and finding sentences never received it.
  - **Fixed:** (this commit). `QuestionContext.tsx` has a styled menu (button + listbox, keyboard model,
    page font at 17px, spans so it is valid inside the `<p>`). The type now goes to Claude as
    `question_asks_for` when naming themes and sub-themes (`labeling.py`, `QUESTION_KIND_SYSTEM`) and
    writing findings (`findings.py`, `HEADLINE_KIND_SYSTEM`); "anything else" sends nothing. Each build
    records the type it used (report content `question_kind`, `profile["themes_question_kinds"]`). Changing
    it reloads the report, which reads out of date ("You changed what the question asks for...") until
    Rebuild report; if the themes were named for another type, the page says to rebuild themes. Builds
    from before this count as the guessed type. No paid call runs on its own. Tests: 4 in
    `tests/test_api_context.py`, `frontend/src/question-context-menu.test.tsx`.

- [x] **BUG-055 — "What should we fix first?" has a Themes / Sub-themes switch that cannot be clicked**
  - Found: 2026-10-25, the user (screenshot of a dominant-theme finding): "this is supposed to have
    clickable sub-themes, why can't I click it".
  - Cause: `f_rank`/`f_rank_m` drew the switch with `seg()`, a static picture of a segmented control copied
    from the design. Nothing behind it; there was no sub-theme list to switch to.
  - **Fixed:** `a76b97d` made the switch real (hidden radios plus `:has()` rules). Then, at the user's
    request ("put these underneath the main theme as expanded main theme details"), the switch was
    replaced (`e9446e9`) by per-theme `<details>` rows. The user then asked for the switch back in its old
    place, revealing the sub-topics under their themes (this commit): the switch is restored at the top
    right; "Sub-themes" shows every theme's sub-themes directly under it, in the same three columns and on
    the same bar scale; "Themes" hides them again. Labels wrap hidden radios and `:has()` rules on the
    chart root do the switching (fragments can't run scripts). Sub-themes store no tone, so their bars are
    neutral and the sentiment column shows a dash. No switch when no theme has sub-themes (or a filter is
    active). Rows grow when a name wraps (`min-height`); the name column is a little wider. Checked live on
    dataset 12. Tests: `test_rank_sub_themes_switch_reveals_them_under_each_theme`,
    `test_rank_without_sub_themes_has_no_switch`; `rank`/`rank-mobile` goldens regenerated.

- [x] **BUG-054 — Tone sunburst prints "34.262107828205906%" for All other answers**
  - Found: 2026-10-25, the user (screenshot of a finding's "Which themes sound negative or positive?"
    chart): "there is no point showing all the decimals". The long labels also overlap in the table.
  - Cause: `app/report_focus.py` builds "All other answers" as a count-weighted average of the other
    themes' tones and never rounded it; stored theme tones are already one decimal.
  - **Fixed:** (this commit). Both merged rows (`reveal_folded_theme`, the score focus) round tones to one
    decimal, matching every other percentage in the report (e.g. 34.3%). Test:
    `test_revealing_a_folded_theme_preserves_counts_and_weighted_tone`.

- [x] **BUG-053 — After Look inside, the report keeps its old findings and doesn't say so**
  - Found: 2026-10-25, the user: "when look inside click it shows the inside the new found theme, but it
    did not update the rest of the report with new finding".
  - Cause: findings are written once, at report build. Look inside's last step was named "Updating the
    report" but only changed Theme rows. The stale banner only fired for findings about deleted themes;
    Look inside grows known themes and adds new ones without deleting any, so nothing flagged it.
  - **Fixed:** (this commit). Look inside now rebuilds the report from the changed themes as its last step
    (`app.api_report.refresh_report`, one Claude call, same as Rebuild report); if that fails, the run still
    finishes with `report_updated: false` and `report_error`. Every report stores a `themes_signature`
    (theme ids, sizes, labels) and reads as stale when the live themes differ. Tests:
    `test_look_inside_other_refreshes_the_report_it_changed`,
    `test_report_is_stale_when_its_themes_changed_even_if_none_was_deleted`,
    `test_look_inside_other_still_succeeds_when_the_report_refresh_fails`.

- [x] **BUG-051 — A barcode column ("ean") is used as the region/group column on dataset 1**
  - Found: 2026-10-25, Claude, local check of the BUG-050 tests. Dataset 1's heatmap groups were EAN values
    such as "848719000000.0", so its findings read "in 848719000000.0".
  - Cause: `looks_like_identifier` only knew id/uuid/sku names and was only applied to `numeric` columns;
    `ean`, `upc` and `manufacturerNumber` were confirmed as `segment`.
  - **Fixed:** (this commit). Identifier names now include ean/upc/gtin/isbn/asin/barcode/"...Number", and
    the check also drops `segment` columns. Any segment whose values are mostly 8+ digit codes is skipped
    too, whatever its name (`looks_like_code_values`). Dataset 1 now groups by `manufacturer`. Tests:
    `test_identifier_columns_are_never_used_as_numbers`, `test_looks_like_code_values_spots_barcodes_not_groups`,
    `test_build_structured_context_skips_a_barcode_segment_for_the_next_real_one_bug_051`.

- [x] **BUG-050 — Region/group findings have no significance test, so chance gaps can become findings**
  - Found: 2026-10-25, Claude, review of the BUG-041/042 fix against survey-crosstab practice.
  - Cause: `segment_skew_candidates` gated on a share ratio (1.5x) and a group-size floor only. It never
    checked how many answers sat in the cell, never tested the gap against chance, and never corrected for
    testing every theme x group cell (up to 140 per heatmap). `SegmentRow` kept only rounded shares.
  - **Fixed:** (this commit). `SegmentRow.counts` carries real cell counts; `segment_cell_tests` tests each
    cell against the rest of its column (two-proportion z, Fisher's exact when an expected count < 5),
    gates on a per-theme chi-square, applies Benjamini-Hochberg at 5% across the heatmap, and requires
    ratio >= 1.5x, gap >= 2 points and >= 10 answers in or expected in the cell. The hover highlight uses
    the same test (none when nothing passes) and says "never mentions" for a zero share. Local check on
    real data: dataset 12 0 findings (was 3), datasets 1, 2, 11 keep their real skews. Tests:
    `test_segment_skew_*`, `test_segment_cells_use_fisher_when_expected_counts_are_small`,
    `test_segment_skew_chance_only_heatmap_gives_no_findings_after_correction`,
    `test_segment_skew_dataset_12_shape_gives_no_findings`.

- [x] **BUG-049 — A heatmap opened scrolled sideways, with its theme-name column cut off**
  - Found: 2026-10-25, Claude, dataset 12 at 1568px: the first heatmap's scroll box was at its end
    (32 of 32px), hiding the left labels.
  - Cause: not found yet (no code scrolls it). Needs a repro.
  - **Fixed:** `f35e9d5`. Defensive: charts open at scrollLeft 0 when content changes or resizes, and `overflow-anchor: none` on chart scroll boxes. Not reproduced; after the fix every chart box on dataset 12 opened at 0. Test: `ThemeChart.test.tsx` (3 jsdom tests).
- [x] **BUG-048 — Dataset 12 has 120 themes, many of them junk ("No comment provided", "Survey not
  applicable or irrelevant", "Non-substantive or referential response")**
  - Found: 2026-10-25, Claude. Theme build gave 46 clusters; splits and repeated Look inside runs added the
    rest. Look inside creates new themes from non-answers.
  - Fix: needs a user decision; ties in with BUG-032.
  - **Fixed:** `0a8a36a`. Look inside asks the labeller to flag non-answer groups (`non_answer`); flagged groups never become themes and their answers stay in Other, never sent to Jev. Result gains `non_answer_count`. Tests in `test_text_pipeline_labeling.py`, `test_other_classify.py`, `test_api_themes.py`. Dataset 12's existing junk themes are still there (needs a merge or a theme rebuild).
- [x] **BUG-047 — While the report loads (about 6 s on dataset 12), the page shows the theme-editing view
  with "Build report"**
  - Found: 2026-10-25, user (second screenshot) and Claude. `GET /report` takes 5.7 s; until it returns the
    page shows the treemap, theme card, a 121-checkbox merge list and "Ready to build the report".
  - Fix: proposed - show a loading line for the report instead of the editing view; make the merge list
    a search box rather than 121 checkboxes.
  - **Fixed:** `aac60fc`. A "Loading the report..." line until the report fetch finishes; the editing view and "Build report" only after a 404 or Manage themes. Merge list gets a filter box (9+ themes). Test: `themes-loading.test.tsx`.
- [x] **BUG-046 — "Done. Everything is updated above." while the report is stale**
  - Found: 2026-10-25, dataset 12: Look inside finished after the report was built; the findings are still
    the old ones (stale banner at the top).
  - Fix: proposed - when the report is stale say "Done. Rebuild the report to update the findings."
  - **Fixed:** `7173d44`. Stale report: "Done. Rebuild the report to update the findings." Test: `inside-other.test.tsx`.
- [x] **BUG-045 — Known themes in Inside Other show "+0%" for real gains**
  - Found: 2026-10-25, dataset 12: 18 answers out of 39,718 rounds to 0.0%, printed as "+0%".
  - Fix: proposed - print the answer count when the share rounds to 0 (e.g. "+18").
  - **Fixed:** `7173d44` + `ddc3852`. A share under 0.1% prints the answer count ("+18"), and a list uses one unit for all rows (no mixed "0.1%" and "19"). Tests: `inside-other.test.tsx`, `inside-other-model.test.ts`.
- [x] **BUG-044 — The overview draws the icicle on desktop for dataset 12, with rotated, broken labels**
  - Found: 2026-10-25, user (screenshot). `_prefers_icicle` picks the icicle when the treemap can't fit;
    labels then rotate and break mid-word ("Temperat ure", "Privac y"), sub-themes hang below, there is a
    large empty area under the biggest theme, and no "Look inside ↓" hint.
  - Fix: proposed - in the report, keep the treemap on desktop and show tiny themes as labelled slivers;
    no mid-word breaks.
  - **Fixed:** `688ba21`. Report overview always draws the treemap; labels wrap at spaces only and fall back to the share, then nothing, by box width (container query); full names in `title` and screen-reader text. Gallery unchanged. Tests in `test_charts_data.py`. Checked live on dataset 12.
- [x] **BUG-043 — With 120 themes, the treemap shows 7 and folds 113 into "Other 50.7%"; Inside Other
  then says Other is 0%**
  - Found: 2026-10-25, user (screenshot) and Claude, dataset 12. The treemap's Other = 12 unthemed answers
    + 113 real themes that have no colour (`other_breakdown.hidden_real_share` 50.7). Inside Other only
    counts the 12 unthemed answers ("0% of all answers. It was 1.7% before"), so the two sections
    contradict each other.
  - Fix: needs a user decision - e.g. call the treemap block "113 more themes" instead of "Other", and/or
    show the folded themes in Inside Other's "See all 120 themes". Also why 120 themes: see BUG-048.
  - **Fixed:** `688ba21`. The folded block reads "113 more themes 50.7%" (or "Other and N more themes" when unthemed answers dominate); "Other" only when nothing is folded. Look inside hint only when there are unthemed answers. Tests in `test_charts_data.py`, `test_api_report.py`, `test_report_medium.py`.
- [x] **BUG-042 — The same theme gets several near-identical findings (one per region)**
  - Found: 2026-10-25, Claude, dataset 12: three heatmap findings, same theme and chart, only the
    highlighted cell differs.
  - Fix: proposed - at most one segment finding per theme (keep the strongest). Recheck after BUG-041,
    which removes these three anyway.
  - **Fixed:** `b85d9f7`. At most one segment-skew finding per theme (largest gap). Test in `test_findings_structured.py`.
- [x] **BUG-041 — Region findings compare against the wrong baseline, so they are false (dataset 12)**
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
  - **Fixed:** `b85d9f7`. `overall` is the theme's share of the answers in the heatmap's own groups; a skew must also survive the 0.1-point rounding. Score and trend paths checked: already like-for-like. Test: `test_build_segment_data_overall_ignores_rows_with_no_group_bug_041`. Confirm on dataset 12 after Rebuild report (BUG-031).
- [x] **BUG-039 — `localhost:8000` serves an old frontend build**
  - Found: 2026-10-24, Claude. `:8000` serves `frontend/dist`, which isn't rebuilt automatically.
  - Fix: run `npm run build` before using `:8000`, or check UI on the Vite dev server `:5173`.
  - **Fixed:** (no code change). Rebuilt `frontend/dist` with `npm run build` on 2026-10-25. It goes stale again after frontend changes: rebuild, or use `:5173`.
- [x] **BUG-038 — The server still builds three overview charts the page no longer shows**
  - Found: 2026-10-25, Claude, Phase 3. `report_medium.theme_views` builds `sentsun`, `rank` and
    `sunburst`; only `icicle` and `diverge` are used. Wasted work and payload, nothing visible.
  - Fix: trim `theme_views` (check that no finding uses them first).
  - **Fixed:** `688ba21`. `theme_views` builds only `icicle` and `diverge`. Tests updated.
- [x] **BUG-037 — The phone overview is headed "Themes and sub-themes", desktop "What are the themes?"**
  - Found: 2026-10-25, Claude, phone width. The phone layout reuses the icicle fragment and its header.
  - Fix: minor; align in Phase 4.
  - **Fixed:** `688ba21`. Phone overview (icicle) is headed "What are the themes?". Test in `test_report_medium.py`.
- [x] **BUG-036 — On dataset 12 the treemap's Other block has no "Look inside ↓" hint**
  - Found: 2026-10-24, Claude. The capped Other box is about 54px wide, below the 80×64 the hint needs.
  - Fix: Phase 4 to decide (the Inside Other section sits right under it, so the link is still visible).
  - **Fixed:** `688ba21`. A narrow Other box gets a compact "↓" hint with an accessible label. Test in `test_charts_data.py`. Seen live on dataset 12.
- [x] **BUG-035 — Before a run, Inside Other's ribbon area is mostly empty**
  - Found: 2026-10-25, Claude, dataset 11 at 1280px. One Still-in-Other ribbon on the right, blank space on
    the left.
  - Fix: compare with `Other-Flow.dc.html` in Phase 4 (`REPORT-UI-4`).
  - **Fixed:** `7173d44`. Idle (and failed) flow is a short band from the centred Other strip down to Still in Other (152 instead of 346 units tall). Test in `inside-other.test.tsx`.
- [x] **BUG-033 — Curly apostrophes split words in the sentiment tokenizer ("don’t" → "don", "t")**
  - Found: 2026-10-24, Claude, during the phrase-apostrophe fix (BUG-003 only fixed phrases).
  - Fix: **needs a user decision** (it changes sentiment scores on existing datasets).
  - **Fixed:** `79faf04`. Typographic apostrophes are normalised before sentiment tokenising; "don’t" scores like "don't". Test in `test_text_pipeline_sentiment.py`. Lexicon sentiment shifts slightly on datasets scored after this.
- [x] **BUG-032 — Look inside Other put 5,833 of 6,041 answers into one new theme on dataset 12**
  - Found: 2026-10-24, Claude, dataset 12 ("Office Layout and Facility Condition").
  - Cause (likely, not confirmed): Jev classifies against a broad merged label with no size or confidence
    cap. `confidence_by_row` is computed but unused (`other_classify.py`); union-find merging can chain
    labels (`merging.py`).
  - Fix: investigate in `REPORT-UI-5`. **Needs the user's approval** before any change.
  - **Fixed:** `0a8a36a`. Cause (from code; the original job's data was gone): Jev's per-answer picks, after union-find merging chained candidate labels into one broad option. Now: Look inside merges without chaining (`star_groups`), and a pick below `MIN_MATCH_CONFIDENCE = 0.5` stays in Other (`low_confidence_count` in the result). Threshold not yet checked against real Jev confidences.
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

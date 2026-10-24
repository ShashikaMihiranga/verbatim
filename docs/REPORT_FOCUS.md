# Finding-specific report charts

## Bug and cause

Different findings could render identical chart fragments. Candidate selection legitimately keeps
several findings of one kind (for different themes or demographic groups), but the read route passed
the same full ReportData to every heatmap, score comparison and trend. Highlighting the shared
"Other" bucket also made findings about distinct themes beyond the overview's top seven look alike.
This was a rendering-context bug, not duplicated Report rows or an extra model call.

## Behavior

- Overview stays broad. Candidate scores, thresholds, confidence, cap of five and stored headlines
  are unchanged. Reusing a suitable chart type is valid; its evidence must match its own finding.
- Segment findings show the finding's theme row, overall reference, and named group highlight.
- Score findings show that theme versus an explicit "All other answers" remainder. Original band
  denominators, counts and average sentiments remain unchanged; a selected theme is never normalized
  to 100%.
- Trend findings show the named theme's series; stacked time charts retain a 100% complement.
  The first/last alternate also focuses on the named theme.
- Tone findings about an overview-folded theme recover that real theme and compare its weighted tone
  with all remaining answers, rather than outlining the same merged Other bucket. Overview is unchanged.
- Full-context Sankey and group-mix alternates remain available, explicitly labeled "All themes".
  They can legitimately repeat across findings because they are context, not distinct evidence claims.
- A filtered-away group/theme or switched structured source column shows an unavailable-comparison
  message instead of substituting unrelated data. Saved headlines retain their existing rebuild semantics.
- Current theme IDs resolve live names after renaming; historic headline text is not silently rewritten.

## Implementation and handoff

`app/report_focus.py` creates immutable, lightweight per-finding views. `app/api_report.py` feeds those
views to existing renderers. `app/report_medium.py` distinguishes focused alternatives from broader
context. No schema, migration, network service or new composer/ranking engine is involved.

Existing reports gain this behavior on GET/refresh after the updated backend is running; no paid
theme/report rebuild is needed. The report export endpoint reuses the same corrected read path.

Regression coverage includes a real asynchronous report build whose top five contain multiple score
and demographic findings, same-theme/different-group highlighting, two overview-folded themes,
filter fallback, weighted totals, unchanged score denominators and overview non-mutation.

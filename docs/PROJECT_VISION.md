# Verbatim: project vision (the North Star)

Read this first. It is the reason the project exists. Every feature is judged against it.
Last updated: 2026-09-20. Decisions that change it go in `docs/DECISIONS.md`.

## What Verbatim is
An AI app that lets anyone, with no data background, do the exploratory data analysis (EDA) that normally needs a data scientist. The user uploads a spreadsheet. The app works out what it is and tells the story in it.

## The main goal, in five parts
1. **Understand first.** On upload, the app works out the context of the dataset: what question was asked, what each column means, its unit and its role (text, score, date, segment, number, ID).
2. **Clean adaptively.** The app picks cleaning steps to suit this dataset (blanks, n/a, duplicates, spelling merges, banding) and shows the user what it did. Nothing is done silently.
3. **Pick the story.** Either the app decides which findings matter, or the user says what they want. The result is a short dynamic report. Each block has one insight, one sentence and one visual.
4. **Make EDA open to everyone.** No statistics knowledge needed. Plain wording, "Solid" or "Tentative" badges, no jargon or p-values on the report face.
5. **Solve open-ended text.** This is the hardest and most important part. Find the best way to represent free-text answers: themes, sub-themes, sentiment, and the chart that makes the most sense for the type of question. See SPEC.md sections 4 and 9.

## Trust rules (apply everywhere)
- Every theme and every sentence links back to real answers.
- Claude sees samples and aggregated numbers only, never the whole dataset. Cheap steps (embeddings, clustering, sentiment lexicon) do the bulk work.
- Groups below a minimum size are hidden. Individual rows of demographic columns are never shown.
- The user confirms column meanings before they are used.

## Decisions taken (2026-09-20)
| Area | Choice |
|---|---|
| Sign-in page "dynamic" | The server rotates between designs A to D per visit, so they can be compared |
| Auth | Clerk, using its hooks to build our own designs |
| Database | Railway Postgres |
| Front end | React app plus FastAPI JSON API |
| Chart code | `app/charts.py` keeps serving SVG fragments at first. Port to JS only where interactivity needs it |

## Where things live
- `SPEC.md`: product plan, data flow, chart-selection rules, structured columns.
- `CLAUDE.md`: design rules, product rules, commands, task order.
- `design/screens/`: mockups. They only render inside the Claude Design canvas.
- `docs/DECISIONS.md`: append-only log of decisions.
- Build plan: milestones M1 (skeleton live), M2 (understands a sheet), M3 (reads the text), M4 (tells the story).

## Glossary
- **Theme**: a group of similar answers with a label, found by clustering.
- **Finding**: a difference or pattern worth telling, scored by size and group size.
- **Block**: one report unit, one sentence plus one visual.
- **Solid / Tentative**: badge for how strong a finding is.
- **Verbatim**: a real answer text shown as evidence.

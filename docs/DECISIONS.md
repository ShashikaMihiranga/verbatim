# Decision log (append only)

## 2026-09-20
- Main goal recorded in `docs/PROJECT_VISION.md`.
- Sign-in page: server rotates between designs A to D per visit, logged for comparison.
- Auth: Clerk custom flow. Database: Railway Postgres. Front end: React plus FastAPI JSON API.
- `app/charts.py` stays as the SVG source at first and is ported to JS only where needed.

## 2026-09-20 (foundation stream)
- `DATABASE_URL` values starting `postgres://` or `postgresql://` are rewritten to `postgresql+psycopg://` (psycopg 3 driver).
- Railway runs `alembic upgrade head` as `preDeployCommand`; `nixpacks.toml` adds Node so one image builds the frontend and serves it.
- Procfile kept as a fallback; `railway.json` also carries the start command.
- Extra tables columns beyond the brief: `datasets.filename/row_count`, `columns.kind/stats`, `themes.answer_refs` (row indexes, for the "link back to real answers" rule).
- No frontend test runner added (skipped to keep the scaffold small).

## 2026-09-20 (charts-to-data stream)
- Charts take a `ReportData` dataclass (`app/chart_data.py`); the EV sample lives in `app/fixtures/ev_sample.py` and is the default for `render()` so `/frame/<id>` is unchanged.
- Regression guard: full HTML of the 20 frames is committed in `tests/golden/` (about 330 KB) and compared byte for byte.
- Design constants (theme on-colours `TH_ON`, dim opacity, axis scales) stay in `charts.py`; only sample data moved. Demo view states (selected, hover) are data fields `selected_theme` / `hover_theme` so custom data never references EV theme names.
- `GET /api/charts/{id}` returns the full standalone document in `html` (same as `/frame/<id>`), plus width and height.
- `f_freq`, `f_phrases`, `f_quotes` are not in `FRAMES` (not among the 20); they take data too but are unregistered.
## 2026-09-20 (upload + profiling stream)
- Dataframe library: pandas (with openpyxl for .xlsx, xlrd for .xls). CSVs are read with the stdlib `csv` module into rows first, so ragged rows, title rows above the header and odd delimiters cannot break the parser. Pinned in `requirements.txt`, plus `python-multipart` for uploads.
- Column kinds are `open_text, short_text, score, date, segment, numeric, yes_no, id_or_junk` (SPEC sections 3 and 9.1). `columns.kind` now stores these values (the old comment listing text/number/category/id/ignore in `app/models.py` is superseded). No migration needed: the user's confirmed choices live in `datasets.profile["confirmed"]` and in `columns.kind` / `columns.stats` (`off`, `sensitive`, `unit`, `guessed_kind`).
- Nothing is silent: the loader writes what it changed (skipped rows, blank rows, "n/a" cells turned blank, encoding, delimiter) to `profile["notes"]` and the Check columns screen lists it.
- Files are stored as `UPLOAD_DIR/<sha256><ext>` (default `~/.verbatim/uploads`, outside the repo). File names from users are display-only and sanitized. Same hash for the same user reuses the existing dataset record. `MAX_UPLOAD_MB` defaults to 50. Zip-bomb check for .xlsx (uncompressed size and ratio), row cap 500,000, column cap 300.
- Sensitive flag (age, sex/gender, income, and similar) is set by column name and by values. Sample values for sensitive columns are limited to 3 common values, and are never sent to Claude.
- `app/profiling/claude_hook.py` calls Anthropic only when `ANTHROPIC_API_KEY` is set (headers plus up to 30 distinct samples per column, one call, model `claude-haiku-4-5`, override with `VERBATIM_CLAUDE_MODEL`). The `anthropic` package is imported lazily and is not in requirements.
- `current_user()` in `app/api_upload.py` is a dev-user stub to be replaced by the Clerk dependency (stream 3).
## 2026-09-20 (adaptive cleaning stream)
- Cleaning lives in `app/cleaning/` (planner `plan_cleaning`, executor `apply_plan`, `redact.py`, `payload.py`) with routes in `app/api_cleaning.py`. The plan is built by running steps in order on a working copy, so thresholds and merge tables reflect the data at that point and steps that would change nothing are omitted (only `mask_pii`, `exclude_columns`, `check_score_range` and `parse_dates` are always listed, so the user sees the scale and date order we assumed).
- Storage: plan and report are JSON in `datasets.profile["cleaning"]`; no new column or migration. The cleaned copy is `UPLOAD_DIR/<sha256 of its bytes>.clean.csv`; the original is never modified. User edits are stored as `plan.overrides` and the plan is rebuilt from the data on every PATCH, so the preview always matches what apply will do.
- Non-answers, keyboard mash and out-of-range scores blank the cell, not the row: the row's other columns still count. Rows are removed only when completely empty, or as exact repeats of a long open-ended answer (default on, length limit from the data, min 3 and max 10 words; short answers like "Price" are never collapsed). Every removed row is listed by number, step and reason; `accounted_for` checks rows in minus rows out.
- Identical whole rows are reported and flagged, not removed (no ID column means we cannot tell a double submission from two people).
- Fuzzy matching: `rapidfuzz==3.14.6` (ratio cut-off 86/90/93 depending on how many distinct answers there are, plus a one-letter-typo rule when there are 300 or fewer; guards against digit differences and one- or two-letter tokens such as Model X vs Model Y). The merge table is the source of truth: apply uses exactly the table the user reviewed.
- Dates: numeric d/m/y is classified per value. A first number above 12 proves day first, a second above 12 proves month first; if the file has neither, ambiguous dates are read month first, flagged, and a warning says so. Impossible dates (31/02) are blanked and flagged, not repaired.
- Scores: scale chosen from 1-5, 0-5, 1-7, 0-10, 1-10 as the smallest scale covering at least 95% of values (2% tolerance); it is editable. Numbers: "1,234" is read as one thousand two hundred thirty-four; "1.234,56" and "12,5" are read European style.
- PII masking (emails, phones, links, Luhn-valid cards, SSN-style and 9 to 15 digit runs) is regex based with bounded quantifiers, on by default, and `model_safe_samples` masks again and refuses sensitive columns. Names and street addresses are NOT detected; that needs a model or NER and is out of scope for now.
- Suppression: sensitive columns get `groups` metadata with `hidden: true` and `count: null` under `MIN_GROUP_SIZE` (default 30, env). No examples are produced for sensitive columns, and merge tables hide counts under the minimum.
- Public-app hardening: owner check via `_own_dataset`, row (200k) and column (300) caps, a 30 second deadline checked between steps and every 2,000 distinct values, at most 2 concurrent cleaning jobs (429 after that), request bodies validated with `extra=forbid` and size limits, only whitelisted params editable, cleaned file named from its hash, nothing evaluated. Examples are returned as JSON strings with control and bidi characters removed; the UI renders them as text.
- Known gap: the cleaned CSV can contain cells starting with `=`, `+`, `-` or `@`. There is no download route yet; when one is added, prefix such cells or export with a formula guard.

## 2026-09-20 (auth stream)
- Auth is Clerk with a custom flow (`@clerk/clerk-react` 5.61.10 hooks: `useSignIn`, `useSignUp`, `useAuth`, `useClerk`), styled to our designs. Google and Microsoft use `authenticateWithRedirect` with `/sso-callback`. Only the publishable key (`VITE_CLERK_PUBLISHABLE_KEY`, build time) is in the frontend; the Clerk secret key is not used anywhere.
- Backend (`app/auth.py`) verifies `Authorization: Bearer <jwt>` with PyJWT 2.14.0: RS256 only (checked from the header before any key lookup, so `none`, HS* and other algorithms are refused), signature against the JWKS at `CLERK_JWKS_URL`, `iss` equal to `CLERK_ISSUER`, `exp` required, `nbf` checked, 10 s leeway, `azp` must be in `CLERK_AUTHORIZED_PARTIES` when that is set, Clerk `sts` must be active if present. The JWKS is cached for an hour and an unknown `kid` can refetch at most once a minute (junk tokens cannot make us hammer Clerk). `CLERK_JWKS_URL` must be https outside dev.
- Every failure is the same 401 `{"detail":"Sign-in is required."}`; the real reason is logged at info level on the server. Missing Clerk settings in production also give 401 (fail closed).
- `token.sub` maps to `users.clerk_id`; the row is created on first sight (a race on the unique key is retried). `current_user` in `app/api_upload.py` keeps its name and now calls `app.auth.authenticate`. The dev user requires `ENV=dev` and `ALLOW_DEV_USER=true`; `tests/conftest.py` sets both by monkeypatch.
- `GET /api/me` returns `{id, email?}`; email only if the token carries an `email` claim (Clerk session tokens omit it unless a custom claim is added in the Clerk dashboard).
- Dynamic sign-in: `GET /api/signin-variant` picks a, b, c or d at random (`SIGNIN_VARIANT_WEIGHTS`, default equal) and writes `signin_variant_log(variant, created_at)`, nothing else. The client keeps the choice in `sessionStorage` for the tab session so a refresh does not re-roll or re-count. The optional outcome endpoint was NOT built: the table has no outcome column and adding one needs a migration; revisit when the designs are compared.
- The four designs share one form component; only the layout and decorative side panel (`frontend/src/auth/SidePanel.tsx`) differ.
- CSP (`app/security.py`): when `CLERK_FRONTEND_API` is a plain host name, `https://<host>` is added to script-src, connect-src, frame-src and img-src; `https://img.clerk.com` to img-src; `https://challenges.cloudflare.com` to script-src, frame-src and connect-src; and `worker-src 'self' blob:` (Clerk's script uses a blob worker). No `unsafe-inline` or `unsafe-eval` for scripts. Invalid values are ignored so the variable cannot inject directives.
- Error wording never reveals whether an email has an account: unknown email and wrong password both say "Email or password is not right."; the reset flow shows the code step whatever the answer; sign-up with an existing email gets a neutral message.
- Frontend `authFetch` (`frontend/src/authFetch.ts`) adds the Clerk session token to every `/api` call (uploads use XHR and set the header too) and sends the user to `/sign-in` on a 401. `/projects`, `/upload`, `/check-columns`, `/cleaning`, `/report` redirect to `/sign-in` when signed out.
- Vitest added for the password rules, the variant parser and the side panels.

## 2026-09-20 (cleaning and web-layer hardening)
- Names and addresses (best effort, NOT a guarantee): `redact.py` masks a name only after a cue ("my name is", "I am", "I'm", "this is", "call me", Mr/Mrs/Ms/Miss/Mx/Dr/Prof) when capitalised words follow, and skips common capitalised words ("I am Very happy", "This is Monday", car brands). Addresses are number + capitalised street name + street word (Street, Rd, Avenue, Lane, Drive, Court, Place, Blvd, Highway, ...), plus postcodes next to an AU state, a US state (ZIP or ZIP+4), or UK format. A name with no cue ("Sarah told me"), lowercase addresses, bare 4-digit AU postcodes and non-English cues are missed. Masks appear in the report with counts and partial examples (`name`, `address` in `pii` and in the step details). When an open-text column still has runs of capitalised words that are not at a sentence start (5 or more answers and 5% of answers), the report adds a "may still contain names" warning for that column. `model_safe_samples` applies all masks again.
- Bare 9 to 15 digit runs are phone numbers in open_text and short_text columns (`bare_digits="phone"`), and IDs only where the column kind is id_or_junk or numeric (`bare_digits_for_kind`). Luhn-valid cards and SSN-style numbers stay IDs everywhere. Over-masking a long order number as a phone is accepted: it is the safe direction.
- Score scale (supersedes the "Scores" line above): the scale comes from, in order, the user's edit (`scale_source: user`), a hint in the column header ("0-10", "1 to 5", "out of 10", "/10"; `header`), then the observed values (`observed`, lowest confidence, smallest of 1-5, 0-5, 1-7, 0-10, 1-10 covering 95%+). Out-of-range answers are blanked only for `user` and `header` scales. For an `observed` scale they are kept, flagged ("outside the guessed 1 to 7 scale (was 9), confirm the scale"), listed in a report warning, and `details.needs_confirmation` is true. Sending the scale through the existing editable `scale` param (even the same numbers) is the confirmation. Plans stored before this change have no `scale_source` and are treated as `observed`, so they never blank. Reason: a 1 to 10 question where few people chose above 7 was read as 1 to 7 and the high answers were lost.
- Duplicates (supersedes the exact-repeat removal above): a repeated long open-text answer is now FLAGGED (`same answer as row N`) and the rows are kept, because two different people can type the same sentence; the report gives the count (`repeats_flagged`) and examples, and the first row keeps `_verbatim_dup_count`. A row is removed only if it is identical to an earlier row in every column (`identical_rows_removed`), listed by row number and reason, so `rows_in - rows_out == removed_rows_total` still holds. Rows identical in every column with no long text remain flag-only (`report_duplicate_rows`).
- Non-English (best effort): non-answer matching folds case and accents (`No sé`, `não sei`, `Weiß nicht` match) and has a small list for Spanish, French, German and Portuguese plus a few Russian, Chinese, Japanese and Korean whole-answer terms. A single ASCII letter is still a non-answer; a single CJK character is not. Keyboard-mash rules (repeated character, key runs, vowel floor) are skipped for any answer that contains a non-ASCII letter (non-Latin script or accented letters), because they only work for English typing; the report records `skipped_non_english`. Laughs such as haha, jajaja and kkkk are kept. Users can add terms through the plan: `blank_non_answers.extra_terms` (up to 100 terms, 60 characters each) and `blank_keyboard_mash.safe_words`; both are validated in `api_cleaning`. `blank_non_answers` is now always listed for text columns so terms can be added even when it found nothing. Not solved: mash and non-answer lists for other languages, and Latin-script languages without accents.
- Formula injection (resolves the 'Known gap' above for future downloads): `app/cleaning/export.py` has `csv_safe_cell`, `csv_safe_frame` and `csv_safe_bytes`. Any string cell or column name that starts with =, +, -, @, tab or carriage return (also after leading whitespace, and the full-width look-alikes) gets a single quote prefix; lone symbols and numbers are untouched; the input frame is not modified. EVERY future download route (CSV or XLSX) MUST go through it. The internal analysis file `<hash>.clean.csv` is intentionally unchanged because the pipeline reads real values back from it; it must never be served as a download as is. Echoed text in the report (examples, flags, warnings, column names via `safe_text`) is guarded the same way, so a copied example is inert. Merge-table `from`/`to` values are the exception: they must equal the data to round-trip, so the UI must render them as text and any export of them must use `csv_safe_cell`. The API returns JSON only (no HTML), with `nosniff`.
- Web-layer limits (`app/ratelimit.py`, pure ASGI, one `add_middleware` line in `main.py`): in-memory sliding-window counter per client, three numbers per (bucket, client), LRU-capped at 50,000 keys with stale entries swept. Buckets: 120/min `/api` overall, 10/min `POST /api/upload`, 30/min `/api/signin-variant` and `/api/auth*` (upload and auth also count toward the `/api` total), 300/min everything else, `/health` exempt; all env-configurable. 429 with `Retry-After` and a generic body. Client IP is the socket address unless `TRUST_PROXY=true`, then the first `X-Forwarded-For` entry (`PROXY_XFF_POSITION=last` available, because a first entry is forgeable if the proxy appends instead of replaces); invalid values fall back to the socket address; IPv6 is grouped by /64; paths are normalised (case, repeated and trailing slashes) before classification. The header is never read when `TRUST_PROXY` is off. Tests set `RATE_LIMIT_ENABLED=false` globally in `tests/conftest.py` and build their own app for limit tests. Per instance only: with N instances or workers the effective limit is N times higher; move the counters to Redis when scaling out.
- Request size guard (same middleware): `POST /api/upload` with `Content-Length` above `MAX_UPLOAD_MB` + 1 MB is 413 before the body is read; other `/api` requests above `MAX_API_BODY_KB` (default 1024) are 413; a malformed `Content-Length` is 400. Chunked uploads without a length still rely on the streaming check in the upload route.

## 2026-09-21
- Railway build switched from Nixpacks to a Dockerfile: Nixpacks gave Node 22.10 (Vite 8 needs 22.12+) and npm skipped the rolldown native binding, so `npm run build` failed. Procfile and nixpacks.toml removed.
- Railway start command is shell-wrapped in railway.json (`sh -c`), because a dashboard start command is run without a shell on Docker builds, so `$PORT` stayed literal and uvicorn exited with a usage error. railway.json overrides the dashboard value.
- Railway kept running a start command with a literal `$PORT` even after railway.json used `sh -c` (likely a start command saved in the dashboard). The image now has `entrypoint.sh`, which runs any supplied command through a shell so `$PORT` always expands. `startCommand` removed from railway.json again.
- Logs after the entrypoint change still showed `--port '$PORT'`, so Railway replaces the image ENTRYPOINT with the saved start command. The image now installs `docker/uvicorn-shim.sh` over the `uvicorn` command; it swaps a literal `$PORT` argument for the real port. Also clear the Custom Start Command in the Railway dashboard.

## 2026-09-25 (text pipeline stream: embed + cluster)
- Embedding provider: Voyage AI (`voyageai==0.5.0`, installs and imports cleanly; lazy-imported inside `VoyageEmbeddingClient` so nothing outside `app/text_pipeline/embeddings.py` needs it installed, and `import app.text_pipeline` never touches the network). Reads `VOYAGE_API_KEY` from the environment and raises `EmbeddingNotConfigured` before any network call if it is missing; batches requests at 128 texts (well under Voyage's per-request text and token caps) and retries a batch once on a transient error. Default model `voyage-3.5`, override with `VOYAGE_MODEL`.
- Clustering: scikit-learn's `HDBSCAN` (`scikit-learn==1.9.1`, installs and imports cleanly: `from sklearn.cluster import HDBSCAN` works with no extra native deps). No LLM call in clustering; that stays a separate step (labelling) for the next stream. `store_centers="centroid"` is used so each cluster gets a real centroid, and each member's `distance` is the plain Euclidean distance from its vector to that centroid (computed here, not read from HDBSCAN's `probabilities_`, which is a membership-strength score, not a distance).
- Adaptive `min_cluster_size` (PROJECT_VISION.md's "clean adaptively" applies here too): `max(5, min(50, round(n_answers / 50)))` - roughly one theme-worth of answers per 50 answers, floored at 5 (a theme needs a handful of answers to mean anything) and capped at 50 (past that, a bigger floor would swallow real sub-themes into noise). A cluster HDBSCAN finds that ends up smaller than this minimum (its own `min_cluster_size` only bounds the search, not every accepted cluster) is folded into noise rather than reported as a one- or two-answer theme.
- Determinism: this build's `HDBSCAN` (scikit-learn 1.9.1) exposes no `random_state` parameter - it is density-based with no random initialisation (unlike k-means), so the same vectors always produce the same labels; there is nothing to seed.
- Changed from the brief: `cluster_answers`'s signature omits the `column` name (the brief's own worked example for it did not include one either); `pipeline.embed_and_cluster` sets `ClusterResult.column` itself after clustering, since that is the only place column and vectors meet. `model_safe_column` returns `None` only for a missing/NaN cell, per the brief; a present-but-empty string stays `""` (not promoted to `None`), since it is a real value, not a missing one - `pipeline.embed_and_cluster` treats both as "no answer" when deciding what to embed.
- `FakeEmbeddingClient` hashes each lowercased word of a text into a fixed-size vector and sums per answer (bag-of-words, so word order does not matter), then normalises to a unit vector. This is NOT a semantic embedding: it only clusters well when near-duplicate test answers are built from a small, disjoint, topic-specific vocabulary (see `tests/test_text_pipeline.py`'s `BATTERY_POOLS` / `PRICE_POOLS`). Exact duplicate strings land at distance 0 and can pull HDBSCAN toward a tight sub-cluster of just the repeats rather than merging with the rest of the topic - the test fixtures avoid exact repeats for that reason. A real embedding model would place genuine paraphrases (different words, same meaning) close together, and would separate on meaning rather than shared vocabulary; the fake client cannot do either, so clustering quality on real survey text will differ from - and should be noticeably better than - what these tests show.

## 2026-09-25 (text pipeline stream: theme labelling)
- `app/text_pipeline/labeling.py`'s `ClaudeClient` is a one-method Protocol - `complete(system, prompt) -> str` - deliberately narrower than the raw `anthropic` SDK shape, mirroring `embeddings.EmbeddingClient.embed`'s one-method split rather than exposing `messages.create`'s full parameter surface to callers. `AnthropicClaudeClient` is the real implementation: lazy-imports `anthropic` (still not a hard requirement - not added to `requirements.txt`, same as `claude_hook.py`), raises `ClaudeNotConfigured` before any network call if `ANTHROPIC_API_KEY` is unset, and inside `complete()` calls `client.messages.create(model=..., max_tokens=4096, system=..., messages=[{"role": "user", "content": prompt}])` - the exact same call shape `app/profiling/claude_hook.py` already uses for its optional Claude step, joining the text blocks of `msg.content`. Model defaults to `claude-haiku-4-5`, override with `VERBATIM_CLAUDE_MODEL` - the same env var `claude_hook.py` reads, so one small model serves both optional Claude steps unless someone points it elsewhere. `FakeClaudeClient` (reply string, or a callable of the prompt for reply-depends-on-input tests) records every call in `self.calls` for the batching assertion.
- Prompt: one JSON user message - `{"survey_question": ..., "clusters": [{"cluster_id": int, "sample_answers": [str, ...]}, ...]}` - built from every `Cluster` in `result.clusters` in one shot (never one call per cluster, per SPEC.md's "One batched call for all clusters"). "Representative" samples are the `samples_per_cluster` members closest to the cluster's centroid by the `distance` HDBSCAN clustering already computed (ties/`None` sort last), cheapest option that still favours typical answers over outliers, needing no extra call or model. Reply contract: `{"themes": [{"cluster_id": int, "label": str, "description": str, "merge_with": [int, ...], "note": str or null}, ...]}`, one entry per cluster id sent - plain JSON in the system prompt (not the SDK's tool-use / `output_config.format` structured-output path), matching `claude_hook.py`'s existing parse-the-text-as-JSON approach rather than introducing a second response-handling style into the codebase for one more module. `_parse_response` validates every field's type and that every sent cluster id got an entry back, ignores any entry for an id never sent, drops self-references and unknown ids from `merge_with`, and raises `LabelingError(message, raw_response)` on the first problem - nothing unvalidated reaches `ThemeLabel`. `_extract_json` first tries a bare `json.loads`, then falls back to pulling the first `{...}` span (same tolerance as `claude_hook.py`'s `_parse_json`) for a reply wrapped in prose despite the "JSON only" instruction.
- `ThemeLabel.size` is never read from the response at all - `label_clusters` sets it from `len(cluster.members)` (or `len(result.noise)` for "Other") itself, after parsing, so even a reply that includes a bogus `"size"` field (our schema has none) cannot influence it; the system prompt also explicitly tells Claude not to invent counts, percentages, or shares. The noise/"Other" group is never sent to Claude - `label_clusters` only calls `client.complete` when `result.clusters` is non-empty, and appends a locally-built `ThemeLabel(cluster_id=-1, label="Other", ...)` afterward when `result.noise` is non-empty; `-1` doubles as HDBSCAN's own noise label and is never a real `Cluster.id` (those are assigned 0-based by `clustering.cluster_answers`).
- Changed from the brief / left for later: the brief's example protocol method name `label_clusters(prompt: str) -> str` was not used verbatim - `complete(system: str, prompt: str) -> str` on `ClaudeClient` keeps the module-level `label_clusters` function name unambiguous and matches `claude_hook.py`'s system+prompt call shape. Split suggestions have no dedicated field of their own; per the brief's own `ThemeLabel` signature (`note: str | None`) a split suggestion is just free text in `note`, same as any other flag - there is no `split: bool` or similar. Label quality on real survey text (as opposed to structural correctness) is unverified: everything here is tested against `FakeClaudeClient` only, no real Claude call was made, per the no-network constraint.
## 2026-09-25 (text pipeline stream: sentiment)
- Lexicon, not a third-party package: `app/text_pipeline/sentiment.py` embeds about 220 English words in four weight bands (strong +/-1.0, moderate +/-0.6, mild +/-0.3), plus a negation list (apostrophe and no-apostrophe spellings, since survey text often drops them) and an intensifier/downtoner list. No new dependency was added - the brief allowed a normal, no-native-deps pip package, but nothing reviewed beat a small hand-built list for "typical survey vocabulary" coverage without pulling in a general-purpose (and often VADER/NLTK-corpus-sized) package. `score_text` averages the weight of only the sentiment-bearing words it recognises (not diluted by sentence length), applies negation by flipping the sign of the next sentiment word within a 3-token window, and intensifiers by scaling the next sentiment word's weight within a 2-token window; the result is clipped to [-1, 1].
- Tone thresholds: `NEG_THRESHOLD = -0.15`, `POS_THRESHOLD = 0.15`. Because polarity is an average over matched words (not tokens), a single unmodified mild word already scores +/-0.3 and a single moderate word +/-0.6 - both comfortably clear a small band. The band only needs to catch true near-zero cases: opposing words cancelling out in the same answer, or a heavily-softened word ("slightly good" = 0.3 x 0.5 = 0.15). 0.15 sits at that softened-mild floor, below any unmodified recognised word, so "recognised sentiment, however mild" and "no sentiment recognised" (0.0) do not collide except at true ambiguity. Not a single arbitrary cutoff: it is derived from the mild-word weight and the softest intensifier, and both threshold constants live at the top of the module for easy re-tuning.
- Lexicon coverage and limits (honest accounting): about 220 words, hand-picked for common English survey vocabulary (praise, complaints, frustration, satisfaction, price/value language). It WILL miss: slang and internet-speak ("mid", "fire", "sus"), sarcasm and irony ("oh great, another delay" scores positive), industry/product jargon specific to any one survey, emoji and emoticons (not handled at all), misspellings not in the list ("gr8", "terribel"), non-English text or code-switching (the whole pipeline is English-only; `redact.py`'s non-answer detection has separate limited non-English handling, this lexicon has none), and any word used ironically or in a negated construction the negation window doesn't reach (e.g. "I would not call this good service" - four tokens between "not" and "good" is outside the 3-token window and would NOT flip). Multi-word phrases ("rip off" as two words, "not worth it") are not specially handled beyond what single-token negation/intensifier windows catch. This is a best-effort scorer for triage and aggregate tone, not a ground truth - which is exactly why `spot_check` exists.
- `tone_split` uses largest-remainder rounding (`_round_percentages_to_100`) so neg/neu/pos always sum to exactly 100, never 99 or 101 from three independently-rounded floats. With zero scored answers it returns 100% neutral by convention (not 0/0/0) purely to preserve that "always sums to 100" invariant across every input shape the brief asked for, including the empty case; callers with zero answers should treat that as "no data" upstream, not read it as a real finding.
- `score_column` treats a masked value of `None` (missing/NaN), `""` (masked down to nothing), or whitespace-only as "no answer" and returns `None` for that row - never inventing a score. This is slightly stricter than `model_safe_column`'s own contract (which keeps a present-but-empty string as `""`, distinct from `None`, per the embed/cluster stream's decision above): here, an empty or whitespace string has nothing to score either way, so it is treated the same as a blank row for sentiment purposes specifically.
- Merge note (2026-09-25): `labeling.py` and `sentiment.py` were built by two agents in parallel off the same base and each independently defined its own `ClaudeNotConfigured` and `FakeClaudeClient`, mirroring `embeddings.EmbeddingNotConfigured`'s pattern. They are separate classes with the same name; `app/text_pipeline/__init__.py` re-exports them as `LabelingClaudeNotConfigured`/`FakeLabelingClaudeClient` and `SentimentClaudeNotConfigured`/`FakeSentimentClaudeClient` rather than letting one import silently shadow the other. Worth consolidating into one shared Claude-client abstraction later.
- Deviation from the brief: `spot_check`'s `SpotCheckReport` has both `pairs` (every sampled answer's `{row, text, lexicon_tone, claude_tone, agree}`, capped at `sample_size` which is itself capped at ~100 by the caller) and `disagreements` (just the mismatches, capped separately at 20 for display) - the brief's item 4 asked for "the raw pairs for inspection" and item 5's dataclass only named `disagreements`; both are kept since neither list is ever the full raw dataset (bounded by `sample_size`).
- `ClaudeClient` is a plain `Any` type alias (matching `app/profiling/claude_hook.py`'s own `client: Any = None` style) rather than a structural Protocol, since a Protocol can only check attribute presence, not that `.messages.create(...)` has the right shape - no real safety over `Any` for this one nested-attribute case.
- `FakeClaudeClient` accepts either a fixed reply string or a callable `(kwargs) -> str`, so tests can build a reply that depends on what was actually sent (used to make the spot-check tests agree/disagree by answer content rather than by position).

## 2026-09-25 (Jev sentiment trial)
- Scoped to sentiment only, deliberately not extended to column-kind detection or theme merge/split flags: per the project's own comparison of task shapes, sentiment is the one per-answer, high-volume task in this pipeline (one classification call per survey answer, potentially thousands per dataset), which is exactly the profile Jev's cost/speed (70-500ms, cheap per call) suits. Column-kind detection (`app/profiling/`) and theme merge/split flags (`labeling.py`) are low-volume - one batched call per dataset/per column's clusters, not one per row - and are already served adequately by the existing batched Claude calls; adding a second AI vendor there would trade nothing for the added surface area. This trial therefore touches only `app/text_pipeline/jev_sentiment.py` and adds one new opt-in function, `sentiment.score_column_with_jev`; nothing else in the app references Jev or `TYPESAFE_API_KEY`.
- Polarity-from-confidence mapping (`sentiment._polarity_from_jev`): Jev's API returns a `(choice, confidence)` pair, not a signed number, but `AnswerScore.polarity` is a signed float in [-1, 1] that downstream code (`tone_split`, `chart_data.ToneSplit`) expects to stay in that shape. Chosen mapping: `pos -> +confidence`, `neg -> -confidence`, `neu -> 0.0` regardless of confidence (a "neutral" verdict has no direction to scale - scaling it by confidence would just move a neutral answer's polarity toward one pole or the other for no principled reason). This is a judgement call the API does not make for us, documented in `score_column_with_jev`'s docstring since it is not derivable from the brief or the API contract alone.
- `AnswerScore`'s shape was NOT changed: no `source`/`method` field was added, even though `score_column_with_jev`'s `max_answers` cap means some rows in a single call can be scored by Jev and others by the free lexicon fallback. Reasoning: `AnswerScore` is constructed in exactly one place in the codebase before this change (`sentiment.py`'s `score_column`; now two call sites, the second being `score_column_with_jev`) and read by `tone_split`, `_representative_sample`/`spot_check`, and re-exported via `app/text_pipeline/__init__.py`; none of that code was fully audited beyond what this trial needed to touch, so per the brief's own guidance the safer choice was to leave the schema untouched and document the cap/fallback behaviour in `score_column_with_jev`'s docstring and in `tests/test_jev_sentiment.py` instead (see `test_max_answers_caps_jev_calls_and_falls_back_to_lexicon`). A future pass that wants a per-row method marker should add it as a new optional field with a default, after checking every `AnswerScore(...)` call site (only two as of this change) and every reader of the dataclass.
- `HttpJevClient` follows `app/auth.py:_fetch_jwks`'s precedent exactly: plain `urllib.request`, no new HTTP dependency (`requests`/`httpx` were not added to `requirements.txt` - `httpx` in `requirements-dev.txt` is already there for FastAPI's test client, unrelated to this). ~10s timeout, response capped at 16KB (Jev's replies are one choice, three floats and a confidence - always tiny), one retry on a transient network error or a 5xx status only, never on a 4xx (a 429 or bad-request retried blindly would just repeat the failure or make rate-limiting worse). `classify_tone` validates the response strictly before it can become an `AnswerScore`: an unrecognised `choice`, an out-of-range `confidence`, a `probabilities` dict missing a key or not summing to ~1 (tolerance 0.02, since these are floats from an external API) all raise `JevError` rather than being trusted through.
- Deviation from the brief: none identified. `JevClient.classify_tone` also defensively rejects empty text and text over `MAX_TEXT_CHARS` (200,000 characters, a crude chars-per-token proxy for Jev's ~64k token budget) before ever building a request - not a practical limit for one survey answer, but the brief asked for defensive validation of the (non-binding) context budget even though it is never actually hit by this pipeline's per-answer calls.
- Real-world accuracy is unverified: every test in `tests/test_jev_sentiment.py` uses `FakeJevClient` or a monkeypatched `urllib.request.urlopen` - no real call to `api.typesafe.ai` was made (no `TYPESAFE_API_KEY` was available in this environment, and the brief requires zero network access in tests regardless). `HttpJevClient`'s request-building and response-parsing are exercised against hand-built response bodies shaped like the documented contract, not against Jev's actual live behaviour - real latency, real edge cases in how it phrases `choice`/`probabilities`, and real classification quality on this app's actual survey text are all unverified until someone runs it with a real key outside this trial's test suite.

## 2026-09-25 (build-themes API and screen: stream 6 finish)
- New `app/api_themes.py` wires the already-built `app/text_pipeline/` (embed, cluster, label, sentiment) to storage and an owner-only API, mirroring `app/api_cleaning.py`'s style: same `current_user`/`_own_dataset`, a `_Slot`/`BoundedSemaphore` concurrency cap, JSON stored on the ORM row rather than a side table. `app/text_pipeline/*` internals were not touched - only its public `__init__.py` surface is imported.
- Theme schema: added three nullable columns to `themes` (migration `f59a87637ace`, tested on a fresh SQLite file both up and down): `description` (Text), `tone` (JSON `{"neg","neu","pos"}` - the per-theme aggregate tone split the report screen needs; `Theme.sentiment` alone is one float and cannot carry a three-way split), and `column_name` (String, indexed). `column_name` was added even though `Theme.column_id` already FKs to `columns`: a `columns` row is only created by `confirm_columns`, and nothing requires that to have run before cleaning/theme-building (`test_cleaning.py`'s own tests never call it). Filtering/replacing themes by a FK that can legitimately be `None` would be unreliable, so `column_name` is the source of truth and `column_id` is set best-effort only when a matching row exists.
- Per-answer sentiment storage: NOT persisted as a new table/column. `Theme.tone`/`Theme.sentiment` cover the required per-theme aggregate; `GET .../themes/{id}/answers` recomputes each returned answer's tone on the fly with the free lexicon (`score_text` - pure, no network, no stored state), regardless of whether the theme's own aggregate was built with the lexicon or with Jev. Avoids a schema change and an `AnswerScore`-per-row table, at the cost of the drill-down tone not always exactly matching the aggregate's method - documented rather than silently inconsistent.
- DI seam for tests: `get_embedding_client`/`get_claude_client`/`get_jev_client_factory` are FastAPI `Depends` providers, matching `current_user`'s own override pattern (`app.dependency_overrides`). The first two build the real client and translate its `*NotConfigured` into `HTTPException(503, ...)` *inside the provider*, which is what lets FastAPI's dependency-exception handling turn it into a clean 503 instead of an uncaught exception. Jev is optional (`use_jev_sentiment`), so it cannot be eagerly resolved the same way (that would require `TYPESAFE_API_KEY` on every build); `get_jev_client_factory` instead provides a zero-arg factory (defaulting to `HttpJevClient`), which the route only calls, in its own try/except, when requested. Tests override all three with the Fake clients.
- Concurrency and deadline: `THEMES_CONCURRENCY` defaults to 1 (lower than cleaning's 2), since a build does real embedding/Claude network calls, not just pandas work. `THEMES_DEADLINE_SECONDS` defaults to 300s - a judgement call, not a measurement (no real Voyage/Anthropic key was available - see below), generous enough for embedding + clustering + one batched labelling call on a large column. Implementation is a SOFT deadline: the pipeline runs in a one-worker `ThreadPoolExecutor`, and on `future.result(timeout=...)` expiring the route returns 504 immediately but the worker thread keeps running to completion in the background (Python cannot kill a thread); its result is simply discarded. A background job queue is the right real fix, out of scope here. The timeout path has no dedicated automated test (fakes return instantly) and is reviewed by inspection only.
- "Solid"/"Tentative" indicator: a simple heuristic, not the findings engine - a real theme is "solid" if its size is at least both 20 answers and 8% of the column's total, else "tentative"; "Other" is always "tentative".
- Masking boundary (re-confirmed, not changed): the build pipeline only ever sees text through `model_safe_column`. `GET .../themes/{id}/answers` deliberately does NOT use it - it reads `clean_df.at[row, column]` directly, since that route is the owner viewing their own cleaned data, not a boundary to an external model. Covered by `tests/test_api_themes.py::test_answers_are_real_unmasked_text_not_masked`, which disables `mask_pii` so a real email survives cleaning, and asserts the fake Claude client's prompts never saw it while `/answers` returns it verbatim.
- Not independently verified in this environment: no `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY` or `TYPESAFE_API_KEY` was available, so the real clients were exercised only for their "key missing -> `*NotConfigured` before any network call" path (the 503 tests), never against a real API. All pipeline behaviour is tested against the Fake clients only, same limitation already logged for the labelling and Jev streams above.

## 2026-09-27 (findings engine: stream 7)
- Scope, deliberately narrow: SPEC.md section 9.3 lists five candidate-finding kinds; only two are built here - **tone contrast** (a theme's sentiment differs notably from the dataset's overall sentiment) and **dominant/rare theme** (a clear #1 theme, or an oversized "Other"/long tail). The other three ("a theme raised more by one group than the rest", "a number that moves with sentiment or score", "a trend over time") all need segment/score/date columns, which are SPEC.md build-order step 3 and out of scope for this stream. `app/findings.py`'s module docstring says this explicitly so it is not mistaken for an oversight later.
- Confidence thresholds (`app/findings.py`, all named constants at the top of the module, chosen since SPEC.md gives no exact numbers, only "label uncertain ones Tentative"): a candidate is discarded outright (never becomes a `Candidate`) below `app.cleaning.suppression.min_group_size()` (this codebase's existing "too small a group to report" floor, reused rather than a second constant) AND a kind-specific effect-size gate (`TONE_GAP_MIN=0.08`, `DOMINANT_SHARE_MIN=25%`+`DOMINANT_MARGIN_MIN=10pt`, `LONGTAIL_SHARE_MIN=15%`). "Solid" additionally needs the group to be at least `SOLID_COUNT_MULTIPLIER=2` times the suppression floor (e.g. 60 answers at the default floor of 30) AND a higher kind-specific bar (`TONE_GAP_SOLID=0.16`, `DOMINANT_SHARE_SOLID=35%`, `LONGTAIL_SHARE_SOLID=25%`); otherwise "Tentative". Every constant is a module-level name specifically so a future pass can retune without hunting through the logic.
- Candidate scoring blends effect size (the dominant factor) with a diminishing group-size bonus (`abs(gap) * (1 + min(1, size / (5 * floor)))` for tone contrast; margin-over-runner-up for dominant; share for long tail) - SPEC.md 9.3 asks for both "size of difference" and "group size" to matter, without specifying a formula.
- "Keep the top 3 to 5" (SPEC.md section 5) is implemented as a CAP (`MAX_CANDIDATES = 5`), never a floor: `candidate_findings` can legitimately return 0, 1, 2... or 5 candidates. This is what lets the engine express SPEC.md section 5's "also checked, nothing notable" case honestly instead of padding the report with weak findings just to hit a minimum count - `tests/test_findings.py::test_nothing_notable_returns_no_candidates` and `test_build_findings_nothing_notable_still_writes_a_report_with_only_overview_and_quality` cover this.
- Chart-selection fallback given no sub-theme data yet: `Theme` rows carry no sub-themes, so every `ThemeNode` this stream builds has `children=[]` - always fewer than the "3 sub-themes in total" SPEC.md section 4's table requires for a sunburst. Rather than rendering a sunburst with no outer ring (silently violating the table's own stated skip condition), `pick_chart` uses the table's own documented replacement: `long_tail` findings ("theme breakdown", `Other` unusually large) map to **treemap**, not sunburst. `dominant_theme` findings map to **rank** (the richest single view available in this small subset - share, count and a sentiment tint together - and matches the table's "prefer the chart that carries the most information" tie-break better than another share-only chart). `tone_contrast` findings map to **sentsun** (sentiment sunburst) since its own skip condition ("sentiment spread under 0.05") is about sentiment spread, not sub-themes, so it is unaffected by the gap. `tests/test_findings.py::test_pick_chart_mapping_and_the_sunburst_to_treemap_fallback` pins this down explicitly. Overview (priority 1, always first) and Quality (priority 9, always last) are fixed blocks, not routed through `pick_chart` at all - they are never scored as findings.
- `ContextData` (question kind/framing/length) falls back to honest, generic defaults (`kind="anything else"`, `framing="neutrally"`, `length="a sentence or two"`, `columns_note` stating score/segment/date cross-cuts are not wired in yet): `app/profiling/claude_hook.py` only infers column kind/unit and the question text, never question "kind" (reasons/improvements/...), framing or expected answer length, so there is nothing upstream to read yet. A future pass that adds that classification (SPEC.md section 2's "Question classification" row, itself not yet built) should wire its output into `build_report_data`'s `context` argument instead of this placeholder.
- Answer-length histogram (`QualityData.bins`/`typical_bin`): `build_report_data` is only handed `Theme` rows, not the cleaned dataframe, so it cannot cheaply compute a real word-count histogram itself. Rather than guessing, it takes an optional `answer_lengths: list[int] | None` and says so honestly (`bins=[("n/a", answered)]`, a note stating the gap) when the caller does not supply it. A sibling API-layer task that already loads the cleaned dataframe to build themes in the first place can pass real word counts through cheaply; `build_findings` threads the same optional parameter through.
- Render-vs-store-HTML: `Report.content` stores each block's `chart_id`/`finding_id`/`priority` only, NOT rendered HTML. `app/charts.py`'s `render()` is fast, pure-Python, and makes no network call, so re-rendering from the stored `Theme`/`Finding` rows on every read is both cheap and - unlike cached HTML - can never go stale after a theme rename/merge/split (SPEC.md section 5: "editing a theme... updates the whole report"). Storing HTML would have needed an invalidation story for exactly that case; not storing it needed none.
- `Finding`/`Report` have no `column` field (checked both models before writing any migration, per the brief's own instruction to migrate only for a genuine gap). Rather than adding one, `column` is stored inside `Finding.data`/`Report.content`, which already exist for exactly this purpose ("the specific numbers behind that finding" / the block list), and is used as the correlation key for "this dataset's report for this column" when `build_findings` replaces a prior report on rebuild. Documented here as a deliberate reuse of existing JSON fields, not an oversight of a missing column.
- `ClaudeNotConfigured` naming: reused `app.text_pipeline.LabelingClaudeNotConfigured` under the alias `FindingsClaudeNotConfigured`, rather than defining a third distinct-but-identically-shaped exception class. The 2026-09-25 text-pipeline entry above already flags `labeling.py` and `sentiment.py` independently inventing their own same-named-but-different `ClaudeNotConfigured` classes as "known duplication" that "a future pass should consolidate" - a third class would have deepened exactly that debt. `app/findings.py`'s `default_claude_client()` reuses `labeling.py`'s `AnthropicClaudeClient` directly (same key, same model, same lazy import) rather than a second real-client implementation, so `app/api_themes.py`'s existing `get_claude_client()` FastAPI dependency (which already catches `LabelingClaudeNotConfigured` and turns it into a 503) can be reused verbatim by a sibling API-layer route for findings-building too.
- `write_headline`'s actual signature takes `candidates: list[Candidate]`, not a single `Candidate` as the brief's numbered item literally named it - matching this codebase's mandatory "one batched call, never one per item" convention (SPEC.md section 2; `app.text_pipeline.labeling.label_clusters`'s identical precedent). A per-candidate function could not honour that convention without either making N calls or being a thin wrapper around a batching function anyway, so the batching function is what was built and named `write_headline`.
- `FakeClaudeClient` is defined locally in `app/findings.py` rather than imported from `app.text_pipeline`, matching this repo's existing precedent of one small Fake client per stream (already flagged as accepted debt in `app/text_pipeline/__init__.py`, not repeated here as a new problem).
- Not independently verified in this environment: no `ANTHROPIC_API_KEY` was available, so `write_headline`'s real-model path is untested beyond its strict parsing/validation logic against hand-built `FakeClaudeClient` replies. Real headline *quality* (whether Claude actually writes sentences matching SPEC.md section 5's style - "Charging carries the most negative wording" - reliably, across real survey data) is unverified; only the batching, prompt shape (numbers only, no raw text) and defensive parsing are tested. `candidate_findings`' thresholds are also unvalidated against a labelled gold set (SPEC.md section 6 calls for one before any prompt/model change ships) - they are a reasoned starting point, not a measured one.

## 2026-09-27 (dynamic report: API and screen, stream 8)
- Scope, matching the brief this stream was built from: SPEC.md section 5's header sentence, blocks, quality footer and "less text" rules, plus section 6's trust/quality block. The filter/sharing/export subsections of section 5 (global filter recompute, theme rename/merge/split, share roles and links, PNG/SVG/PPTX/PDF export) are explicitly a later stream and not touched here - `app/api_report.py`'s module docstring and CLAUDE.md's task list say so.
- `app/api_report.py` reuses, never duplicates: `app.api_themes._load_clean_df` (same cleaned-dataframe loader `api_themes.py`/`api_cleaning.py` already use - a private-by-convention helper, already imported across a module boundary by `tests/test_api_themes.py` itself, so this is an established pattern, not a new liberty), and `app.api_themes.get_claude_client` (the exact same FastAPI `Depends` provider, same function object, so overriding it in one router's tests also covers the other - see `tests/test_api_report.py`'s `_fake_claude_reply`, which has to speak both `label_clusters`' and `write_headline`'s prompt shapes because of this). "See answers" is `app.api_themes.theme_answers` unchanged; this module returns each finding's `theme_id` so the frontend calls that route directly.
- Concurrency: `REPORT_CONCURRENCY`, default **2** (`app/api_report.py::_SLOTS`). Chosen relative to the two existing conventions rather than invented from nothing: `CLEAN_CONCURRENCY` defaults to 2 for pure in-process pandas work (no network at all); `THEMES_CONCURRENCY` defaults to 1 because build-themes runs a real embedding call, clustering, AND a Claude labelling call - a genuinely heavy multi-step pipeline. Report building's only network cost is ONE small batched Claude call for headlines (`app.findings.write_headline`) over numbers that are already computed; every other step (loading stored `Theme` rows, scoring candidates, rendering charts) is in-process and fast. That is closer in weight to cleaning's "real but modest" load than to themes' heavy pipeline, so this stream matched cleaning's default (2) rather than themes' (1) or picking a third number with no anchor.
- `FindingsClaudeNotConfigured` is caught a second time inside `build_report`'s route body (mapped to the same 503), even though `get_claude_client`'s own `Depends` resolution already turns a missing key into a 503 before the route body ever runs, making that except-clause currently unreachable in practice. Kept because the brief this stream was built from named it explicitly as a required step; the route's own comment says so, so a future reader does not mistake it for dead code left by accident.
- No exact record counts on the report face (CLAUDE.md's design rule, applied here too): the one computed-in-code header summary line ("N themes found, overall tone X (+0.12)") is plain arithmetic on `build_report_data`'s own `overall_sentiment` and a count of non-"Other" themes - never a respondent/answer count, and never a second Claude call (SPEC.md section 2's "aggregated numbers only" rule, applied the same way `app/findings.py`'s own `_build_overview` already applies it to its insights).
- Rendering untrusted-shaped chart HTML safely: `app.charts.render()` returns a complete standalone HTML document (`<!doctype html>...`), by design (see `app/charts.py::render`) - not a fragment meant to be spliced into the app's own page. This codebase already has a documented habit of never using `dangerouslySetInnerHTML` for rendered content (see `Cleaning.tsx`'s own comment: "Nothing here uses dangerouslySetInnerHTML") and had no existing precedent anywhere for embedding one of these full documents in the app, so `frontend/src/Report.tsx`'s `ChartFrame` uses `<iframe srcDoc={...} sandbox="">` - the empty `sandbox` attribute is the most restrictive setting (no scripts, no same-origin, no forms, no popups), appropriate since `render()`'s output is static markup with no interactivity beyond CSS and needs none of those capabilities. The chart HTML is in fact trusted (server-rendered from stored numbers, never from user-typed text reaching the DOM unescaped - `app/charts.py`'s own `esc()` already handles that boundary), but the sandboxed iframe was used anyway rather than carving out a "this one's fine" exception, matching the rest of the app's general stance.
- Chart iframe sizing: `app.charts.py::frame()`/each `f_*` renderer bakes a fixed pixel width (1180) and a per-chart height (overview 680, rank 860, treemap/sentsun 800, quality 880) into the returned HTML - the charts are not responsive, by design, predating this stream. `Report.tsx`'s `CHART_HEIGHTS` map mirrors those numbers (plus a small margin) so the iframe's own height roughly matches its content without needing `postMessage`-based auto-sizing, which the empty sandbox deliberately rules out anyway (no scripts run inside the iframe to report a size back). On narrow screens `.rp-frame` scrolls horizontally rather than clipping or attempting to squeeze a desktop-first 1180px chart into a phone width - a known, accepted limitation of `app/charts.py` itself, not something this stream's scope covered fixing.
- Frontend architecture: extend `Themes.tsx`'s existing `/report` route rather than add a second route. `Themes.tsx` already owns dataset/column resolution, the "build themes" flow, and the verbatim drill-down (`AnswerList`) the report view's own "see answers" needs to reuse - a second route would have duplicated all three or forced an awkward cross-file dependency the other way round. Concretely: `AnswerList` was exported from `Themes.tsx` and its prop narrowed from a whole `ThemeCard` down to the one field (`themeId: number`) it actually used, so `Report.tsx` can call it directly with just a finding's `theme_id`, without either module depending on the other's full type. Once a report exists for the confirmed column, `Themes.tsx` renders `Report.tsx`'s `ReportView` in place of the plain theme-card grid; a "Manage themes" toggle switches back to the theme cards (for "Rebuild themes") and a "Rebuild report" action re-runs `build_findings` on demand, with a "Back to report" toggle to return. This was a judgement call, not something the brief pinned down exactly - documented here per the brief's own request to record it explicitly.
- Frontend test coverage: `frontend/src/Report.tsx` exports a pure presentational `ReportView` (report data comes in as a prop; nothing is fetched inside it), which let `frontend/src/report.test.tsx` use `renderToStaticMarkup` - the same style `frontend/src/home/home.test.tsx` and `frontend/src/auth/auth.test.tsx` already use for presentational components, and the only style this repo's vitest config (`environment: 'node'`, no jsdom) actually supports. `Themes.tsx` itself - the stateful wrapper that fetches themes/report and wires up the "Build report"/"Manage themes" actions - has no test file of its own (it had none before this stream either), and adding one would mean introducing jsdom plus fetch mocking, new test infrastructure this brief's scope did not ask for. `report.test.tsx` covers: header (question + computed summary), block ordering, Solid/tentative badge rendering, chart HTML only ever appearing inside a sandboxed iframe never inlined into the page, the "Also checked, nothing notable" phrasing, and no exact record counts in the summary line.
- Not independently verified in this environment: no `ANTHROPIC_API_KEY` was available, so - exactly as the 2026-09-27 findings-engine entry above already notes for `write_headline` itself - this stream's own round-trip test (`tests/test_api_report.py::test_build_then_get_round_trip_renders_real_chart_html_with_real_theme_names`) proves the HTTP wiring, chart rendering and headline plumbing end-to-end against a `FakeClaudeClient`, but real headline *quality* over a live model, and the real chart HTML's actual visual appearance inside an iframe in a live browser (checked by build/lint/types only, not by eye), were not checked against a live Claude key or a running browser.

## 2026-09-27 (projects list: stream 9)
- Scope: a user can now see and reopen files they have already uploaded without knowing a dataset id - `GET /api/projects` (`app/api_projects.py`) and the real `/projects` screen (`frontend/src/Projects.tsx`), replacing `App.tsx`'s old `<Placeholder title="Projects" />`. No migration was needed: every signal `status` reads already exists on `Dataset`/`Column`/`Theme`/`Report` from earlier streams.
- How `status` is computed without duplicating another module's business logic: `app/api_projects.py::_status` checks, most-advanced-stage-first, (1) any `Report` row for the dataset -> `"report ready"`, (2) any `Theme` row -> `"themes built"`, (3) `"report" in app.api_cleaning._stored(ds)` (that module's own accessor for `Dataset.profile["cleaning"]`, reused directly rather than re-parsing the JSON blob a second time; `"report"` is the exact key `api_cleaning.apply_cleaning` writes only once a plan has actually been applied, not just previewed) -> `"cleaned"`, (4) `"confirmed" in (ds.profile or {})` (the same expression `app.api_upload._view` already uses for its own `confirmed` field) -> `"columns confirmed"`, else `"uploaded"`. Steps (1) and (2) are deliberately a plain, direct `Theme.id`/`Report.id` existence query via the DB session rather than importing `app.api_themes.list_themes`/`app.api_report.get_report` (both are column-scoped and do much more work - re-rendering charts, paginating answers - than "does at least one row exist"), matching the brief's own instruction that a light direct read of these tables is fine here.
- `question`: only ever read from `(ds.profile or {}).get("confirmed", {}).get("question")` - i.e. the CONFIRMED profile, never the profiler's own initial guess (`profile["question"]["text"]`, which `Themes.tsx` falls back to for a different purpose). A dataset with columns not yet confirmed, or confirmed with a blank question, both show `null` (frontend falls back to the filename) - the brief asked for exactly this, not a "guessed question" fallback.
- Where each status links to, matching `Themes.tsx`/`Cleaning.tsx`'s existing `?dataset=<id>` query-param convention exactly (no new convention invented): `"uploaded"` -> `/check-columns?dataset=<id>` (nothing confirmed yet); `"columns confirmed"` -> `/cleaning?dataset=<id>` (cleaning has not run yet); `"cleaned"`, `"themes built"` and `"report ready"` all -> `/report?dataset=<id>`, because `Themes.tsx` already owns every step from "pick the open-text column" through "build themes" through "build/view the report" once cleaning is applied - a dedicated per-stage frontend route for each of those three would have duplicated logic `Themes.tsx` already has.
- Row counts: CLAUDE.md's "no exact record counts" rule is written for marketing/login screens; `/projects` is a signed-in screen, and this codebase's own signed-in screens are inconsistent here (`CheckColumns.tsx`/`Cleaning.tsx` print exact `toLocaleString()` row counts; `Report.tsx`'s header summary and the design reference's own "Recent projects" mockup do not carry that same restraint - it uses exact figures like "50,000 responses"). The brief for this stream explicitly asked for rounded/described counts here rather than exact ones regardless, so `frontend/src/Projects.tsx::roundedRowCount` rounds to 1 significant figure under 100 and 2 above that (e.g. `47973` -> `"about 48,000 rows"`), prefixed with "about" so it never reads as a precise figure. This is a deliberate, brief-driven exception to this app's own inconsistent precedent, not an oversight - documented here so a future reader does not "fix" it back to an exact count to match `CheckColumns.tsx`.
- `DELETE /api/datasets/{id}` was added (small, owner-only, mirrors `app.api_upload.confirm_columns`'s/`app.api_themes.build_themes`'s existing "delete old rows in an explicit loop before committing" convention rather than relying on the database to cascade - needed regardless of backend, since sqlite in this repo's own tests does not enforce `ON DELETE` actions by default). It deletes the `Dataset` row and its `Finding`/`Report`/`Theme`/`Column` rows. It deliberately does **not** delete the uploaded original or cleaned file on disk: `app.api_upload.upload` names files by content hash only (`UPLOAD_DIR/<sha256>.<ext>`), so two different users' datasets - or two datasets for the same user - can point at the very same on-disk file; unlinking it here on one dataset's delete could silently break a different, still-live dataset that happens to hash to the same content. Real garbage collection for orphaned upload files (reference-counting by hash, or a scheduled sweep) is a separate piece of work this stream did not take on. No frontend UI was wired to this route in this stream: the frontend brief for `/projects` asked only for a list, plain status, and a reopen link, not a delete flow (confirmation dialog, undo, etc.) - adding one was judged to be new scope, not implied by "add delete if it's small and safe."
- Test coverage (`tests/test_api_projects.py`) reuses existing test fixtures rather than duplicating them: `tests.test_api_themes.install_fakes` (fake embedding + Claude-labelling + Jev clients) and `tests.test_api_report.install_fake_claude`/`survey_df` (a Claude fake that also speaks `write_headline`'s "findings" prompt shape, needed once the pipeline reaches build-report) are imported directly and composed, so the suite drives the real `upload -> confirm columns -> clean/apply -> build themes -> build report` sequence through the actual HTTP API rather than seeding rows by hand, and asserts `status` advances correctly at every stage. Also covers: ownership isolation, newest-first ordering (by `Dataset.id`, not `created_at` - sqlite's `CURRENT_TIMESTAMP` default only has second precision, so two datasets created in the same test can share a timestamp; row id order is the reliable "insertion order" signal and is what `list_projects` actually orders by), the empty-list case, delete (both that it removes every dependent row and that it is owner-only), and a socket-blocking guard mirroring `tests/test_api_report.py`'s own (`test_zero_network_is_ever_attempted`).
- Frontend test coverage: `frontend/src/Projects.tsx` exports `ProjectsList`/`ProjectRow` as pure presentational components (the list comes in as a prop; nothing is fetched inside them), so `frontend/src/projects.test.tsx` uses `renderToStaticMarkup` wrapped in a `MemoryRouter` (`ProjectRow` renders react-router `Link`s, which need a router context - `frontend/src/home/home.test.tsx` is this repo's existing precedent for that combination). `Projects.tsx`'s default export (the stateful wrapper that calls `getProjects()`) has no test of its own, matching `report.test.tsx`'s own documented reasoning for `Themes.tsx`: exercising it would need jsdom plus fetch mocking, new test infrastructure outside this stream's scope.
- Deviations from the brief worth flagging explicitly: (1) the brief's frontend section did not ask for delete UI, so none was built, per the point above; (2) "optionally add a short 'Recent projects' section to the Upload screen" was left out - `Upload.tsx` is a focused, single-purpose drop zone and its own `Steps` component assumes a fresh upload is in progress; a second, differently-shaped list (with its own loading/empty states) would have made that screen's already-tight layout busier for a benefit the new `/projects` screen (linked from the nav bar on every page already) already covers, so it was judged not "small and natural" enough to force in.
- Not independently verified in this environment: no running browser was used, so the actual visual layout of `/projects` (row wrapping on narrow screens, the status pill's colour against `--surface` in the one light theme this app currently ships) was checked only by reading the CSS and this app's existing token values, not by eye.

## 2026-09-27
- Found and fixed a real deploy bug: `anthropic` was never added to requirements.txt across the project's whole history, even though app/text_pipeline/labeling.py, app/text_pipeline/sentiment.py and app/profiling/claude_hook.py all lazy-import it. Every deployment installs dependencies fresh, so the real package was never present on Railway, no matter how correct ANTHROPIC_API_KEY was. Its ImportError is caught and re-raised as the same ClaudeNotConfigured exception the missing-key case raises, so the resulting message ("ANTHROPIC_API_KEY... not configured yet") was misleading: the key was fine the whole time. Diagnosed by exec'ing into the live Railway container via `railway ssh` failed on host-key verification; the real cause was found by reading the exact import/exception code path and confirming `anthropic` is absent from requirements.txt and not importable in the dev venv. Fixed by pinning `anthropic==1.8.0` (whatever `pip install anthropic` resolved to at the time). The same message-conflation (missing key vs. missing package, both surfacing identical text) still exists in api_themes.py/api_report.py/sentiment.py and would be worth splitting into two distinct messages in a future pass, so this class of bug is diagnosable directly from the error text next time.

## 2026-09-27 (uploaded/cleaned file bytes moved off disk into Postgres)
- Real production bug this fixes, confirmed by a live traceback: `POST /api/upload` wrote the uploaded file to `UPLOAD_DIR` on the Railway container's own disk, and `apply_cleaning` wrote the cleaned CSV next to it - but that disk is ephemeral: every redeploy wipes it, so any dataset uploaded before a redeploy became permanently unreadable (`_load_df`/`_load_clean_df` both 404'd, since the file was simply gone). The obvious first fix - attach a Railway volume and point `UPLOAD_DIR` at its mount - was tried and did not work: the app's container runs as a non-root user (`useradd --uid 10001 verbatim` in the Dockerfile, so it never runs as root even for one write), and that user got a `PermissionError` writing to the mounted volume path. Rather than keep fighting Railway volume/ownership semantics (which would need matching the volume's UID/GID to the container's at attach time, redone on every volume Railway might recreate), the chosen fix stores file bytes in Postgres instead, which every other piece of state in this app (users, projects, datasets, themes, findings, reports) already relies on and which already reliably survives every redeploy.
- Two new tables (`app/models.py`, migration `f707d3907a31` after `f59a87637ace`): `UploadedFile` (`file_hash` String(64) primary key, `content` LargeBinary, `created_at`) and `CleanedFile` (`clean_hash` String(64) primary key, `content` LargeBinary, `created_at`). Both are pure content-addressed blob stores, deduplicated by hash exactly the way the disk paths (`UPLOAD_DIR/<hash><ext>`, `UPLOAD_DIR/<hash>.clean.csv`) already were - only the storage backend changed, not the addressing scheme or the dedup semantics (insert-or-reuse by primary key, with an `IntegrityError`-and-retry for the race where two requests store the same bytes at once, matching the existing pattern in `app/auth.py:user_for_subject`). Migration tested on a fresh SQLite file: `upgrade head` / `downgrade -1` / `upgrade head` / `downgrade base` all ran cleanly.
- `app/api_upload.py:upload()` now streams the incoming file into a `tempfile.NamedTemporaryFile` under the OS default temp directory (never `UPLOAD_DIR`), hashing and enforcing the size limit exactly as before. Once the hash is known, the bytes are stored in `UploadedFile` (insert-or-reuse - the dedup point for raw bytes, distinct from and in addition to the existing per-user `Dataset`-row dedup-by-hash, which is unchanged) before `profile_file` is called against that same temp file (it already has the right extension, so no second write was needed); the temp file is deleted in a `finally` block right after. On `LoadError`/a malformed file, the just-stored `UploadedFile` row is deleted again before the 400 is raised, mirroring the old code's `final.unlink(missing_ok=True)` on failure - a corrupted file's bytes are not kept either way.
- `app/api_cleaning.py:_load_df` now fetches `UploadedFile.content` by `ds.file_hash` from the database (404, same message, if the row is missing - this should now only happen from genuine data corruption, never a redeploy) and hands those bytes to `load_table` via a short-lived scratch file (see `scratch_file` below). `apply_cleaning`'s write step inserts-or-reuses a `CleanedFile` row by the digest of the cleaned CSV bytes instead of the old temp-file-then-`os.replace` dance.
- `app/api_themes.py:_load_clean_df` fetches `CleanedFile.content` by `clean_hash` and calls `pd.read_csv(io.BytesIO(content))` directly - no temp file at all, since pandas reads `BytesIO` natively (unlike `openpyxl`/`xlrd`, which need a real path). `app/api_report.py` needed no direct changes: it already reused `api_themes._load_clean_df` rather than reading the disk itself, and that import still works with the new `(ds, db)` signature after updating its two call sites.
- **Temp-file-for-library-compat approach, not a `profiling/loader.py` interface change**: the brief flagged changing `load_table`'s signature to accept bytes/`BytesIO` as higher-risk (more call sites depend on its current `path`-based contract) unless there was a clean, well-tested reason to do it anyway. There wasn't one here - `openpyxl`/`xlrd` need a real filesystem path (pandas' own CSV reader is the only one of the three that accepts `BytesIO`, and only api_themes.py's read path relies on that). So both `app/api_upload.py` and `app/api_cleaning.py` write the bytes to a short-lived file under the OS default temp directory (`tempfile.NamedTemporaryFile`, suffix set to the real extension so `load_table`'s dispatch-by-suffix still works), pass that path to `profile_file`/`load_table` unchanged, and delete it in a `finally` block immediately after. This is scratch space for a library that needs a path, not persistent storage: every container can always write to `/tmp`, no volume or non-root permissions to fight. The pattern is factored once, as `app.api_upload.scratch_file` (a context manager), and reused by `app.api_cleaning._load_df` rather than duplicated.
- **`upload_dir()`/`UPLOAD_DIR` removed entirely**, not kept as a narrow scratch-dir helper: nothing in the app needs a *configurable* scratch directory - the OS default temp directory (via bare `tempfile.NamedTemporaryFile`, no `dir=` argument) is enough, and the whole point of this change is that nothing about the file's location needs to be operationally meaningful (mounted, permissioned, backed up) any more. `app/cleaning/export.py` needed no code change at all - `csv_safe_frame`/`csv_safe_bytes` are pure in-memory pandas transforms with no disk I/O; only its docstring's stale `UPLOAD_DIR` reference was corrected. The Dockerfile's `mkdir -p /home/verbatim/.verbatim/uploads` was dead once `UPLOAD_DIR` was removed, so it was deleted too (the `useradd --create-home` step already gives `/home/verbatim` for anything else that might want it, and nothing does).
- Tests: every test that asserted on real files existing under a monkeypatched `UPLOAD_DIR` (`tests/test_upload_api.py`, `tests/test_cleaning.py`'s API section) was rewritten to assert on `UploadedFile`/`CleanedFile` rows instead - same claims (bytes stored, deduplicated by hash, not kept on a failed/oversized upload, original untouched by cleaning), just against the database rather than a `tmp_path`. The now-unused `monkeypatch.setenv("UPLOAD_DIR", ...)` fixture lines in `tests/test_api_themes.py`, `tests/test_api_report.py`, `tests/test_api_projects.py` and `tests/test_auth.py` were deleted (they set an environment variable nothing reads any more). Added `tests/test_api_themes.py::test_themes_build_after_the_disk_is_wiped_between_steps`: drives upload -> clean/apply -> themes/build through the real HTTP API (fake embedding/Claude clients only, as the rest of that file already does), and between steps points `tempfile.tempdir` at a dedicated scratch directory that the test itself `shutil.rmtree`s and recreates empty - simulating the container's disk vanishing entirely (a redeploy, or the `PermissionError` above) - then proves themes still build and are still readable afterwards, purely from `UploadedFile`/`CleanedFile` rows. (A dedicated directory was used rather than sweeping the shared OS temp directory, which other tests and pytest itself also use, so this test's "disk wipe" is safe to actually delete.) Full suite: 436 passed, zero real network (existing socket-blocking guards in `tests/test_api_report.py`/`test_api_projects.py`/`test_findings.py` were not touched and still pass).
- Left uncertain, flagged rather than guessed at: (1) Postgres row/column size limits for very large files stored as `bytea` - Postgres's per-column TOAST limit is about 1 GB, comfortably above `MAX_UPLOAD_MB`'s default (50 MB) and even a generous raised limit, but this was not load-tested against a real Postgres instance, only reasoned about; (2) whether Railway's managed Postgres migration step (`preDeployCommand` in `railway.json`) behaves identically to the SQLite upgrade/downgrade cycle tested here for a `LargeBinary`/`bytea` column - autogenerate produced a `sa.LargeBinary()` type that SQLAlchemy maps to `BYTEA` on Postgres and `BLOB` on SQLite, which should be portable, but this was only exercised against SQLite in this environment, never against a real Postgres server; (3) whether any orphaned `UploadedFile`/`CleanedFile` rows (from a dataset whose `Dataset` row was later deleted via `DELETE /api/datasets/{id}`, which - like the old disk behaviour - deliberately leaves the content-addressed blob in place since it may be shared) are worth garbage-collecting later; not attempted here, matching the brief's scope (storage backend only, not dataset-deletion semantics).

## 2026-09-27 (async build jobs: build-themes and build-report no longer block the request)
- The real bug, confirmed live: both `POST /api/datasets/{id}/themes/build` and `.../report/build` ran their whole pipeline inside the HTTP request, guarded only by a SOFT internal deadline (`ThreadPoolExecutor.result(timeout=...)` for themes; nothing at all for report). Python cannot forcibly kill a running thread, so a caller who hit that deadline (or whose browser simply gave up) saw an error, but the real embedding/Claude work kept running server-side regardless - a user watched Railway's CPU graph stay busy well after their browser showed a timeout, with nothing anywhere letting anyone check on it afterward. Fixed by moving the actual pipeline off the request entirely: `app/jobs.py` is the shared job-runner both routes now use.
- **New table**: `app/models.py:Job` (migration `e15812ca2ddb`, after `f707d3907a31`; tested upgrade head / downgrade -1 / upgrade head / downgrade base on a fresh SQLite file, all clean) - `id`, `dataset_id` (FK, `CASCADE`), `column_name`, `kind` (`"themes"`/`"report"`), `status` (`"running"`/`"done"`/`"failed"`), `step` (short plain-English phase), `error` (nullable - the exact message a caller would previously have received as an HTTP error body), `created_at`, `updated_at`. A fresh build replaces the prior job row for the same dataset+column+kind, mirroring `Theme`'s own existing rebuild-replaces convention - deliberately, not just for tidiness: on SQLite a plain integer primary key's rowid can be reused once a table is completely empty, so the delete and the insert are done in ONE commit (not two), exactly like `Theme`'s existing delete-then-`add_all`-then-one-commit shape; doing it as two separate commits was tried first and produced the same job id twice in a row, caught by this stream's own tests.
- **Shared, not duplicated, job-runner**: `app/jobs.py::start_job(job, slots, work, error_message, deadline_seconds=None, deadline_message=None)` is used by both `api_themes.build_themes` and `api_report.build_report`. Both routes' pipelines differ in shape (themes: embed -> cluster -> label -> score, writing `Theme` rows; report: one un-modified `build_findings` call plus a render pass), but "create the `Job` row, run a callable on a daemon thread, translate a caught exception into `job.error` via a per-route mapping function, release the concurrency slot only once real work finishes, optionally watch for a stuck job" was identical in both, so that part was written once. Each route supplies its own small `work(step)` closure and `error_message(exc) -> str | None` mapping function - not forced into one shared "themes-shaped" or "report-shaped" abstraction, since the two pipelines' actual bodies are legitimately different.
- **Route contract**: both build routes now validate everything cheap/instant SYNCHRONOUSLY, unchanged from before - ownership (`_own_dataset`), column exists, Jev/embedding/Claude key checks (the existing `Depends` providers, still instant 503s), and the concurrency slot (`_SLOTS.acquire(blocking=False)`, still an instant 429 if full - this one call still happens in the request, not the thread; see the concurrency note below for why). Once all of that passes, the route creates the `Job` row and starts the thread, then returns **202** `{"job_id": ..., "status": "running"}` immediately. 202 (Accepted), not 200, because nothing has been built yet at response time - the request only accepted the work, which is exactly what 202 means; a caller has to poll the job (or the existing `GET .../themes`/`GET .../report`) to find out what actually happened. A failure that can only be known once the pipeline runs (`TooFewAnswers`, `CleaningError`, `LabelingError`, `JevError` for themes; `NoThemesForColumn`, `FindingsClaudeNotConfigured` for report - the last one unreachable in practice, same as before) now surfaces as `job.error`, with the EXACT SAME message text the old synchronous HTTP error body used to carry (`_theme_build_error`/`_report_build_error` in each API module do this mapping, one function per route, tested against the literal old wording).
- **Concurrency slot ownership, a deliberate deviation from the brief's literal wording**: the brief says to acquire `_SLOTS` "inside the thread, not the request." Taken completely literally that would mean the request always returns 202 and a full slot could only be discovered later by polling a job that immediately fails with a "busy" message - but the brief elsewhere is equally explicit that cheap, instant checks (which a non-blocking semaphore probe absolutely is) stay synchronous errors, and the existing test suite already asserts an immediate 429 for this exact case (`_SLOTS.acquire(blocking=False)` held, then a build call is expected to 429 on the spot). Both instructions can't be honoured by a literal reading, so the design actually built is: the non-blocking `acquire()` still happens in the request (preserving the immediate 429), but ownership of releasing it moves into the thread - it is released only once the real work truly finishes (success, failure, or the watchdog's deadline), not after the old soft deadline that could and did lie about whether work was still running. This is what "held for the duration of the actual work" means in practice, and is checked by a test that starts two genuinely-running (not merely simulated) blocked jobs to exhaust the cap for real (`test_concurrency_cap_holds_while_a_job_is_genuinely_running` / `..._while_jobs_are_genuinely_running`).
- **`THEMES_DEADLINE_SECONDS`: kept, repurposed as a background watchdog, not retired.** Nothing on the request side blocks on it any more, so its old job (stop a single request from hanging forever) is moot - but a genuinely stuck inner step (a hung embedding/Claude call) would otherwise leave a `Job` row at `"running"` forever with no one ever told. `start_job`'s optional `deadline_seconds`/`deadline_message` start a second daemon thread that `join(timeout=deadline_seconds)`s the worker thread and, if it is still alive after that, marks the job `"failed"` with a clear "took longer than N seconds" message - a SANITY-CHECK watchdog only: Python still cannot kill the worker thread, which keeps running to completion regardless. To stop that eventual (real) completion from silently flipping an already-"failed" job back to `"done"` out from under a user who was already told it failed and moved on, `_mark_done`/`_mark_failed`/`_set_step` in `app/jobs.py` all guard on "only touch a still-`running` job" - tested directly (`test_watchdog_marks_a_truly_stuck_job_failed_without_stopping_the_real_thread`). `app/api_report.py` never had an equivalent deadline before this stream (only `THEMES_CONCURRENCY`/`REPORT_CONCURRENCY` existed on that side) and still doesn't - its own network cost is one small batched call, not a multi-step pipeline, so no watchdog was added there; revisit if that stops being true.
- **Database session inside the background thread**: `create_job`/`_write_theme_rows`/`build_findings`'s call site all need a `Session`, but the request's own `db` (from FastAPI's `Depends(get_db)`) closes the moment the request returns - long before the thread's work is done. `app/jobs.py`, `app/api_themes.py` and `app/api_report.py` all do `from . import db as _db` and call `_db.SessionLocal()` at the point of use (never `from .db import SessionLocal`, which would bind the name to the object that existed at import time forever). This is not just style: it is also what lets tests build a fresh engine per test and monkeypatch `app.db.SessionLocal` itself so the background thread's session lands on the SAME test database as the request's - the identical mechanism already used for the `get_db` FastAPI dependency override, just reachable from a plain background thread instead of a `Depends`.
- **Test infrastructure change, found the hard way**: the existing per-test fixture (`create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)` - one shared in-memory connection for the whole test) corrupted data intermittently once a background THREAD genuinely touched the database concurrently with the main test thread (observed directly: sporadic "Identity map already had an identity... replacing it" warnings and wrong row counts under the full suite, gone once fixed, present again on rerun before the fix). Real cause: one raw SQLite connection object shared and used concurrently from two different Python threads is not how any real database driver is meant to be used, in-memory SQLite `StaticPool` trick or not. Fixed in `tests/test_api_themes.py`, `tests/test_api_report.py` and `tests/test_api_projects.py`'s `env` fixtures: a real file-backed SQLite database under `tmp_path` with `poolclass=NullPool` instead - every session gets its own real connection to the same file (opened and closed per checkout), the way separate pooled connections to a real Postgres server already behave in production; no `check_same_thread=False` override needed since a `NullPool` connection is always used only by the thread that opened it. Verified stable across many repeated full-suite runs after the change (it was not before).
- **Tests** (all fake clients, zero real network - existing socket-blocking guards untouched and still pass): the full async flow through the real HTTP API - start a build, poll its job, see `step` change while `status` is still `"running"`, then reach `"done"` - using a `BlockingClient`/`_TwoWayBlock` (`tests/job_test_support.py`) that wraps one fake client method (`embed` for themes, `complete` for report) and pauses it on a `threading.Event` the test controls, so an intermediate step is OBSERVED, not merely inferred from timing. Also: a failure path (`TooFewAnswers` for themes, `NoThemesForColumn` for report) surfaces the exact old message text via `job.error`; ownership isolation on the new job endpoints (`GET .../jobs/{id}` and `.../jobs/latest`); the "resume after reload" `.../jobs/latest` lookup (matches the right job while running, keeps matching once done, 404 for the wrong column/kind, 404 before anything has ever started); the concurrency cap holding for genuinely-running (not merely semaphore-held) jobs; the watchdog test above. Full suite: 443 passed (436 before this stream + 7 new), run repeatedly with no flakes after the `NullPool` fix.
- **Frontend**: `frontend/src/jobsApi.ts` (`Job`/`BuildStarted` types, `getJob`, `getLatestJob`, `pollJob` - a 2-second interval, chosen as "frequent enough to feel live, infrequent enough not to hammer a build that can take minutes", not measured against a real deployment) and `frontend/src/JobProgress.tsx` (a pure, props-driven progress view: a plain-English `step`, a small CSS spinner as the "real work is happening" indicator - deliberately never a percentage or invented count, per CLAUDE.md's "no exact record counts" spirit extended to not inventing false precision here either). `Themes.tsx` (which already owns both the themes and report build flows - see the 2026-09-27 "dynamic report" entry above for why) is rewritten around a small `watch(job, setJob, refresh)` helper shared between starting a fresh build and resuming one found via `.../jobs/latest` on page load, so there is one polling wire-up, not two near-duplicates, for four call sites (start themes, resume themes, start report, resume report). On `status: "failed"`, the plain `job.error` text is shown with a "Try again" button - same honest-error style already used elsewhere in this app, no jargon, no stack trace.
- **Frontend test coverage**: `frontend/src/JobProgress.tsx` is pure/props-driven (the job comes in as a prop; nothing is fetched or polled inside it), so `frontend/src/jobProgress.test.tsx` uses `renderToStaticMarkup` - this repo's existing precedent (`report.test.tsx`) for testing a presentational component under a `environment: 'node'` vitest config with no jsdom. The stateful poller in `Themes.tsx` itself has no test of its own, matching `report.test.tsx`'s own already-documented reasoning for that same file: exercising it would need jsdom plus fetch mocking, new test infrastructure outside this stream's scope.
- **Not independently verified in this environment / genuinely uncertain**: (1) real-world polling frequency - 2 seconds is a judgement call for "feels responsive without hammering the server," not measured against actual embedding/Claude latency or Railway's request volume limits; a slower default (e.g. 3-5s) might be kinder to the server with no perceptible UX cost, worth revisiting with real usage data. (2) A job can still get stuck at `"running"` forever if the background thread itself dies in a way that skips both the `except`/`finally` in `start_job`'s `_runner` AND the watchdog never fires (e.g. `THEMES_DEADLINE_SECONDS` set to 0/disabled, or the process itself is killed - a daemon thread does not survive process death, and nothing re-derives job state from scratch on the next process start, so a job that was `"running"` when the whole server process was killed - not just this one request - would stay `"running"` in the database forever with no code path that ever revisits it). A real fix (a periodic sweep that fails any job whose `updated_at` is implausibly old, or a proper task queue with its own liveness tracking) was judged out of scope for this stream's brief (which asked for a background-thread watchdog specifically, not a whole second reconciliation system) but is the honest answer to "could this get stuck forever" - yes, in that one specific scenario (process death, not just a hung call), and this stream does not close it. (3) This was only tested against SQLite in-process threads; real Postgres connection-pool behavior under many concurrent background threads on Railway (pool exhaustion, connection lifetime under load) was reasoned about, not load-tested.

## 2026-09-27 (clustering bug: real embeddings, not fake ones, broke HDBSCAN)
- **The bug, confirmed live**: the first time this pipeline ran against a genuine dataset (Women's Clothing E-Commerce Reviews, a well-known, naturally clusterable public dataset, 23,486 rows) rather than `FakeEmbeddingClient`'s fixtures, `cluster_answers` put 22,641 of 23,486 answers (96%) into noise - essentially no themes found. The embedding call itself clearly succeeded (a failure there would have failed the whole job, not produced a result) and sentiment scoring on the same run - which does not touch clustering at all - produced a believable 74% positive, so the failure was isolated to clustering specifically. Voyage's own documentation confirms its embeddings are already unit-length, ruling out a normalisation bug. The real cause: `voyage-3.5` embeddings are 1024-dimensional, and HDBSCAN (density-based) is well documented to perform badly directly on raw high-dimensional vectors - distances between points concentrate (everything ends up roughly, uselessly equidistant), so HDBSCAN can no longer tell a genuinely dense region from background noise. This is exactly why established text-clustering tools built on HDBSCAN (BERTopic, Top2Vec) reduce dimensionality first and cluster the reduced vectors, never the raw ones. It was invisible in this project's own tests because `tests/test_text_pipeline.py`'s fixtures all use `FakeEmbeddingClient`'s 32-dimensional vectors - low enough that the problem barely bites - so the module was built and tested only against exactly the case that could never expose this failure.
- **The fix**: `app/text_pipeline/clustering.py` now reduces vectors with UMAP (`umap-learn==0.5.12`, added to `requirements.txt`) before HDBSCAN ever sees them, via a new `_reduce_for_clustering` step. `metric="cosine"` (the correct metric for normalised, unit-length text embeddings - UMAP's default is Euclidean, the wrong choice here), `min_dist=0.0` (UMAP's own documented recommendation when the output feeds a clustering step rather than a 2D plot - pack points as tightly as the manifold allows), and a fixed `random_state=42` so the same input always reduces to the same output. `n_neighbors=15` (UMAP's own well-tested default), clamped to `n - 1` for safety. Target dimensionality is adaptive, not one fixed constant, via a new `adaptive_n_components(n_answers)`: `round(n_answers / 300)` clamped to `[5, 15]` - 5 is the common default both BERTopic and Top2Vec use, 15 a common practical ceiling past which UMAP's own reduction starts giving back some of the sparsity it was meant to remove; growing mildly with answer count matches this module's existing `adaptive_min_cluster_size` philosophy (more answers give UMAP more to work with).
- **Skip threshold (so every existing small-fixture test keeps passing unchanged)**: `_reduce_for_clustering` skips itself - clustering the original vectors exactly as before - below EITHER `MIN_ANSWERS_FOR_REDUCTION = 50` or `MIN_DIMENSIONS_FOR_REDUCTION = 50`. Reasoning for 50 answers: UMAP needs enough points to build a trustworthy local-neighbourhood graph; with its own `n_neighbors` defaulting to 15, a widely used rule of thumb is at least 3-4x that many points before trusting the result, and 50 sits just above that band (and comfortably above every existing fixture's size - 63 is the largest currently in the test file). Reasoning for 50 dimensions: the failure this step fixes is specifically a high-dimensionality problem; real Voyage vectors are 1024-dimensional, `FakeEmbeddingClient`'s test vectors are 32-dimensional by default, and 50 sits cleanly between the two, so low-dimensional fixtures are recognised as not needing a fix for a problem they don't have - not merely tuned to dodge the tests. Both thresholds are named constants in `clustering.py`, not magic numbers.
- **`min_samples` tuning, and why it's gated the same way**: HDBSCAN's own default sets `min_samples = min_cluster_size`, which is unusually strict and (in the same real, high-dimensional scenario) a secondary contributor to over-aggressive noise labelling. New `adaptive_min_samples(min_cluster_size)`: `round(min_cluster_size / 3)` clamped to `[3, 10]` - always well below `min_cluster_size` itself (floor 3 at `min_cluster_size = 5`, ceiling 10 at `min_cluster_size = 50`), because "how dense must a region be to not be noise" and "how big must a group be to report as a theme" are different questions and HDBSCAN's default answers both with the same number. This tuning is applied ONLY when reduction actually ran (`clustering_vectors is not vectors` after `_reduce_for_clustering`) - not unconditionally - because the first attempt at this fix applied it unconditionally and broke an existing test (`test_cluster_answers_finds_distinct_fake_clusters_and_keeps_noise`, which found 3 clusters instead of the expected 2 once `min_samples` was decoupled on its 32-dimensional fixture). Gating it to "only when the real fix actually kicked in" is not just a test-dodge: `min_samples`'s old default was never the primary problem on low-dimensional inputs, so leaving it untouched there is honest, not merely convenient.
- **Distance/centroid consistency fix, found while making this change**: `cluster_answers` computed each member's `distance` as `_euclidean(vectors[i], centroid)` using the ORIGINAL vectors even though HDBSCAN's centroid came from whatever space it actually clustered on. Once clustering could run on reduced vectors, that would have silently zipped mismatched-length vectors together (Python's `zip` truncates, so this would have produced a wrong number - not a crash) for every reduced answer. Fixed: `distance` is now computed against `clustering_vectors[i]` (the same space HDBSCAN saw), which is simply `vectors[i]` unchanged whenever reduction was skipped, so this is a no-op for every existing test.
- **Determinism, re-confirmed**: the module's docstring claim ("deterministic given the same input") still holds, now resting on a fixed seed (`UMAP_RANDOM_STATE = 42`) rather than "nothing to seed" (HDBSCAN itself has no random component; UMAP's optimisation does, and needs the seed). A fixed `random_state` also forces UMAP to run single-threaded (its own documented trade-off - parallelism is not reproducible), which is slower but correct for this guarantee. Tested directly: `test_cluster_answers_reduction_path_is_deterministic_given_same_input` runs the same high-dimensional fixture through `cluster_answers` twice and asserts identical cluster membership and noise.
- **Tests proving the bug and the fix** (`tests/test_text_pipeline.py`): a new deterministic, high-dimensional synthetic fixture (`_high_dimensional_fixture`, plain numpy, NOT `FakeEmbeddingClient` - that client is only 32-dimensional by design) builds 3 separable groups of 60 unit-length 300-dimensional vectors each (a random direction per group plus substantial per-dimension noise across all 300 dims, mimicking how a real embedding's true semantic signal is thin relative to the many other directions in the space) plus 15 unrelated noise vectors. `test_cluster_answers_on_raw_high_dimensional_vectors_finds_almost_nothing` runs plain `sklearn.cluster.HDBSCAN` directly on the raw vectors (the old code path, reproduced inline) and asserts it finds ZERO real clusters - all 195 answers written off as noise, reproducing the live bug's shape exactly. `test_cluster_answers_recovers_separable_groups_with_reduction` runs the SAME fixture through `cluster_answers` (the fix) and asserts it recovers at least 2 real clusters, noise drops below 50% of all answers, and each recovered cluster is >75% pure (dominated by one true group) - a direct, numeric proof that the fix changes the outcome, not just that nothing crashes. Also added: `_reduce_for_clustering` skip-threshold tests (below each of the two thresholds, the function returns the input unchanged by identity), `adaptive_min_samples`/`adaptive_n_components` boundary tests, and a zero-network test (`test_cluster_answers_with_reduction_never_touches_the_network`, same `socket.socket`-patching pattern already used in `tests/test_findings.py`/`test_api_report.py`/`test_api_projects.py`) confirming UMAP and HDBSCAN are pure local compute, as expected. Full suite: 452 passed (433 before this stream + 19 new/changed in `test_text_pipeline.py`).
- **`umap-learn` dependency, verified clean**: `umap-learn==0.5.12` installs cleanly via pip and imports without any native-build step (no compiler needed at install time). It pulls in `numba` (JIT compiler, via `llvmlite`/LLVM), `pynndescent`, `scipy`, and `tqdm` as transitive dependencies. Worth flagging honestly, not glossing over: `numba`'s JIT means UMAP's FIRST import in a fresh environment is slow - measured at ~50 seconds in this environment, spent compiling and disk-caching UMAP's numba-jitted functions - while every import after that (same environment, cache present) is ~3 seconds. This is a one-time, per-environment cost (e.g. once per deploy image build/first server start), not a per-request or per-test-run cost, but it is real and should be expected the first time this deploys, not mistaken for a hang.
- **Candid limitation - NOT re-verified against the real dataset that exposed this bug**: no live Voyage or Anthropic API key is available in this environment, so this fix has NOT been re-run against the actual 23,486-row product-review dataset that produced the original 96%-noise result. Everything here - the UMAP parameters, the two skip thresholds, the `min_samples` formula - is a well-reasoned best attempt based on established practice (BERTopic/Top2Vec's own defaults, UMAP's own documented guidance for clustering use, and a synthetic high-dimensional fixture built specifically to reproduce the failure's shape), verified against that synthetic fixture and against every pre-existing low-dimensional test, but it is NOT a guaranteed fix confirmed against the exact data that exposed the problem. The honest next step, whenever a Voyage key is available, is to re-run the real dataset through `embed_and_cluster` end to end and check the noise fraction and theme count directly, rather than trusting the synthetic proxy alone.

## 2026-09-28 (report page: fragments, not iframed documents)
- **The problem, confirmed by the person who designed the original mockup**: the `/report` screen (`frontend/src/Report.tsx`) read as "a bunch of charts" - disconnected boxed mini-websites - rather than one coherent report, and the person who designed `design/screens/report-ev.dc.html` (the approved mockup for exactly this screen) confirmed this directly. The root cause was structural, not cosmetic: every block's chart arrived from `GET .../report` as `app.charts.render()`'s own FULL standalone HTML document (its own `<!doctype html>`, its own `<link>` to Google Fonts, its own `background`), which the frontend then dropped into a hard-`sandbox=""` `<iframe>` with a blanket `min-width: 1180px` applied to every chart regardless of its real size. Each chart was, literally, its own tiny web page glued onto the report - never sharing the page's background, spacing or typography, which is exactly why it read as boxed and disconnected.
- **The fix**: `app/api_report.py`'s `GET .../report?column=...` now returns each block's chart via `app.charts.render_parts` (the raw body FRAGMENT - no `<!doctype html>`, no own background/font - already used for other purposes in `charts.py`, not newly added), plus its own `chart_width`/`chart_height`, instead of `render()`'s full document. `frontend/src/Report.tsx` embeds that fragment straight into the page's own DOM via `dangerouslySetInnerHTML`, sized by its own `chart_width`/`chart_height` rather than a hardcoded per-chart-id guess, wrapped only in a `.rp-chart-scroll` that grows a horizontal scrollbar when that fixed-pixel content genuinely exceeds the viewport - not a blanket forced minimum applied to every chart. This is a small, surgical change to that one route's response-shaping; `app/findings.py`'s and `app/charts.py`'s own logic were not touched.
- **Why `dangerouslySetInnerHTML` is safe here specifically, and nowhere else in this app**: every other screen in this app (see `Cleaning.tsx`'s own comment) renders text as plain React children because that text can be user-authored (survey answers, column headers) and must never be interpreted as HTML. Chart fragments are different in kind: they are 100% server-generated from typed numbers and theme labels already run through `app.charts.py`'s own `esc()` HTML-escaping, via a route that accepts no free-text body from the caller. There is no path by which a viewer's own typed text reaches this string. `Report.tsx`'s `ChartFragment` component carries this reasoning in a code comment so a future reader sees it as a deliberate, scoped exception rather than a precedent to copy elsewhere.
- **CSS token reconciliation**: `app/chart_data.py`'s header comment and `app/charts.py`'s own `CSS` block both confirm the chart SVGs are drawn entirely from CSS custom properties (`--bg --surface --ink --muted --line --accent`, `--t1..--t7 --other`, `--neg/--neu/--pos`, `--ramp`), and `frontend/src/index.css` already defined the same names with the same light-theme values - both were built from the same design system, so a fragment embedded directly into the page's DOM inherits the page's own tokens with no extra CSS, as intended. One real gap found while checking every chart id this report actually reaches (`overview`, `rank`, `treemap`, `sentsun`, `quality` - see `app/findings.py`'s `CHART_BY_KIND`): `charts.py`'s `CSS` block also defines "on-colour" tokens (`--on-accent`, `--on-neg`, `--on-neu`, `--on-pos`, `--on-ramp`) for text printed on top of a tone/accent-filled shape (used by `rank`'s segmented control and by `sentsun`'s tone-split arc labels), and `index.css` had none of them. Reconciled by adding all five (light-theme values only, matching this project's "light theme only for now" rule) to `frontend/src/index.css`, including `--on-ramp` even though no chart this report currently reaches uses it, so the next chart kind `findings.py` wires in (e.g. `heatmap`) does not silently regress.
- **The honest "Columns used" chip row**: the mockup's own example row shows six chips (an open-text column plus age group, a score, an income band, a survey date, and sex) because SPEC.md section 9's structured-column findings (score/segment/date-driven) are its illustration of the finished product. `app/findings.py`'s own docstring is explicit that this is a "deliberately narrow first pass" - only `tone_contrast` and `dominant_theme`/`long_tail` findings exist today, computed purely from `Theme` rows on one open-ended text column; there is no score/segment/date column wired into report-building at all yet. Showing the mockup's fictional richer example would misrepresent what this build actually does. `ReportView` shows exactly one chip - the report's own `column` (the open-text column that themes were actually built from), labelled "open-ended text" - which is the only thing this route can honestly claim to have used, and revisits this decision once step 3 (score/segment/date findings) is built.
- **Known, accepted overlap - not fixed, out of scope**: `app.charts.f_overview`'s own fragment bakes in a second, smaller "What stands out" sub-heading (two generic sentences from `OverviewData.insights`, computed in `app/findings.py:_build_overview` from plain arithmetic on the numbers - largest theme's share, long-tail share). This sits directly below the new page-level "What stands out" list (built from real `Finding` sentences, with Solid/Tentative badges) that this stream added, since the overview chart is rendered as the first story block right after it. Fixing this properly means either changing what `OverviewData.insights` contains or changing `f_overview`'s own markup, both in `app/findings.py`/`app/charts.py` - explicitly out of scope for this stream (constrained to `api_report.py`'s response-shaping and the frontend). Documented here honestly rather than silently left for someone else to rediscover; the two sections differ enough in presentation (a numbered list with badges vs. a plain two-line note nested inside a stat card) that it reads as two related things, not a broken duplicate, but it is still a real seam worth closing in a later stream.
- **Responsive behaviour, and its real limit**: `app/charts.py`'s frames have a fixed pixel `viewBox`/internal layout (`frame()` always returns width 1180 for every chart id this report reaches) with no percentage-based internals - confirmed by reading `f_overview`/`f_rank`/`f_treemap`/`f_sentsun`/`f_quality` directly, not assumed. `ChartFragment` sizes its wrapper to the fragment's own reported `chart_width` and only lets `.rp-chart-scroll` scroll horizontally when that exceeds the viewport, rather than the old blanket `min-width: 1180px` forced onto every chart regardless of its real size - a real improvement (a future chart kind returning a narrower `chart_width` would need no scrollbar at all), but since every chart this report reaches today happens to report the same 1180px width and the app's own `.page` container caps content at 960px, a horizontal scrollbar inside the chart area is still the practically-always case on any screen, not a rare edge case - not fixable without changing `charts.py`'s own fixed-pixel frames, which is out of scope here.
- **Not independently verified in a real browser**: this environment has no way to open the running app and look at the rendered page. Verified instead: `npm run build`/`npm run lint` pass, the full backend (452) and frontend (28) test suites pass, and the fragment's raw markup (confirmed by reading `f_overview`/`f_rank`/`f_treemap`/`f_sentsun`/`f_quality`'s actual returned HTML) uses only the CSS custom properties now confirmed present in `index.css`. A real-browser screenshot pass is the honest next step before calling this visually done, not assumed here.

## 2026-09-29 (score/segment/date findings: cross-tab plumbing, part B2 of a 3-part stream)
- **Per-band/per-period sentiment is a documented approximation, not a per-row recomputation**: no per-answer sentiment is persisted anywhere in this codebase (see the 2026-09-25 entry, "Per-answer sentiment storage: NOT persisted" - only each `Theme.sentiment`, one aggregate float per theme, exists). `app/findings_structured.py`'s `build_score_data`/`build_trend_data` therefore compute `ScoreBand.sentiment`/`TrendData.sentiment[i]` as a count-weighted average of each theme's *aggregate* `Theme.sentiment` over the rows landing in that band/period - the same approximation `app/findings.py::_overall_sentiment` already makes globally for the report's own `overall_sentiment`, just re-weighted per cell rather than across the whole dataset. Stated plainly in the module's own B2 section-header comment and in both functions' docstrings so a future reader does not mistake it for a true per-cell recomputation.
- **Scope**: this is B2 of a 3-part stream (banding math in B1, already merged; the new `segment_skew`/`score_correlation`/`trend_shift` candidate-finding kinds and the `app/api_report.py` wiring that actually surfaces them in a real report are B3, not yet built). `app/findings.py::build_report_data` gained one optional `structured: StructuredContext | None = None` parameter that fills real `score`/`segment`/`trend` data when given; `candidate_findings`/`build_findings`/`CHART_BY_KIND`/`context.columns_note` are all untouched, so populating this data has no visible effect on a real report yet - `pick_chart` still never selects `byScore`/`heatmap`/`trend` for any finding until B3 lands.
- **B3 (findings wiring end to end) is now built too, on top of the above**: `app/findings_structured.py` gained `segment_skew_candidates`/`score_correlation_candidates`/`trend_shift_candidates`, each with its own gate/"Solid" threshold pair (`SEGMENT_SKEW_RATIO_MIN/SOLID`, `SCORE_SPREAD_MIN/SOLID`, `TREND_SHIFT_MIN/SOLID`) named the same way `app/findings.py`'s pre-existing constants are. `app/findings.py::candidate_findings`/`build_findings` gained the matching optional `structured` parameter, appending these 3 new kinds into the SAME ranked candidate pool `tone_contrast`/`dominant_theme`/`long_tail` already go through before `MAX_CANDIDATES` truncates it, and `label_confidence` was extended with each new kind's own "Solid" check (not explicitly asked for in this stream's brief, but without it every new-kind `Finding` would always render "Tentative" regardless of its real effect size, defeating the whole point of the gate/solid distinction spelled out above).
- **Score-scale decision, honoured as scoped (corrected during coordinator review)**: `app/findings.py::candidate_findings`'s own existing kinds are not all on one scale to begin with - `dominant_theme`'s score is a bare percentage-point margin (`score=margin`) and `long_tail`'s is a bare percentage-point share (`score=share`), NEITHER with any size-bonus multiplier; only `tone_contrast` multiplies its effect size by a size bonus, on its own -1..+1 sentiment-gap scale. The subagent that built this stream's first draft made all 3 new kinds' `Candidate.score` a percentage-point effect size *times* `tone_contrast`'s own size-bonus shape (`1 + min(1.0, count / (5 * floor))`) - correct units, wrong shape: on review this was caught because it does not "match `dominant_theme`/`long_tail`", it out-scales them (an equivalent-sized real-world effect would score ~1-2x higher for a new kind than for `dominant_theme`/`long_tail`, since only the new kinds get the extra multiplier), risking the opposite failure from the one this decision was meant to prevent - new kinds systematically crowding out the old ones, not competing fairly with them. Fixed to a bare percentage-point score with no multiplier at all (`segment_skew`: the group-vs-overall gap; `score_correlation`: the raw `spread_pct`; `trend_shift`: the raw `abs(change_pct)`), which is what actually matches `dominant_theme`/`long_tail`'s existing shape. `tone_contrast`'s existing scoring/thresholds were not touched at all; the pre-existing mismatch between it and the other 4 (all bare percentage points) is left as documented, known debt, exactly as scoped. The synthetic all-5-kinds-qualify-at-once test (`test_candidate_findings_all_five_kinds_qualify_and_new_kinds_are_not_crowded_out` in `tests/test_findings_structured.py`) only asserts the new kinds AREN'T shut out entirely, not that representation is balanced - it does not by itself catch an over-correction in the other direction, so this was found by reading the scoring code directly against `dominant_theme`/`long_tail`'s real formula, not by a failing test. A future pass could strengthen that test to assert a healthier mix of old/new kinds once real report data makes clear what "healthy" should look like.
- **`score_correlation`'s chart is `byScore`, not `Sankey`**: SPEC.md section 4's table pairs "a number that moves with sentiment or score" with Sankey (priority 5); this app has no Sankey renderer built or tested. `byScore` (already built, tested, and visually matching the mockup's "score-band bar chart") is used instead - a deliberate, scoped SPEC.md deviation, not an oversight; `PRIORITY_BY_KIND["score_correlation"] = 5` still matches the table's own priority number for that row.
- **`trend_shift`'s per-period answer counts don't exist, so its gate falls back to the theme's overall size**: `TrendData`/`TrendSeries` (`app/chart_data.py`) carry each period's theme *share* and the period's aggregate sentiment, but no raw per-period answer count per theme. Every surviving period already cleared `build_trend_data`'s own per-period floor (SPEC.md's trend-specific "under 30" skip row), so `trend_shift_candidates`'s gate instead checks the theme's own overall stored `Theme.size` against `floor` - a documented substitution, not a silently-skipped check. Relatedly, `TrendData` itself carries no column-name field (unlike `ScoreData.name`/`SegmentData.name`), so `trend_shift_candidates` takes an extra `column: str = ""` parameter beyond the session plan's literal 3-argument stub, which `candidate_findings` fills from `structured.trend_column_name`.
- **Circular import, resolved with a deferred import inside each new function**: `app/findings.py` already imports `StructuredContext` from `app/findings_structured.py` at module level (from B2); the 3 new functions need `Candidate` (and `score_correlation_candidates` also needs `theme_nodes`) from `app/findings.py`, which would be a genuine import cycle at module level. Each function instead does `from .findings import Candidate` (deferred to inside itself) rather than restructuring either module - by the time any of these functions is actually called, both modules have finished loading. `python -c "import app.findings"` and `python -c "import app.findings_structured"` both still succeed standalone.

## 2026-09-29 (real sub-theme clustering: S2, storage + backend wiring)
- **`Theme.sub_themes` is a JSON column on the same row, not a new table** (plan decision 1/6). Two facts from this stream's plan review, both re-verified directly against the code before being relied on: (1) `app/api_projects.py::delete_dataset` (lines 76-86) is a THIRD manual cascade-delete site, alongside `app/api_themes.py::_write_theme_rows`'s own rebuild loop - a new child table would have needed updating in both places, kept in sync by hand, forever; a JSON column needs no cleanup code anywhere, it dies with the `Theme` row both places already delete. (2) `app/api_report.py::_render_report` calls `build_report_data(...)`, which calls `app.findings.theme_nodes(...)` - the real report page's chart data already flows through that one function, so making it read `t.sub_themes` directly off the `Theme` row it is already handed means EVERY caller (there are exactly four: `build_report_data`, `app.api_themes.themes_chart`, `app.api_report._structured_context_for`, `app.findings_structured.score_correlation_candidates`) gets real `ThemeNode.children` for free, with zero signature changes anywhere. Cost accepted knowingly: no stable sub-theme id across a rebuild (fine - a rebuild already replaces the whole parent `Theme` row) and no FK a future `Finding` could point at directly (a real limitation only if that's ever needed; a table migration stays possible then).
- **Every new constant lives in `app/text_pipeline/subthemes.py` (S1, already merged) and is only summarised here, not redefined**: `MIN_THEME_SIZE_FOR_SUBTHEMES=100` (a parent needs at least this many answers before a sub-pass is attempted, comfortably above `clustering.py`'s own `MIN_ANSWERS_FOR_REDUCTION=50` so UMAP reduction always runs for an eligible parent and the sub-pass can't hit the raw-high-dimensional-HDBSCAN "96% noise" failure mode from the 2026-09-27 clustering entry above), `MAX_THEMES_TO_SPLIT=7` (matches `app/charts.py`'s `t1`..`t7` palette - an 8th-ranked theme already folds into "Other" on the treemap and its sub-themes could never be drawn regardless), `MAX_SUBTHEMES_PER_THEME=3` (`app/charts.py`'s `MIX` is a hardcoded 3-element list), `MIN_SUBTHEME_SHARE_OF_PARENT=0.10` (a sub-theme must hold at least 10% of its OWN parent's answers - relative to the parent, not the whole-dataset `adaptive_min_cluster_size` formula, which would produce far too many micro-clusters on a 100-2000-answer subset), `MIN_SUBTHEME_COVERAGE=0.50` (a parent's sub-themes are stored only if the kept ones together cover at least half its answers - otherwise a treemap block would visually imply "this theme = these 1-2 small sub-themes" when squarify actually scales them to fill the WHOLE parent rectangle regardless of true coverage, a real silently-misleading-chart risk the plan's design review caught). "Other"/noise is never sub-clustered (decision 2) - `eligible_parents`/`sub_cluster_themes` only ever look at `result.clusters`, never `result.noise`, and `_write_theme_rows` below sets the "Other" row's `sub_themes=[]` unconditionally, without even checking the `sub_clusters` dict for it.
- **Labeling-failure fallback (decision 10), and exactly what it does and doesn't catch**: `app/api_themes.py`'s `build_themes._work` wraps ONLY the `label_sub_clusters(...)` call in `try/except LabelingError` - not the sub-clustering step itself (`sub_cluster_themes`, pure local compute, no network, nothing to catch there) and not the main `label_clusters` call (unchanged, still propagates as before - only the OPTIONAL sub-theme enhancement gets this safety net). On `LabelingError` the job logs a warning (`log = logging.getLogger("verbatim.themes")`, this module's first logger - no prior logging import existed here) and falls back to `sub_labels = {}`; every theme is then stored with `sub_themes == []` (checked in `_write_theme_rows` via `if sub_clusters and sub_labels and cluster.id in sub_clusters` - an empty `sub_labels` dict is falsy, so this short-circuits to `[]` for every real theme without a special case), and the job still reaches `"done"`, not `"failed"`. Any OTHER exception out of that call (a real bug, not an untrusted reply) still propagates through `start_job`'s own top-level catch exactly as every other unanticipated exception in this pipeline already does.
- **`_write_theme_rows`'s new `sub_clusters`/`sub_labels` params default to `None`, confirmed to be backward-compatible**: grepped for every caller before changing the signature - `build_themes._work` is the only one in the whole codebase (`app/`, `tests/`), so the "byte-identical when omitted" claim was actually checked, not assumed. The inner `_aggregate` tone/sentiment closure was lifted to a module-level `_aggregate_tone(rows, scores_by_row)` so both a theme's own numbers and each of its sub-themes' numbers go through the exact same aggregation code, not a copy of it.
- **New route, same ownership/pagination code as the existing one, not a parallel implementation**: `GET .../themes/{tid}/sub-themes/{index}/answers` reuses a new `_answers_page(ds, db, column, refs, limit, offset)` helper extracted from what used to be `theme_answers`'s own inline body (`theme_answers` itself now calls the same helper - its own behaviour is unchanged, confirmed by leaving every existing `test_api_themes.py` assertion in place). An out-of-range `index`, or a theme whose `sub_themes` is `[]`/`None`, is a 404 ("Sub-theme not found."), not a 500 or an empty-but-200 page.
- **`_theme_dict`'s `sub_themes` field never carries `answer_refs`** - `size_pct` is computed on the SAME basis as the parent theme's own `size_pct` (`% of all answered`, i.e. `total` = the whole column's answer count, not the parent theme's own size) - matching decision 7's "share is of all answered, not of the parent" convention that `app.chart_data.SubTheme.share` already documents. Drilling into a sub-theme's real answers is `GET .../sub-themes/{index}/answers` only, mirroring how a parent theme's own `answer_refs` is never in its list-view dict either.
- **`app/findings.py::theme_nodes` needed NO signature change** (see the JSON-column reasoning above) - its inner `_node()` now builds `children` from `t.sub_themes`, capped to 3 and filtered to `share > 0` computed AFTER rounding (not `size > 0` before rounding - `size` is always positive for anything actually stored; the real crash risk the plan's design review flagged is a computed SHARE that rounds to exactly `0.0` on a very large dataset, which would still divide-by-zero in `squarify`). This is a second, independent guard on top of `subthemes.py`'s own count/coverage gates at the clustering step, not a duplicate of them - the two guards protect different things (which parents get sub-themes stored at all, vs. what any single caller's specific `total_answered` denominator does to one sub-theme's rounded share).
- **`_build_overview`'s stat note is now a real count, not "(no sub-themes yet)"**: `sum(len(n.children) for n in real_nodes)` renders as `"(N sub-themes)"` when `N > 0`, else `"(no sub-themes)"` - dropping "yet" deliberately, since a theme genuinely not qualifying (too small, ranked 8th+, gated out) is not a "not built yet" situation any more now that the feature is real.
- **Sunburst/icicle remain unwired, unchanged, on purpose (decision 11, explicitly out of scope for this stream)**: `pick_chart`/`CHART_BY_KIND` still never select sunburst or icicle for any finding kind, real sub-themes or not - SPEC.md section 4's "skip when fewer than 3 sub-themes in total, use treemap" row's own threshold check was never wired into `pick_chart` and still isn't; a comment was added directly above `CHART_BY_KIND` flagging this as real, scoped follow-up work, not an oversight.
- **Future theme editing will need to touch `sub_themes` too, flagged here for whoever builds it**: SPEC.md section 5's rename/merge/split theme-editing UI does not exist yet (CLAUDE.md's own task list confirms this is still unbuilt). Whenever it is built, renaming a parent theme has no effect on its `sub_themes` JSON (fine, no coupling there), but MERGING or SPLITTING a theme changes which answers belong to it - that code will need to explicitly clear or recompute the merged/split theme's own `sub_themes` (most simply: set it back to `[]` and let the next full rebuild repopulate it, rather than trying to incrementally patch stale sub-theme `answer_refs`/sizes that no longer match the edited theme's real membership). Not built here; documented so it isn't silently missed later.
- **Empirically tuned, not just unit-tested**: proving `sub_cluster_themes` actually recovers a real nested split end to end (not just that the pure clustering logic behaves correctly on a hand-built `ClusterResult`, which S1's own tests already cover) needed a bigger, family-clustered synthetic fixture than `FakeEmbeddingClient`'s bag-of-words hash can reliably produce at this dataset size (confirmed directly: the hash-based fake could not be tuned to keep 3 sub-groups merged into one 100+-answer top-level cluster while still being separable by a SECOND, independent UMAP fit on just that subset - tried first, abandoned). `tests/test_api_themes.py`'s new end-to-end job test instead uses a small numpy-built fixture (3 sub-group centers, a small shared perturbation from one base direction, substantial per-dimension noise, 300 dimensions - the same style as this file's 2026-09-27 `_high_dimensional_fixture`) fed through a `FakeEmbeddingClient`-shaped fake that maps each exact masked text to a precomputed vector by dict lookup rather than hashing it. The exact working parameters (`sub_delta_scale=0.05`, per-member noise `0.15`, group sizes 45/45/40 plus a 35-answer unrelated second theme) were found by directly scripting `app.text_pipeline.clustering.cluster_answers`/`app.text_pipeline.subthemes.sub_cluster_themes` against a parameter sweep in this environment (not guessed) - the recovered top-level cluster (131 members, 130 real) splits into 3 sub-clusters of 41/40/39 answers, each dominated by ONE true sub-group, and covering 100% of the parent - comfortably clearing every one of `subthemes.py`'s own gates (>=2 kept, >=50% coverage).

## 2026-09-29 (fluid-width report charts: genuine layout reflow, not a zoom)
- **The problem, and a first attempt that was explicitly rejected**: charts on `/report` stayed at a fixed pixel width regardless of screen size - confirmed live on the production deployment at a 2200px viewport, where `.page`'s 960px cap and each chart's own 1180px-designed markup meant a chart never grew to use extra width on a wide screen. A first fix wrapped the whole rendered chart fragment in a CSS `transform: scale()` in `ThemeChart.tsx` - uniformly zooming text and shapes together to fill available width. It was implemented, tested, and shipped, then **explicitly rejected and reverted** (`git revert`, commit `5bf595d`): the actual ask was narrower/harder than "not static" - the chart's own LAYOUT should genuinely reflow (wider bars, more breathing room, more visible content), while text stays a literal, fixed size matching the report page's own typography. A uniform zoom does the opposite of that for text.
- **Central technical finding, verified empirically before designing around it, not assumed**: SVG `<text>` with an explicit pixel `font-size` scales identically with its ambient `viewBox` when that `viewBox` is stretched by CSS (confirmed via a live before/after `getBoundingClientRect()` measurement: a 3x viewBox stretch produced 3x text growth) - and `<foreignObject>` containing real HTML text is **also** subject to that same transform, so it does not escape it either. The only way to get "shapes fluid, text literally fixed" is to keep every text node entirely outside any viewBox-scaled coordinate system: either draw a chart in plain HTML/CSS with text in normal flow, or, for genuinely curved geometry, keep a shapes-only SVG (no text inside it at all) and layer every label as a sibling, absolutely-positioned HTML element on top, positioned by `%` of the chart's own fixed design width/height.
- **Scope: the 8 real report chart ids**, not all 20 registered `FRAMES` functions - `overview`, `treemap`, `rank`, `sentsun`, `heatmap`, `byScore`, `quality`, and `trend` (confirmed `trend` is genuinely reachable via `app/findings.py`'s `CHART_BY_KIND["trend_shift"] = "trend"`, not dead - `pick_chart`'s own docstring undersold its own dict). The other 12 (both `-mobile` variants included) stay fixed-pixel; only their `hdr()`-derived golden output changed as a side effect of the next point, not their own body logic.
- **`app/charts.py` gained a small block of shared typography constants** (`FS_HDR_TITLE=20`, `FS_HDR_SUB=14`, `FS_BODY=16`, `FS_LABEL=14`, `FS_LABEL_SM=13`, `FS_NUMBER_LG=32`), aligned to `frontend/src/report.css`'s own real values (`.rp-standout-title` is `20px/600`, `.rp-summary` is plain `16px`) and CLAUDE.md's stated "Body 16px/1.55" rule, rather than each chart inventing its own independent sizes. `hdr()` (the title/subtitle block called by 19 of the 20 registered chart functions, 12 directly and 7 more via `frame()`, which calls `hdr()` internally - only `f_context` never does) moved from its old independent `22px`/`15px` to these shared constants, which is why 19 of 20 golden files changed even though only 8 charts' own bodies were rewritten - a known, deliberate, reviewed blast radius, not a mistake.
- **Per-chart technique, chosen per shape, not one mechanism for everything**: `rank`/`heatmap`/`byScore` were already flex/grid-based HTML with no SVG - their one fixed-px reference dimension (a 560px bar-width divisor, a 250px grid column, a 700px bar row) became a `%`/`clamp()`/`minmax()` value instead. `byScore` additionally needed a real **CSS container query** (`container-type: inline-size` on each segment, `@container (min-width:Npx)`) to replace its old server-side "does the theme name fit" pixel guess, since that guess assumed a fixed 700px reference that no longer exists once the row is fluid - both label variants are always emitted, the query picks which is visible at the segment's real final width. `quality`'s histogram dropped its `<svg>` entirely (simple axis-aligned bars, no curve, no reason to keep SVG) for the same CSS-flex-bar pattern. `treemap`/`treemap_html` (renamed from `treemap_svg` - it draws zero SVG now) converts every `squarify()` rect (already a fully proportional algorithm, needed zero code change) to a `position:absolute` HTML `%`-positioned div with `container-type: inline-size` and the same full/short label-swap pattern as `byScore`; `f_overview` inherits this for free since it just embeds the same call. `trend` and `sentsun` are the two genuinely hard cases (real coordinate/polar geometry) - both keep a shapes-only SVG (`preserveAspectRatio="none"` so a fixed-height/fluid-width box stretches correctly) and move every label to a sibling `chart_label()`/`arc_label()` HTML div, positioned by `%` + (for `sentsun`'s arc labels) a `rotate()` transform matching the original SVG group's own rotation. `arc_label()`'s "does this label fit its wedge" decision did **not** need to change at all - it's computed in the chart's own fixed design-coordinate space (angles/radii), which stays a stable reference regardless of final rendered pixel size; only its *output* moved from an SVG `<text>` group to an HTML div.
- **A real bug found and fixed during this work, not by a test**: `treemap_html`'s "full" label variant needs `display:-webkit-box` inline (required for `-webkit-line-clamp` to 2-line-wrap long names) - and an inline `style` attribute always wins over a plain stylesheet rule regardless of which `@container` query matched, so the intended "hidden by default, shown when the container query matches" toggle silently failed: both the full and short label were rendering stacked on top of each other on every narrow cell. Caught by live-browser inspection (`getComputedStyle` on a specific narrow cell showed both variants' `display` as visible), not by any automated test - fixed by moving `display` control entirely into the stylesheet rules with `!important` on both the default-hidden and container-matched states, removing `display` from the label's own inline style. `byScore`'s equivalent toggle never had this bug (its own inline styles never set `display` at all).
- **No `render_parts`/API contract change** - every chart is fluid via CSS/SVG relative units and container queries alone, with the *same* server-rendered markup correct at any client width. The one necessary frontend change: `ThemeChart.tsx`'s wrapper went from forcing `width: fragment.chart_width` to `width: '100%', maxWidth: fragment.chart_width` (the server's returned width is now a **design cap**, never forced), and `frontend/src/report.css` gained a `@media (min-width: 960px)` rule letting `.rp-chart-scroll` grow past `.page`'s normal 960px reading column (with every other text element on the page untouched) - without this, `.rp-chart`'s own `max-width:100%` would just fill `.page`'s capped ~928px box on any screen, and none of the fluid-layout work above would ever become visible. `render()`'s own standalone-document wrapper (used only by the internal `/frame/{id}` design-review gallery) was deliberately left untouched - editing it would force all 20 golden files to regenerate regardless of which chart bodies actually changed, for a dev-only nicety; fluidity was verified against the real `/report` page's own markup instead.
- **Known rough edge, since fixed (2026-09-29, follow-up)**: `treemap_html`'s sub-theme cells originally had no full/short label-swap - they always rendered name+percentage, clipped by `overflow:hidden` if the cell was too small, which could look crowded at a narrow rendered width (never broke layout, just harder to read than it should be). Fixed by giving each sub-cell the exact same mechanism as its parent cell: two label variants (`{scls}f`/`{scls}s`, `scls = f"tms{idx}_{k}"` - unique per parent x sub-theme pair), `container-type: inline-size` on the sub-cell's own box (CSS containment nests correctly, so the `@container` query binds to that sub-cell, not its parent), and the same `!important`-on-both-states discipline the display-toggle bug fix above established (neither variant's inline `style` sets `display`). `tests/test_charts_data.py::test_treemap_html_sub_cells_have_their_own_label_swap_fallback` pins this using `small_report()`'s existing "Zebra crossing" theme, which already has a real sub-theme in its fixture data. Verified live in a real browser at the same narrow width that originally showed the crowded text, confirmed clean at both that width and the normal/wide case.
- **Verified live in a real browser at every step, not just via tests**: each of the 8 charts was checked by fetching a real rendered fragment (either from a real built dataset via the local dev API, or the built-in fixture data via `render_parts`) into a standalone repro page using `ThemeChart.tsx`'s exact wrapper markup and `report.css`'s exact rules, then resizing/forcing container widths and inspecting computed styles directly - confirming text stayed a constant pixel size while layout genuinely reflowed, for `rank`, `treemap` (including the display-toggle bug above), `trend`, and `sentsun` specifically.

## 2026-09-29 (treemap labels: height-derived line count replaces the container-query toggle)
- **The previous entry's sub-cell container-query fix (above) was itself replaced, same day, after comparing against the original design prototype.** Reading `verbatim-visual-system/project/treemap.dc.html` directly (the actual prototype the treemap's visual design comes from) showed it always shows a cell's name, wrapped across as many lines as its height allows (a 72.8px-wide, 133.2px-tall cell wraps "Hybrid or petrol is enough" across 5 lines) - it only drops to a bare number when a cell is too short for even one line. The container-query full/short toggle (both the original top-level version and the just-added sub-cell version) instead hard-capped every label at 2 lines and fell back to a percent-only sibling element below a width threshold, so many cells that could easily fit a wrapped name lost it entirely - confirmed live on the Railway deployment after rebuilding a dataset with real sub-themes (see below).
- **The fix, and why it's simpler rather than more complex**: `treemap_html`'s own docstring already states the design's HEIGHT never changes with viewport width - only WIDTH is fluid. That means the true number of lines that fit in any cell is fully computable server-side from its own known height (`rh` for a top-level cell, `sh` for a sub-cell - both already in the fixed 580px design-height reference frame the browser actually renders at), while WIDTH-wise wrapping can be left entirely to the browser's own natural text flow, which adapts correctly to whatever width the cell ends up at with no server-side guess at all. `-webkit-line-clamp` is now set per-cell to `max(1, int(avail_h // line_h))` instead of a fixed `2` - no `needed_w` character-count estimate, no `{cls}f`/`{cls}s` element pair, no `@container` rule, no `css_rules` list, no `<style>` tag, and no `container-type: inline-size` (nothing queries it any more) anywhere in the function.
- **A top-level cell's available height respects the sub-theme header boundary when sub-cells actually render**: sub-cells always start at `top: {header_pct}%` (34% of the parent's own height) regardless of how tall its label rendered, so `avail_h` is computed against `rh * header_pct / 100` (not the full `rh`) whenever `sub_html` ends up non-empty - checked against the *actual* rendered state (after the existing `sub_w > 20 and sub_h > 20` gate), not just whether `subs` is non-empty, since sub-cells might not end up rendering at all. Without this, a tall cell with sub-themes could compute far more lines than the reserved header area actually has room for, visually colliding with (rendering behind) its own sub-cells.
- **`overflow-wrap: break-word` added defensively** on both label levels, new because the old server-side pixel-wrap never needed it (it pre-computed exact line breaks) - protects against a single unusually long word overflowing a very narrow cell, not just a long phrase. **The percentage now renders in its own bold span** (`font-weight:600`) within a lighter-weight name (`font-weight:500`), matching the prototype's visual hierarchy more closely than the previous uniform-weight text - a deliberate small improvement made while already touching this code, confirmed against the prototype's own screenshot.
- **`overflow:hidden` on both cell levels' wrapper divs is unchanged** - still the outer safety net guaranteeing a label can never bleed into a sibling cell, even though `-webkit-line-clamp`'s own ellipsis-on-truncation makes hitting that limit rare now.
- **Verified live against the real Railway deployment**, not just locally: earlier the same day, a report on that deployment had zero sub-themes stored (built before sub-theme clustering existed) - rebuilding themes on it produced real sub-themes, which is what first exposed the container-query approach's over-aggressive fallback (many sub-cells showing only a bare percentage even though their cell was clearly tall enough for a wrapped name). After this fix, the same real fragment (fetched from the local dev API for the equivalent locally-tested dataset, embedded in a repro page using `ThemeChart.tsx`'s exact wrapper markup) shows every previously percent-only cell's real name again, wrapped and bold-percentage-suffixed, at both normal and a stress-tested narrow width, with clean ellipsis truncation and no overflow into sibling cells.

## 2026-09-30 (theme-axis mixing: a consistent naming axis, real cluster merging, two related bugs)
- **The problem**: on the Women's Clothing E-Commerce Reviews dataset (the same one that exposed the
  2026-09-27 "96% noise" HDBSCAN bug, and whose UMAP fix was never re-verified end-to-end against it
  until now), top-level themes mixed two inconsistent dimensions - some named after product categories
  ("Dress fit, fabric, and design details"), others after feedback topics - scattering "fit" across many
  differently-named themes and leaving 37.9% in "Other". Root cause, confirmed by reading every relevant
  file directly: nothing in `embeddings.py` (raw Voyage embeddings, no task framing) or `clustering.py`
  (pure unsupervised HDBSCAN+UMAP) steers clustering toward a consistent axis, and `labeling.py`'s
  cluster-naming prompt gave Claude no instruction to keep one axis - even though `label_clusters` already
  sends every cluster's samples in one batched call, so Claude already had everything needed to
  self-correct, it just was never told to. Confirmed separately that the app already correctly keeps
  category-like columns (e.g. "Division Name") out of clustering entirely via the existing `segment`
  column role (`app/profiling/columns.py`, `app/text_pipeline/pipeline.py`) - the bug was never
  architectural leakage, just open-text clustering independently rediscovering entity structure from the
  review text's own vocabulary.
- **A second finding changed the shape of the fix**: Claude's labeling reply already includes
  `merge_with` (clusters it thinks are really the same theme) - confirmed via `grep -rn "merge_with"
  app/*.py` that it was parsed, validated, and never consumed anywhere downstream. Same for `note`. Both
  were fully dead data. New module `app/text_pipeline/merging.py` (`merge_groups`, `apply_merges`,
  `apply_sub_merges`) actually consolidates flagged clusters - Union-Find over `merge_with` treated as
  undirected edges (one side flagging is enough; under-merging is worse than over-merging here, a
  deliberate choice), no new LLM call (a merged theme's label/description/note are inherited from the
  LARGEST original cluster in the group, matching `CLAUDE.md`'s cheap-first principle). Wired into
  `app/api_themes.py::build_themes`'s `_work` right after `label_clusters`/`label_sub_clusters` respectively,
  before either cluster shape is used again, so sub-clustering and storage both see the merged result with
  zero changes needed at either call site. Sub-cluster merging is scoped to `merge_groups`/`_merge_one_level`
  run independently within each parent's own sub-cluster list (never across parents - structurally
  impossible, not just prompted against), and re-applies `subthemes.py`'s own "≥2 surviving groups" gate
  post-merge, dropping a parent's sub-themes entirely if merging leaves fewer than 2.
- **Two related, independently-confirmed problems, included in the same pass at the user's request**:
  `MIN_SUBTHEME_COVERAGE=0.50` (documented, intentional - a parent's sub-themes only need to cover ≥50%
  of its answers) meant `treemap_html`'s sub-cells could visually imply full coverage when only half was
  real, since `squarify()` always fills 100% of the reserved sub-area regardless - fixed by appending a
  synthetic `("__remainder__", ...)` entry to `subs` before squarify when the gap exceeds 0.5 points,
  rendered muted (`color-mix(in srgb, var(--muted) 18%, var(--surface))`, never a `--t1..--t7` tint) with
  its own "N% not in a sub-theme" label. Required a matching fix to the sub-cell loop's `MIX[k]` indexing
  (`MIX = [46, 36, 27]`, exactly 3 elements) - a naive 4th synthetic entry on a theme with the max 3 real
  sub-themes would have raised `IndexError` without an explicit `sn == "__remainder__"` branch that skips
  the `MIX` lookup entirely, caught and pinned by a dedicated regression test before it could ship. Also
  fixed `frontend/src/ThemeDetail.tsx`'s "N% fit no sub-theme" line, which used `100 - sum(sub_themes
  size_pct)` when both a theme's and its sub-themes' `size_pct` are "% of ALL answered" (confirmed in
  `app/api_themes.py::_theme_dict` and `app/chart_data.py`'s own docstring) - the correct remainder is
  `theme.size_pct - sum(...)`, not `100 - sum(...)`; wrong in production whenever a theme's own share
  wasn't near 100%, i.e. almost always. Existing test fixtures encoded the old wrong mental model (sub-theme
  shares summing near 100 against a ~26% parent, which can't happen with real data) and were corrected.
- **"Measure, don't assume" caught two real problems a prompt-writing pass alone would not have**, both
  found by rebuilding themes for real against the same dataset that exposed the original bug (not a
  synthetic fixture): (1) `merge_with` alone was insufficient - Claude reliably named many clusters
  IDENTICALLY along the new consistent axis (10 of 13 themes all literally "Fit and sizing") without
  exhaustively cross-referencing all of them against each other via `merge_with`, leaving confusing
  duplicate-labeled boxes instead of one consolidated theme. Fixed by having `_merge_one_level` also treat
  two clusters sharing the exact same label (case/whitespace-insensitive) as an implicit merge edge,
  independent of `merge_with` - a same-labeled pair is useless to show separately regardless of why Claude
  didn't cross-reference it. (2) The first fix for (1), combined with the SYSTEM prompt's original "prefer
  merging when in doubt" wording, then over-corrected: a second real rebuild collapsed 74.4% of the
  dataset into ONE "Fit and sizing" super-theme, swallowing genuinely distinct aspects (fabric quality,
  durability, style) that happened to be fit-adjacent. Fixed by recalibrating the SYSTEM prompt: replaced
  "prefer merging when in doubt" with explicit criteria (only merge when a one-sentence summary of both
  clusters would genuinely be the same sentence; fit, fabric quality, durability, value, and style are
  each their OWN aspect even when one review mentions several) and the equivalent tightening of the
  `merge_with` instruction. A third real rebuild after this produced 6 genuinely distinct, axis-consistent
  themes (Fit and sizing 70.1%, Other 25.6%, Versatility and style 2.2%, Fabric care and durability 1.1%,
  Fabric quality 0.7%, Fabric opacity and transparency 0.3%) with real, specific sub-themes under the
  dominant theme (e.g. "Oversized and roomy sizing", "Fitted torso with selective sizing considerations",
  "Intentionally oversized silhouette") - no entity mixing, no duplicate names, real differentiation
  preserved. "Fit and sizing"'s continued dominance (~70%) is treated as a legitimate finding about this
  specific dataset (correctly consolidating what was previously fragmented by garment type), not
  evidence of remaining over-merging, since the surviving themes are genuinely distinct aspects, not
  near-duplicates.
- **"Other" (25.6%, 5803 answers) stayed IDENTICAL across all three real rebuilds** (10-theme,
  2-theme-collapsed, and final 6-theme runs) - direct, repeated confirmation that "Other" bucket size is
  governed entirely by `clustering.py`'s HDBSCAN density/min-cluster-size noise decisions, a separate
  mechanism from axis-mixing/labeling, exactly as predicted during planning. Not addressed in this pass -
  flagged as real, separate follow-up work if the "Other" percentage itself needs to come down, not
  something a labeling-prompt change can move.
- **New tests**: `tests/test_text_pipeline_merging.py` (pure graph-logic unit tests, no network - 18
  cases covering `merge_groups`'s Union-Find semantics, `apply_merges`/`apply_sub_merges`'s member/size
  consolidation, label inheritance, id renumbering, the same-label merge safety net and its
  case/whitespace-insensitivity, Other exclusion, cross-parent isolation, and the below-2-groups drop
  gate); `tests/test_api_themes.py` gained two real end-to-end job tests (one forcing a top-level merge
  via a custom fake Claude reply asserting every cluster merges into one stored `Theme` row, one forcing a
  sub-cluster merge under the existing big-fixture machinery); `tests/test_charts_data.py` gained the
  remainder-cell tests described above; `frontend/src/ThemeDetail.test.tsx` gained a case with a small
  sub-theme share against a small parent share, the realistic shape the old formula got wrong.

## 2026-09-30 (rank-8+ themes merge into "Other" upstream, in theme_nodes())
- Real bug on a real dataset (>7 real themes): `_theme_color`'s 7-token palette fallback meant every real
  theme ranked 8th or beyond got the same generic "other" colour as the genuine noise cluster - several
  differently-named `ThemeNode`s all rendering as one indistinguishable grey blob in every chart, some too
  thin for `arc_label()` (`app/charts.py`) to fit any text in at all.
- Given a choice between a narrow chart-level fix (only `f_sentsun`/`f_byscore` merge their own rank-8+
  rows) and an upstream fix (merge once, in `app.findings.theme_nodes()`, so every consumer sees the same
  already-merged list), the user explicitly chose upstream, overriding the narrower recommendation.
- Investigating upstream surfaced a real correctness gap before implementing: `build_score_data`/
  `build_segment_data`/`build_trend_data` and the segment-skew/score-correlation/trend-shift finding
  candidates all resolved a `ThemeNode` back to its source `Theme` row via `_themes_by_label()`, a
  `{Theme.label: Theme}` dict keyed off the RAW unmerged rows - relying on a "node name always equals one
  real Theme.label" invariant that a genuine upstream merge would break (a merged node's name would
  resolve to only one of several folded rows' `answer_refs`, silently undercounting every downstream
  cross-tab for that bucket). Reported to the user before implementing; confirmed proceeding with the
  full fix rather than the narrower one.
- Fix: `ThemeNode` (`app/chart_data.py`) gained `answer_refs: list[int]` and `theme_id: int | None`.
  `theme_nodes()` now keeps only the top 7 real themes as their own node; every real theme ranked 8th+,
  plus the genuine noise cluster (whichever are present), fold into ONE new node via `_merge_into_other`
  (summed count/share, count-weighted sentiment/tone, unioned `answer_refs`, `theme_id` staying a real id
  only when exactly one theme is folded - byte-compatible with the common <=7-real-themes case).
  `build_score_data`/`build_segment_data`/`build_trend_data` now read `node.answer_refs`/`node.sentiment`
  directly instead of bridging through `_themes_by_label`, which is now deleted; the three candidate
  functions resolve `Candidate.theme_id` from `ThemeNode.theme_id` the same way (`None` for a genuinely
  merged bucket - already a pre-existing, already-handled case in the frontend, which types
  `Finding.theme_id` as `number | null` and gates the "See answers" link on it being non-null).
- Verified live against a real stored dataset with 11 real themes + noise (`Amazon_reviews.csv`,
  1,597 answered): `theme_nodes()` now returns exactly 8 nodes (7 real + 1 merged "Other", 469 answers,
  29.4% share, `theme_id=None`); rendered `byScore`/`sentsun` HTML shows exactly 8 legend entries, one per
  colour token, with none of the folded-in real themes' names leaking into the chart; the merged answer_refs
  union exactly equals the raw themes' union (1,597 of 1,597, no overlap, no undercount). A second, <=7-real-
  theme dataset (`Womens Clothing E-Commerce Reviews.csv`) was confirmed unaffected: 6 nodes, unchanged,
  each keeping its own real `theme_id`.

## 2026-09-30 (finer HDBSCAN floor: why the merge step was dropped, and what actually fixed "Other")
- Real complaint: many open-ended answers land in "Other" even though they read as clearly belonging to
  an existing theme. Investigated empirically (not by inspection) against `Amazon_reviews.csv` (1,597
  answers, then 11 real themes + 298/18.7% Other): measured every noise answer's distance to its nearest
  real cluster's centroid - only 5% were anywhere near an existing theme's typical radius, ruling out
  "soft-reassign noise to what already exists" as the fix. Re-clustering the noise ON ITS OWN with a finer
  floor found 15 coherent new groups covering 92% of it (real near-duplicate review clusters, e.g. a
  repeated "Fire HD 8 first impressions from a retired IT professional" review and a repeated "$99 tablet
  vs. my iPad" review) - genuine small themes that never had a chance because `adaptive_min_cluster_size`
  (`round(n/50)`, 32 for this dataset) is sized for the WHOLE dataset, not for how many distinct small
  topics exist in it.
- First attempt (planned and initially approved): lower `min_cluster_size` for a first HDBSCAN pass, then
  re-consolidate fragments with a new embedding-space agglomerative merge step (`AgglomerativeClustering`
  on fine-cluster centroids, percentile-based distance threshold). Both halves were needed in that design
  because a bare floor-lowering, tested first, fragmented the biggest existing cluster ("Alexa smart
  speaker satisfaction," 651 answers) into pieces as small as 135 for only an 18.7%->16.6% Other
  improvement - a wash.
- That design was built, tested, and then DROPPED after its own test caught a real problem: on a
  synthetic fixture of 3 known, distinct groups, the merge step merged two of them together. Confirmed
  independently on the real dataset too - it took the clean 651-member cluster and glued ~386 unrelated
  answers from several other clusters onto it (651 -> 1,037). Every linkage method (average/complete/ward)
  and every percentile tried did the same thing on both datasets: a percentile-based threshold over a
  small, unevenly-spaced set of cluster centroids has no principled way to tell "these two are really the
  same topic" from "these two just happen to be the closest pair available."
- Root-caused the ORIGINAL fragmentation problem while debugging the merge step's failure, and found the
  fix was elsewhere: HDBSCAN's `min_samples` (density strictness) was being scaled down TOGETHER with the
  finer `min_cluster_size` (`adaptive_min_samples`'s existing coupling) - lowering the SIZE floor was also
  loosening the DENSITY requirement, and it was the loosened density that let borderline points bleed
  across real topic boundaries and let already-dense regions fragment. Decoupling them - `cluster_answers`
  now takes a `finer_floor: bool` that lowers `min_cluster_size` (via new `adaptive_fine_min_cluster_size`,
  `FINE_ADAPTIVE_DIVISOR=100`, ~1% of answers) but derives `min_samples` from what the STANDARD floor would
  have been, never the finer one - solved both problems at once with no merge step needed at all: on the
  same real dataset, 21 clusters (up from 11), Other 18.7% -> 10.1%, the "Alexa" cluster stayed fully
  intact at 651 (zero fragmentation), and both real near-duplicate-review groups found during diagnosis
  now surface as their own correctly-sized themes.
- Considered (and rejected) using TypeSafe/Jev (`app/text_pipeline/jev_sentiment.py`) for the
  cluster-consolidation judgment instead of embedding distance: its docs (`docs.typesafe.ai`) confirm it
  offers only per-state structured-question primitives (Choice/Score/Noul), no embeddings or similarity/
  clustering capability, and its cost/latency profile is built for high-volume per-row classification
  (thousands of calls) - the opposite shape of this low-volume, one-batched-judgment task. This matches
  and reconfirms this file's own 2026-09-25 Jev-trial entry, which already scoped Jev to sentiment only
  and explicitly declined to extend it to theme merge/split flags for exactly this reason.
- Any genuine "these two of the ~20 real clusters are actually the same topic" consolidation is left to
  the pipeline's existing, already-shipped Claude-based mechanism (`labeling.py`'s `merge_with` + same-
  label matching, applied by `merging.py`, from the 2026-09-30 theme-axis-mixing entry above) - a
  one-batched-call judgment task Claude is already positioned for, not a new mechanism.
- `finer_floor=True` only applies to `pipeline.embed_and_cluster_with_vectors`'s top-level clustering call;
  `subthemes.py`'s own sub-theme pass is untouched (`finer_floor` defaults to `False`), deliberately kept
  out of scope. Verified live via the real `/api/datasets/{id}/themes/build` endpoint (not just isolated
  diagnostic scripts) on `Amazon_reviews.csv`: matches every isolated-diagnostic number above, with real
  Claude labeling completing normally on 21 clusters in one batched call. A second, much larger real
  dataset (`Womens Clothing E-Commerce Reviews.csv`, 22,641 answers) was confirmed unaffected by
  construction, not just by testing: at that scale both `adaptive_fine_min_cluster_size` and
  `adaptive_min_cluster_size` clamp to the same ceiling (50), and `min_samples` derives identically either
  way, so `finer_floor=True` is a provable no-op there.

## 2026-09-30 (adaptive column-kind detection + adaptive score/segment/date column selection)
- User reported a `categories` column's report looked broken (redundant/overlapping theme labels, no
  sub-themes ever forming, no amount of rebuilding fixed it). Root-caused via live investigation on the
  deployed dataset, not by inspection: `categories` isn't free text at all - it's per-product metadata
  repeated once per review of that product (1,597 rows, only **19 distinct exact strings** - 98.8% of
  rows are one of 19 exact category-breadcrumb strings). It got auto-classified `open_text` and run
  through embed+cluster theme discovery, which can only ever rediscover those 19 near-duplicate strings
  and has nothing left to sub-split once a "theme" is hundreds of copies of one identical string.
- Root cause in `app/profiling/columns.py`: segment detection had a **fixed absolute cap of 12 distinct
  values** (`2 <= distinct <= 12 and distinct <= 0.5*n`), blind to dataset scale; a 1,597-row column with
  19 distinct, heavily-repeated values (ratio 1.2%) failed that cap on a technicality and fell through to
  `open_text`, which has no uniqueness gate on the *kind* itself (only on confidence) - a real gap against
  `SPEC.md` section 3's own stated open-text rule ("mostly unique values"), left unaddressed this pass
  (see below).
- User's explicit direction, chosen over the narrower single-column fix: build real per-dataset
  adaptivity into how the report decides which column plays which role, not a fixed rule that assumes
  every dataset looks the same. Two parallel Explore agents mapped the existing machinery before
  designing anything, finding: the cross-tab machinery this bug actually needed (heatmap,
  `segment_skew_candidates` cross-tabbing a `segment` column against theme membership) already exists and
  works unconditionally for any confirmed segment column - no new correlation engine was needed, the
  column was just mis-typed at the one place that decides its role; `pick_structured_columns`/`pick_chart`
  are both pure static, zero-data-awareness lookups (first confirmed column of a kind in upload order,
  full stop); `SPEC.md` section 4's much richer ranked/adaptive multi-chart-candidate vision is
  already-documented, deliberate, out-of-scope follow-up work ("decision 11") - not attempted here, several
  of its chart types have no renderer at all yet; `numeric`/`yes_no` column roles are SPEC'd but never
  consumed anywhere in the report pipeline - a real, separate gap, also not touched this pass.
- **Part A** - `_segment_max_distinct(n)` (`app/profiling/columns.py`): the segment ceiling now scales
  with row count (`max(12, min(30, round(n/80)))`) instead of staying fixed at 12 - floor 12 unchanged for
  every dataset under ~960 rows (byte-identical to before), ceiling 30 for very large datasets. Verified
  directly against the real `categories` column data (pulled from the actual dataset via `_load_clean_df`):
  now classifies `segment` (`distinct=19`, ceiling for n=1,597 is `round(1597/80)=20`), confidence 0.7,
  reason "19 different answers repeated across rows, so it can split the answers into groups."
  Deliberately not touched: `open_text`'s own kind decision still doesn't gate on uniqueness (SPEC.md's
  own stated rule) - a column with too many distinct-but-still-repetitive values to clear even the new
  30-ceiling would still fall through to `open_text` today. Named, not fixed - no case needing it has been
  observed yet.
- **Part B** - `pick_structured_columns` (`app/findings_structured.py`) now returns every confirmed,
  non-off candidate per kind (`dict[str, list[str]]`, still position-ordered), not just the first;
  `build_structured_context`'s score/segment/date blocks each try their kind's candidates in turn and keep
  the first one whose `build_*_data` call actually returns non-`None`, instead of committing to upload-
  column-order regardless of whether that specific column's data survives suppression. A second confirmed
  column of the same kind is no longer silently unreachable if the first one produces nothing.
- **Real limitation flagged to the user directly**: column profiling runs exactly once, at upload time
  (`app/api_upload.py:179`), never recomputed - Part A only prevents this for *future* uploads, it does
  not retroactively fix an already-uploaded, already-confirmed column. For the existing `categories`
  dataset, manually reclassified it live via Check Columns (Open-ended text -> Segment, confirmed via
  screenshot the selection persisted) as the already-available workaround. Discovered the same
  misclassification pattern independently affects `name`, `prices`, `dimension`, `reviews.title`, `weight`
  on this same real dataset (all "Not sure"-badged, "may be a group column" reasoning) - not reclassified,
  left for the user's own judgement since some may legitimately be open text.
- Also confirmed live: the Themes/Report flow has no UI to choose which `open_text` column becomes the
  report's subject - it auto-picks the first one in upload-column order
  (`frontend/src/Themes.tsx`'s `.find(c => kind === 'open_text' ...)`), which is `dimension` (product
  physical dimensions, not survey feedback) on this dataset now that `categories` is reclassified. Getting
  a live end-to-end report specifically on `reviews.text` would require reclassifying several unrelated
  columns first - out of scope for verifying this fix, not attempted; Parts A and B are both independently
  verified via direct real-data checks and a comprehensive test suite instead.
- New tests: `tests/test_profiling.py` (`_segment_max_distinct` bounds, a real-scale low-diversity-column
  pin reproducing the exact bug shape, a small-dataset regression pin proving the floor is unchanged);
  `tests/test_findings_structured.py` (the 3 existing `pick_structured_columns` tests updated for the new
  `list[str]` return shape, plus a new test with two confirmed segment columns where the first fails
  suppression and the second succeeds, asserting the report actually falls back to and uses the second).

## 2026-10-01 (.env was never actually loaded - VOYAGE_API_KEY/ANTHROPIC_API_KEY silently invisible unless
## the launching shell had already exported them)
- User reported Voyage API usage never showed up, despite `VOYAGE_API_KEY` sitting in `.env`. Root cause:
  `app/config.py`'s `Settings` uses pydantic-settings' own `env_file=".env"` to populate ITS OWN fields
  (`env`, `database_url`, `clerk_*`) - but that loading is private to that one model; it never writes
  anything into the process's real `os.environ`. Every other credential in this app (`VOYAGE_API_KEY`,
  `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY`, `ALLOW_DEV_USER`) is read via plain `os.environ.get(...)` in
  whichever module needs it (`embeddings.py`, `findings.py`, `jev_sentiment.py`, `app/auth.py`) - none of
  which ever saw `.env`'s values unless the shell that started uvicorn had separately, manually exported
  them first (`source .env`). `python-dotenv` was already listed in `requirements.txt` for exactly this
  reason, but `load_dotenv()` was never actually called anywhere in the app.
- Confirmed the exact failure mode directly: in a clean environment (`env -i`, nothing but `PATH`/`HOME`)
  matching what a plain `uvicorn app.main:app --reload` would see, `VOYAGE_API_KEY` was unset before the
  fix - meaning `get_embedding_client()` (`app/api_themes.py`) would hit `EmbeddingNotConfigured` and
  every "Build themes" request would fail with a clear 503 before any background work even started,
  whenever the server was launched any way other than first manually sourcing `.env`.
- Fix: `load_dotenv()` (one call, `app/main.py`, right after imports, before `get_settings()` is first
  called) - populates the REAL process environment (unlike pydantic-settings' private model-only
  loading), so every existing `os.environ.get(...)` call anywhere in the app benefits with no other module
  needing a change. Safe by construction in production: `load_dotenv()`'s default never overrides an
  already-set variable (Railway's own dashboard-configured env vars still win), and does nothing at all
  when no `.env` file exists (true on every real deploy - `.env` is git-ignored, never shipped).
- Verified directly: re-ran the same clean-environment (`env -i`) check after the fix - `VOYAGE_API_KEY`
  and `ANTHROPIC_API_KEY` are now both populated purely from importing `app.main`, no manual export
  needed. Full backend suite still green (586 passed, 1 now-skipped - `test_voyage_client_raises_without_
  api_key` correctly self-skips via its own existing, documented `skipif` once a real key is visible in
  the test process too; same 5 pre-existing unrelated auth/security failures as every other entry this
  session).

## 2026-10-01 (report-subject auto-pick: uniqueness, then answer length - no picker UI yet, but the blind
## first-in-order pick was itself a real, repeating bug)
- User hit the same symptom a third time on a real dataset, this time via the `dimension` column (product
  physical dimensions - "4.8 in x 6.6 in x 3.2 in", 100% one value, 1 theme, no sub-themes): the Report
  screen's auto-pick (`frontend/src/Themes.tsx`) chose whichever confirmed `open_text` column came FIRST
  in the spreadsheet's own upload-column order, with zero quality signal - a dataset's column order has no
  relationship to which column is actually free text, so this reliably surfaced whichever repeated-
  metadata column (categories, dimension, name, prices, ...) happened to sort earliest.
- Fix, two-step, both using signals the backend already computes per column:
  1. `pickOpenTextColumn` (new, exported, unit-tested) filters confirmed/guessed `open_text` candidates to
     those with `distinct / answered >= 0.3` ("uniqueness" - reuses the exact threshold
     `app/profiling/columns.py`'s own `open_text` confidence scoring already uses for the same signal, not
     a new number). This alone fixes the reported bug: `categories`/`name`/`prices`/`dimension` all score
     well under 0.3 on the real dataset (0.01-0.04), `reviews.text`/`reviews.title` both clear it (0.66/
     0.80).
  2. Among whatever clears that floor, prefers the LONGEST typical answer (`median_words`, a genuinely new
     field - `app/profiling/columns.py`'s `out()` now returns it for every column, not just the open_text/
     short_text branches that happened to already compute it locally for their own reason text). Needed
     because uniqueness alone doesn't reliably separate two genuinely-free-text columns: confirmed on the
     real dataset that `reviews.title` (short, varied phrases - "Great buy!", "Terrible") scores a HIGHER
     raw uniqueness ratio (0.80) than `reviews.text` itself (0.66, longer but reuses more boilerplate
     phrasing across different reviews) - without the length tie-break, the fix would have "worked" but
     still have landed on the thinner, less meaningful column.
- `median_words` was already computed internally (`profile_column`'s `wcounts`/`med_words`, used for the
  `open_text`/`short_text` kind decision and reason text) but never returned to callers - moved its
  computation to the top of `profile_column` (before any `out()` call, so every kind returns it, not just
  the branches that already happened to need it locally) rather than adding a second computation.
- Verified directly against the real dataset, twice: via the already-stored (stale, pre-fix) profile
  first - confirmed it lacks `median_words` entirely, the same "profiling runs once at upload, never
  recomputed" limitation already documented for the 2026-09-30 segment-detection fix, not a new gap; then
  via `profile_column` called fresh on the same real column data, confirming the exact real numbers quoted
  above and that the two-step pick lands on `reviews.text` - the actually-correct answer - not
  `reviews.title`.
- New tests: `tests/test_profiling.py` (unchanged - `median_words` is additive, no existing assertion
  depended on the returned dict's exact key set); `frontend/src/themes.test.tsx` (new file -
  `pickOpenTextColumn` covering: no open_text candidates, a single candidate, the real dimension-vs-
  reviews.text case, a confirmed-kind override, a switched-off column, the real reviews.title-vs-
  reviews.text length tie-break, and the floor-fallback case where nothing clears 0.3 uniqueness at all).
- Still not built (unchanged from the 2026-09-30 TODO entry): a real column-picker UI. This fix makes the
  automatic fallback meaningfully better, not a replacement for letting a user choose directly.

## 2026-10-01 (raised the default Claude model to claude-sonnet-5, and the real bug that surfaced doing it)
- User asked to try a "slightly better" Claude model. All three optional Claude steps (theme/sub-theme
  labeling `labeling.py`, a sentiment spot-check sample `sentiment.py`, column-kind refinement at upload
  `claude_hook.py`) already shared one `VERBATIM_CLAUDE_MODEL`-overridable `DEFAULT_MODEL`, defaulting to
  `claude-haiku-4-5` - none of the three are high-volume (labeling is one batched call per build
  regardless of dataset size; the other two are a small sample/once-per-upload), so raising the shared
  default one tier to `claude-sonnet-5` is cheap either way. Changed `DEFAULT_MODEL` in all three files.
- **Real regression found immediately by testing against the real API, not assumed away**: a real
  theme-build labeling call (21 clusters, a genuinely large prompt - 170,175 input tokens of representative
  answer samples) failed outright with `"Claude's reply did not contain any JSON."`. Root-caused by
  inspecting the raw API response object directly (`stop_reason`, `usage`, content block types) rather than
  guessing from the error message: `claude-sonnet-5` engaged extended thinking ADAPTIVELY for this large,
  complex prompt - `output_tokens_details.thinking_tokens` was 4096, the ENTIRE `max_tokens=4096` budget,
  leaving zero tokens for the actual reply. The single returned content block was `type: "thinking"`, not
  `"text"` - genuinely no text to parse, not a formatting problem. `claude-haiku-4-5` apparently never
  engaged this for the same prompt shape, so the bug was invisible until the model was actually raised and
  actually tested against something the size of a real dataset, not a toy prompt.
- Fix: `thinking={"type": "disabled"}` added to all three `messages.create()` calls. None of these three
  tasks are open-ended reasoning - every one already gets an explicit, prescriptive system prompt spelling
  out the exact JSON shape wanted; thinking was never useful here, only competing with the reply itself for
  the same token budget. Confirmed this does NOT break the existing "model wraps its JSON in a markdown
  code fence anyway" tolerance (`labeling.py::_extract_json`'s regex fallback, `claude_hook.py`'s matching
  `_parse_json`) - Sonnet 5 does still sometimes fence its reply even when told not to, but the existing
  fallback already handles that correctly; it was never the actual problem here, confirmed by testing the
  real extracted text through the real parser, not a standalone `json.loads`.
- Verified end to end, twice: first the real `label_clusters` function directly against the real 21-cluster
  dataset (22 labels including Other, real `merge_with` suggestions, sensible names) with `thinking`
  disabled; then a full real build-themes job through the actual API, including the separate sub-theme
  labeling call - 16 final themes, several with real sub-themes populated (2/3/3/3 - unlike the degenerate
  `categories` case from the day before, this is the REAL open-text column and sub-clustering is finding
  genuine structure), Other at 10.1% (matching the 2026-09-30 HDBSCAN fix's own verified number exactly,
  confirming the model change didn't regress clustering quality - clustering itself never touches Claude).
  Full backend suite still green throughout (586 passed, 1 skipped, same 5 pre-existing unrelated
  failures).

## 2026-10-02 (report-page "Filters": segment / score band / date range, SPEC.md section 5)
- First of the 4 "Bigger unbuilt report features" (Filters, Theme editing, Sharing & roles, Export),
  built in user-confirmed risk order. Mechanism: `GET /api/datasets/{id}/report` gains 4 optional query
  params (`segment`, `score_band`, `date_from`, `date_to`, AND'd together, one combined filter not three
  independent ones). `app.findings_structured.StructuredContext` now stashes the raw, pre-band/pre-cap
  per-row dicts behind whichever score/segment/date column won each role
  (`score_raw_by_row`/`score_scale`/`segment_raw_by_row`/`date_raw_by_row`); a new pure function
  `resolve_filter_rows` turns a filter request into a row-index `set[int]` from those dicts (reusing
  `band_score`/`apply_bands` as-is - no new banding logic). `build_structured_context` gained one
  `filter_rows` param that narrows its row universe by one line (`rows = [r for r in rows if r in
  filter_rows]`) - every downstream per-kind loop already iterated `for r in rows`, so this is the entire
  filtering mechanism for score/segment/trend, with ZERO changes to `build_score_data`/
  `build_segment_data`/`build_trend_data` themselves. `app.findings.theme_nodes` gained the matching
  `filter_rows` param: node count/share/ranking/answer_refs intersect each theme's `answer_refs` against
  `filter_rows` instead of reading `Theme.size` directly - ranking can legitimately change under a filter
  (a theme largest overall can rank lower once most of its rows are filtered out), which is correct, not
  a bug. `_render_report` always builds an UNFILTERED `StructuredContext` first (supplies
  `filter_options` - real segment group names / score bands / date min-max, taken from already-
  suppression-survived `segment.groups`/`score.bands` labels, never a fresh raw scan, so no offered
  option ever immediately collapses to "not enough data"), then only builds a second, filtered one when
  a filter param is actually present - a request with no filter params is architecturally unchanged from
  before this feature (confirmed via a dedicated regression-pin test).
- Explicit scope boundary (bounds blast radius, matches SPEC's literal "theme counts" wording): `quality`
  (answer-length histogram) and `overview.stats`'s "Responses"/"Answered" tiles stay dataset-wide always -
  they describe the whole upload, not a themed subset. Sub-theme `children` are dropped (`[]`) entirely
  while a filter is active, rather than inventing a new per-row approximation for them (no per-row record
  of a sub-theme's own membership exists to intersect against a filter, only the parent `Theme.answer_refs`
  does). Filtered sentiment reuses the exact count-weighted-average-of-the-stored-aggregate approximation
  already used for bands/periods (no per-row sentiment is persisted anywhere - 2026-09-25 entry).
- **Two real pre-existing chart-rendering bugs found and fixed by testing against a real dataset, not
  assumed away**: the Filters feature is the first thing in this codebase that can legitimately produce a
  theme (or every theme) with a genuine ZERO share/count, and three different chart functions divided by a
  sum/max/min of shares with no zero-guard, all unreachable before this feature:
  1. `app.charts.squarify` divided by `total = sum(v for _, v in items)` with no zero guard - crashed with
     `ZeroDivisionError` the moment every theme had 0 share (a filter matching zero rows entirely). Fixed:
     returns `{}` (no boxes) when `total <= 0`; `treemap_html` renders an empty box in that case instead of
     indexing into the (now possibly empty) `rects` dict.
  2. Even with a non-zero total, `squarify`'s own `worst()` divides by `min(a for _, a in row)` - a single
     *individual* zero-share theme (e.g. a filter leaves one theme with 0 matching rows while others still
     have some) still crashed it. Fixed: `treemap_html` now excludes zero-share rows from what it hands to
     `squarify` entirely (a 0%-share theme draws no box - it's simply not in this filtered view, not an
     error) rather than trying to give `squarify` a zero-area item to lay out.
  3. `app.charts.rank_rows`'s `mx = max(t.share for t in data.themes)` then `share / mx` crashed the same
     way when every theme's share was 0. Fixed: `mx = max((t.share for t in data.themes), default=0) or 1`
     - every bar computes to 0 width instead of dividing by zero.
  4. `app.charts.ramp_mix` (the segment/age heatmap's per-cell colour) divides `v / overall`; `overall` is
     a row's real overall share, which `build_segment_data`'s own docstring already documents CAN be 0 (it
     already skips a zero-overall row for its own highlight-ratio math, for the same reason) - but nothing
     skipped it for the colour-ramp math. Fixed: `ramp_mix` returns the same flat floor (`8`) `r == 0`
     already returns, instead of dividing by zero, when `overall == 0`.
  None of these were filter-specific bugs in the literal sense - they were always-latent zero-division
  risk in chart math that real data had just never managed to trigger before, because no existing feature
  could make a theme's share exactly 0 while the report still rendered at all. Found by testing every
  filter combination (segment alone, score band alone, combined, and the all-filtered-out edge case)
  against a real local dataset (`Womens Clothing E-Commerce Reviews.csv`, dataset id 2: real "Rating"
  score column, "Division Name" segment column, 5 real themes) through the real API before considering the
  feature done - not just the unit-test suite.
- Frontend: `reportApi.ts`'s `getReport(id, column, filters?)` gained an optional 4th param (every
  existing call site keeps compiling unchanged); new `ReportFilters.tsx` component (purely controlled, no
  fetch of its own - matching this app's established "control state -> `useEffect` -> refetch a whole
  section" idiom, reusing the exact shape `Themes.tsx`'s own `themesChart` effect already established);
  `Report.tsx` renders it once, right after the "Columns used" chips and before "What stands out".
- Verified live end to end via `claude-in-chrome` against the real dataset above: filter dropdowns
  populate with real segment/score-band values (not placeholders); selecting a segment visibly changes the
  treemap's own box widths (confirmed via raw HTML diff: "Fit and sizing" went from 70.10% to 57.74% width
  when filtered to the "Initmates" segment); combining two filters at once fires exactly ONE
  `GET /report?...` request (confirmed via `read_network_requests`) and zero Claude/Anthropic calls;
  "Clear filters" round-trips the report back to byte-identical original numbers. Full backend suite green
  (575 passed, 1 skipped, same pre-existing unrelated `.env`/Clerk-dependent auth/security failures) and
  full frontend suite green (62 passed) plus a clean `tsc -b && vite build`.

## 2026-10-02 (treemap: cap "Other"'s box area at 5%, stop it clipping real themes)
- User-reported, confirmed live on the real Women's Clothing dataset (id 2): "Other" at 25.6% of answers
  was getting 25.6% of the treemap's AREA too, squeezing every other real theme's box down to a sliver -
  "Versatility and style" (2.2% real share) was unreadable, several sub-theme labels clipped entirely.
  "Other" is a catch-all (rank-8+ real themes folded in, plus genuinely unclustered noise -
  `app.findings.theme_nodes`'s own merge note) and is frequently the single largest box for reasons that
  have nothing to do with it being the most informative one to look at - the real themes are the ones a
  viewer actually wants to read.
- Fix: new `app.charts._treemap_areas(rows_data) -> dict[name, area]`, called once in `treemap_html`
  right before `squarify`. When "Other"'s real share exceeds `OTHER_MAX_TREEMAP_AREA` (5.0), its AREA is
  capped at 5% and the freed area is redistributed to every other row in proportion to its own existing
  share (not evenly) - a dataset where "Other" is already <= 5% is untouched, areas equal real shares
  exactly as before this fix ("if it's less, adjust their size" = leave them alone, per the request).
  Total area is exactly conserved (only redistributed, never dropped) - verified algebraically and in
  `test_treemap_areas_caps_other_above_five_percent_and_redistributes`. The cell's own LABEL still prints
  "Other"'s real, uncapped percentage (`share`, untouched) - only the box's visual proportion changes,
  never the number reported (`test_treemap_html_other_label_still_shows_its_true_share_despite_the_area_cap`).
  Edge case: a report where EVERY row is "Other" (nothing to redistribute the freed area to) leaves it
  fully uncapped - shrinking the total represented area for no visual gain would be worse, not better.
  One function, one call site - both `f_treemap` (standalone) and `f_overview`'s hero treemap get the fix
  automatically, since both call `treemap_html`.
- Verified live via `claude-in-chrome` against the real dataset that originally showed the bug: "Other"
  now draws as a small, proportionate box in both the standalone "What are the themes?" chart and the
  overview hero chart, while "Versatility and style" and the other previously-clipped real themes now get
  genuinely readable boxes. Full backend suite green (579 passed, 1 skipped, same pre-existing unrelated
  failures), including the existing golden-frame hash tests (none needed regenerating - no existing
  fixture's "Other" share exceeded 5%, so this change is additive-only for every case tested before today).

## 2026-10-02 (treemap -> icicle: switch layout per-report when names won't fit the packed squares)
- Follow-up to the same day's "Other" area-cap fix, same user-reported root cause: the treemap's packed
  squares still clip long/numerous names even with "Other" capped, because squarify packs boxes by AREA
  in 2 dimensions - a small-share box is both short AND narrow. User supplied two design references
  (`design/screens/treemap.dc.html`, `design/screens/icicle.dc.html`) and asked for the icicle layout
  (every box gets the chart's full row height, only width varies) specifically for long names in small
  boxes, keeping the denser treemap when names are short enough to fit.
- **Not a universal swap** - a new per-report decision, `app.charts._prefers_icicle(data, w, h)`, runs the
  exact same `squarify` layout `treemap_html` itself would use (cheap, pure Python) purely to check
  whether any resulting theme or sub-theme box is too narrow for even a short fragment of its own name
  (`_too_narrow_for`, reusing `fit_label`'s own average-character-width convention). `f_treemap` and
  `f_overview` each call it with their OWN reference size (580px vs 320px tall) and pick `icicle_html` or
  `treemap_html` independently - confirmed against a real 14-theme dataset that the smaller hero chart can
  legitimately need icicle while the taller standalone chart still fits treemap; this is correct,
  size-aware behaviour, not an inconsistency to "fix."
- **New `icicle_html`**: a fluid rewrite of the layout idea the legacy, unused `f_icicle` (fixed-pixel SVG,
  one of the "3 dead chart functions" `treemap_html`'s own docstring already named) sketched - not a reuse
  of that dead code. Themes sit in one row (full chart height, width = share), sub-themes in a second row
  directly below their parent's own x-span (not the full chart width - keeps nested sub-themes correctly
  aligned under a possibly `_treemap_areas`-redistributed parent box). "Other"'s width is capped the same
  way `treemap_html`'s area is (literally the same function reused - width and area are the same thing
  once every box shares one fixed row height).
- **A real bug found and fixed by testing live, not assumed away**: the first version capped each cell's
  `-webkit-line-clamp` by HEIGHT alone. Icicle's whole point is generous height, so a genuinely narrow
  column (long name, tiny share) had room for 20-30 lines - enough for the browser to spell the ENTIRE name
  one character per line, vertically ("V" / "e" / "r" / "s" / ...), confirmed live on the real dataset that
  originally showed the bug. Fixed with a width-informed 3-tier label: full name+% only when the column fits
  at least ~6 chars/line (the same threshold `_prefers_icicle` uses to decide icicle is needed at all);
  percent-only when narrower than that but the percentage itself fits one line; nothing at all (box
  colour/size still carry information, and `data-theme` still resolves a click) when even the percentage
  wouldn't fit without wrapping character-by-character. `max_lines` is additionally capped at 6 regardless
  of available height, so a narrow column degrades via line-clamp's own ellipsis rather than an
  ever-taller stack of near-empty lines.
- Verified live via `claude-in-chrome` against the real dataset that showed the original clipping bug
  (Women's Clothing, dataset 2): both the standalone "What are the themes?" chart and the overview hero
  chart now render as icicle, "Other 25.6%" and "Fit and sizing 70.1%" read cleanly, and the several
  previously single-letter-clipped small themes now show as clean, text-free colour strips instead of
  "P...", "B", "U...". Confirmed the EV sample fixture (every golden-frame test's own data) still stays on
  treemap - its own names have enough room at the full reference size, so none of the 63 chart tests
  (15 new) needed a golden-file regeneration. Full backend suite green (594 passed, 1 skipped, same
  pre-existing unrelated failures).

## 2026-10-02 (icicle: rotate a too-narrow label, matching the design reference, instead of hiding it)
- User spotted a real gap by comparing against `design/screens/icicle.dc.html` directly: that reference
  rotates a too-narrow sub-theme's label 90° (reads bottom-to-top) rather than wrapping it horizontally or
  showing nothing - several of its own narrow columns ("Battery replacement cost 7.5%", "Current car is
  fine 5.5%") are rotated. The icicle layout shipped earlier the same day did not do this - it degraded a
  narrow column straight to percent-only or blank, losing the real name entirely in cases the reference
  design shows readable.
- Added a rotated tier to `_icicle_cell` between "horizontal wrapped name" and "percent-only/nothing": a
  new `_icicle_rotated_label` renders the name + percent as ONE unwrapped line, CSS-rotated
  `rotate(-90deg)` and centered - the icicle-layout analogue of the legacy fixed-pixel `fit_label()`'s own
  `rotated()` fallback, rebuilt as a CSS transform instead of an SVG `<g transform>`. Used when a column is
  too narrow for horizontal wrapping (<6 chars/line) but wide enough for one rotated line's own thickness
  (`box_w >= fs*1.4+6`) and tall enough for the real string length once running along the box's height
  (`len(text)*wpc <= box_h-16`, both measured, not guessed). Falls further to a rotated percent-only, then
  horizontal percent-only, then nothing, only when each tier genuinely doesn't fit - still never spells a
  name one character per line (the bug fixed earlier the same day) and still never overflows its own box.
- Verified live via `claude-in-chrome` against the real dataset: "Versatility and style 2.2%" and
  "Other 25.6%" now render as clean rotated text (previously blank strips), matching the reference design's
  own treatment of comparably narrow columns; the 2 still-narrower strips correctly stay blank (too narrow
  even for one rotated line - the reference design's own narrowest ~2% column shows no label either).
  5 new tests (67 total in this file), full backend suite green (598 passed, 1 skipped, same pre-existing
  unrelated failures), golden-frame snapshots unchanged.

## 2026-10-09 (fixed: building themes on a real 80k-row file always timed out at 300s)
- User reported build-themes consistently failing on an 80,000-row file with "Building themes took longer
  than 300 seconds and did not finish in time," across multiple retries, and suspected the earlier
  Claude-model change (2026-10-01, haiku-4-5 -> sonnet-5) was the cause.
- **Root-caused by measuring the real pipeline, not guessing**: `app.text_pipeline.embeddings.
  VoyageEmbeddingClient.embed()` ran its batches (`DEFAULT_BATCH_SIZE=128`) in a plain, strictly
  SEQUENTIAL for-loop - one HTTP round-trip at a time, waiting for each to finish before starting the
  next. Timed a single real batch call directly against the Voyage API: latency is dominated by fixed
  per-call overhead, not by how many texts are in the batch (32/128/500/1000-text batches all took
  roughly the same wall-clock time) - so the NUMBER of sequential round-trips is what matters, and an
  80,000-row file needs ~625 of them at the default batch size. **The Claude model was not the cause**:
  theme labeling is one or two BATCHED Claude calls total (cluster count, which scales far slower than row
  count via `adaptive_min_cluster_size`'s cap of 50), never one call per row - nowhere near enough extra
  latency to explain minutes of difference. A real, secondary finding while investigating: with
  `THEMES_CONCURRENCY=1` and the watchdog-marks-failed-but-cannot-actually-kill-the-thread design
  (`app/jobs.py::start_job`'s own documented behaviour), a slow build that outlives the 300s deadline
  keeps holding the one concurrency slot until the real pipeline eventually finishes in the background -
  so a retry while that zombie thread is still running correctly gets an immediate 429 ("busy"), not a
  second chance; this was not the proximate cause here (the user's screenshot showed the deadline message,
  not a 429), but is a real, related risk worth keeping in mind for very large files.
- Fix: `VoyageEmbeddingClient.embed()` now runs up to `concurrency` batches at once via a `ThreadPoolExecutor`
  (default 8, env-overridable as `VOYAGE_EMBED_CONCURRENCY`, matching `THEMES_CONCURRENCY`/
  `REPORT_CONCURRENCY`'s own convention) - real wall-clock parallelism, since Python releases the GIL
  during network I/O. Results are mapped back to their own batch's position (not completion order), so
  concurrency can never scramble which vector belongs to which text - pinned by a dedicated test using
  randomized per-batch delays specifically so batches finish out of submission order.
- **Verified against the real Voyage API, not just unit tests**: a full, real `embed()` call for 80,000
  synthetic review texts (not identical - 10 varied topics, so clustering has real structure to find) took
  **68.3 seconds** with the new concurrent client (vs. an estimated 3,000-4,000+ seconds for the old
  sequential loop at this scale, based on directly measured per-batch latency). Real `cluster_answers()` on
  the resulting 80,000 vectors took a further 71.8s (725 clusters, 487 noise - this synthetic data's
  intentional repetitiveness inflated the cluster count; a real, more diverse dataset should cluster into
  far fewer themes). Total embed+cluster: 140.1s, comfortably under the 300s deadline with real headroom
  left for the labeling step. 4 new tests (order preservation under real concurrency, single-batch
  no-pool-overhead path, retry-then-raise error propagation unchanged, and a real wall-clock proof that
  6 simulated 0.1s batches finish in well under the 0.6s a sequential loop would need). Full backend suite
  green (602 passed, 1 skipped, same pre-existing unrelated failures).

## 2026-10-09 (follow-up: the concurrency fix above still wasn't enough on real production hardware)
- User retried the same 74,681-row file (`twitter_training.csv`, dataset 11) after the concurrency fix
  deployed and it STILL failed with the same 300s deadline message, plus a Railway CPU graph showing this
  service's container briefly exceeding its own 8 vCPU plan limit (9.51 vCPU observed) around the same
  time. Investigated with real production access (`railway logs`, a `railway connect postgres --tunnel-
  only` tunnel to query the `jobs` table directly - no admin UI needed): `Job` row 51's `step` was still
  **"Turning answers into vectors"** when the watchdog killed it - the pipeline never even reached
  clustering, let alone labeling or sentiment scoring, after the full 300s+.
- **Root cause of why the earlier fix wasn't sufficient**: this service runs as a single Uvicorn worker
  process (confirmed: no `--workers` flag in the Dockerfile's `CMD`), so the 8 concurrent embedding
  threads the previous fix added are the dominant source of concurrency in that one process - each doing a
  blocking HTTP call plus parsing/constructing a sizeable JSON response into a numpy array, which is real
  CPU work, not pure idle I/O wait. On this service's actual 8 vCPU Railway plan, 8 such threads running
  at once - while the same process is also serving ordinary request traffic (confirmed in the logs: dozens
  of concurrent `GET .../jobs/51` polls from the open browser tab) - pushed container CPU briefly over its
  own limit, which Railway's cgroup enforcement throttles rather than crashes (no exception, no OOM-kill,
  no crash loop anywhere in the logs - confirmed by grepping for them) but which slows real wall-clock
  progress during the throttled periods. The combination of that throttling plus production's own real
  network latency to Voyage (not reproducible in a sandbox with different network characteristics) meant
  the embedding step alone still took longer than 300s on this specific hardware, even though the earlier
  fix's own sandbox measurement (68.3s for the same row count, unconstrained) was correct about the
  *mechanism* (concurrency beats sequential) - it just could not predict *this specific container's* real
  throughput under load.
- **Two-part fix, both verified to compile/test clean, not yet confirmed against another live production
  run (next large-file attempt will be the real proof)**:
  1. `VOYAGE_EMBED_CONCURRENCY` default lowered from 8 to 5 (`app/text_pipeline/embeddings.py`) - real
     headroom under the 8 vCPU limit for everything else the single-worker process is doing at the same
     time, at the cost of a smaller (not zero) share of the original speedup.
  2. The build-themes watchdog deadline (`app/api_themes.py`) is no longer one flat 300s for every file
     size - `_themes_deadline_for(n_answers)` adds `n_answers / THEMES_ANSWERS_PER_SECOND_FLOOR` (a
     deliberately conservative 100 answers/sec, both env-overridable) on top of the existing
     `THEMES_DEADLINE_SECONDS` floor. A 500-answer file keeps the exact 300s it always had (negligible
     scaling term); the 74,681-answer file that motivated this gets ~1,047s (~17.4 min) - real headroom
     instead of a near-certain kill partway through embedding. The route computes the scaling input as a
     cheap raw non-null count on the already-loaded `clean_df` (`clean_df[column].notna().sum()`) - no new
     masking pass, no new network/DB call. 3 new tests, including one pinning that a monkeypatched-tiny
     `THEMES_DEADLINE_SECONDS` (the existing watchdog test's own technique) still produces a near-tiny
     effective deadline, not floored back up by some separate hardcoded minimum.
- **Evaluated introducing Jev (TypeSafe) sentiment scoring as a possible fix, per the user's own question,
  and concluded it would NOT have helped here - not implemented**: `TYPESAFE_API_KEY` isn't even configured
  in production (confirmed via `railway variables`), and more fundamentally, job 51 never reached the
  "Scoring tone" step at all (it died in embedding, several steps earlier) - switching the sentiment
  scorer cannot fix a job that never gets that far. For completeness, also confirmed the *local* lexicon
  scorer `score_text` (`app/text_pipeline/sentiment.py`) that runs by default has no heavy NLP dependency
  (plain `re`/`math`, no spaCy/nltk) - it is not a meaningful CPU cost at 80k-row scale either way, so
  there is no CPU-pressure case for switching to Jev by default even independent of this incident. Jev
  stays exactly what it already was: an explicit opt-in (`use_jev_sentiment`) a user can choose per build,
  not a fix for this specific timeout.
- Full backend suite green (605 passed, 1 skipped, same pre-existing unrelated failures).

## 2026-10-10 (theme-building pipeline robustness: 2 `docs/TODO.md` items worked through)

**1. Retry on a dropped-cluster labeling reply - fixed.** `app/text_pipeline/labeling.py` gains
`label_clusters_with_retry`/`label_sub_clusters_with_retry`, each wrapping the existing
`label_clusters`/`label_sub_clusters` with one retry (a fresh `client.complete()` call, same prompt) on
`LabelingError` before raising for real - `LABELING_RETRY_ATTEMPTS = 2` (the original attempt plus one
retry), shared via a small private `_retry_on_labeling_error` helper rather than duplicated twice. Matches
the real, reported failure signature exactly: a manual "Try again" (a whole new build) succeeded
immediately on the very next attempt, which is the direct signal that retrying just the one labeling call
- not the whole embed+cluster+label pipeline - should already fix most occurrences. `app/api_themes.py`'s
`_work` now calls the retry versions at both labeling call sites; `label_sub_clusters`'s own existing
"fall back to no sub-themes" path (sub-themes are an optional enhancement, never worth failing the whole
build over) is unchanged - the retry just means that fallback is reached less often, not replaced. Only
`LabelingError` is retried; any other exception type (a real network/auth error) still propagates
immediately, same as before. 6 new tests in `tests/test_text_pipeline_labeling.py`: recovers after one
dropped-cluster reply (both the top-level and sub-cluster versions), raises after exhausting retries
(both), and a regression pin that a healthy first reply still makes exactly one call (no wasted retry
"insurance" cost on the common, already-working case).

**2. `subthemes.py`'s sub-clustering pass "never got the `finer_floor` treatment" - investigated, found
NOT to be a real bug, no code change shipped.** First attempt mirrored the top-level `finer_floor` fix
directly: added a `min_samples_reference` parameter to `cluster_answers` so a caller with its own
explicit, small `min_cluster_size` (`subthemes.py`'s `sub_cluster_min_size`, ~10% of the parent) could
still pin `min_samples` to a separate, "stricter" reference, and wired `subthemes.py` to pass
`adaptive_min_cluster_size(n_parent)` as that reference, by direct analogy with how the top-level fix
pins `min_samples` to the STANDARD (non-finer) adaptive formula.

**This was caught as backwards before shipping, by a real test, not assumed correct from the analogy.**
A test spying on the real `HDBSCAN(...)` constructor call (not just the final clustering output) showed
`adaptive_min_cluster_size(n_parent)` is actually SMALLER than `sub_cluster_min_size(n_parent)` for every
realistic parent size - confirmed numerically from n=100 to n=10,000:

| parent n | `sub_cluster_min_size` | `adaptive_min_cluster_size` | min_samples (today's default) | min_samples (the rejected "fix") |
|---|---|---|---|---|
| 100 | 10 | 5 | 3 | 3 |
| 150 | 15 | 5 | 5 | 3 |
| 300 | 30 | 6 | 10 | 3 |
| 1000 | 100 | 20 | 10 | 7 |
| 2500+ | 250+ | 50 (capped) | 10 | 10 |

`sub_cluster_min_size` grows linearly with no ceiling (`round(n * 0.10)`), while `adaptive_min_cluster_size`
caps at 50 (`round(n / 50)`, clamped `[5, 50]`) - the two formulas are not "finer vs standard" versions of
the same thing the way `adaptive_fine_min_cluster_size`/`adaptive_min_cluster_size` are at the top level;
`sub_cluster_min_size` is actually the LARGER, stricter-sized one for almost every realistic parent size.
Using the "standard" top-level formula as a min_samples reference would have LOOSENED density strictness
below what today's unpinned default already gives - the opposite of the intended fix.

Digging into why the top-level bug doesn't transfer: the top-level bug's real mechanism was `min_samples`
deriving from an UNBOUNDED-above value (an adaptive `min_cluster_size` with no ceiling at dataset scale) -
`adaptive_min_samples`, by contrast, already clamps its OUTPUT to a fixed `[3, 10]` range regardless of
how large its input is, so sub-clustering's `min_samples` was never at risk of growing unboundedly loose
the way the top-level case was. Separately, `adaptive_min_samples` (vs. the raw, unclamped default) is
only even USED when UMAP reduction applies (`_reduction_eligible`, needs `n >= 50` and `dims >= 50`) - and
every eligible parent (`len(members) >= MIN_THEME_SIZE_FOR_SUBTHEMES = 100`) always clears both thresholds
automatically, since real embeddings are always 1024-dimensional (Voyage) regardless of how small the
parent is. So sub-clustering was already, unconditionally, going through the SAME clamped-and-adaptive
path the top-level fix exists to route dataset-scale clustering into - there was no unguarded path left
for the bug to hide in.

Reverted the `cluster_answers`/`subthemes.py` code change and its tests entirely (not left in as dead,
unused flexibility - nothing else needs `min_samples_reference`); kept the investigation as this writeup
plus the `docs/TODO.md` entry, matching the existing "investigated and rejected, documented why" pattern
this project already uses for the embedding-space merge design (2026-09-30 entry) - so nobody re-attempts
the identical "mirror the top-level fix" design without reading this first.

Full backend suite green throughout (610 passed, 1 skipped, same pre-existing unrelated failures) - the
6 labeling-retry tests are real, shipped coverage; the sub-clustering investigation's own tests were
written, run, caught the bug, and were then reverted along with the code they were testing.

## 2026-10-21 (fixed: `GET /report` 500 crash on any segment column with blank cells)

User reported "reporting is not working correctly." Investigated by reproducing locally against the real
Amazon reviews dataset (dataset 1, `reviews.text` column): `GET /api/datasets/1/report?column=reviews.text`
returned a 500, `ValueError: Out of range float values are not JSON compliant: nan`, raised from
Starlette's own `json.dumps` inside `JSONResponse.render` - i.e. the *entire* report response, not one
block, failed to serialize.

**Root cause**: `build_structured_context`'s segment-column loop (`app/findings_structured.py`, the
`for segment_col in columns.get("segment", [])` block) read each row's raw segment-column value straight
off the cleaned dataframe (`clean_df.at[r, segment_col]`) with no check for a blank/missing cell. Pandas
represents a missing cell as `float('nan')`, so a dataset with even one blank value in its segment column
got a literal `float('nan')` treated as if it were a real category value - counted in `group_totals`,
potentially surviving the suppression floor as its own "group," and ultimately constructed into
`SegmentGroup(label=nan, ...)`. That NaN then flowed, unflagged, all the way into the top-level JSON
response via `app/api_report.py`'s `filter_options.segment.groups` (added for the Filters feature,
2026-10-02 - before that date `segment.groups` labels were only ever consumed inside chart-rendering code,
which stringifies values rather than JSON-serializing them, so this exact crash shape could not have
happened before Filters shipped). The date-column loop already guarded against this correctly
(`if ts is None or pd.isna(ts): continue`); the score-column loop is protected downstream by
`apply_bands`'s own explicit NaN skip (line ~349, pre-existing). Only the segment-column loop had no
equivalent guard.

**Fix**: `app/findings_structured.py`'s segment loop now skips a row whose raw value is `None` or NaN
before it ever enters `raw_seg` - a missing cell is correctly treated as "this row has no segment," not
as membership in a group called "nan." One-line-equivalent change, matching the exact guard style already
used by `apply_bands`.

**New regression test**: `tests/test_findings_structured.py::test_build_structured_context_drops_nan_segment_values_instead_of_treating_them_as_a_group`
- 300 synthetic rows, 30 with a blank segment cell, asserts exactly 2 string-labeled groups survive (never
a third NaN-labeled one) and the 30 blank rows never appear in `segment_raw_by_row`.

**Verified live**: ran the real local app against dataset 1 (`Amazon_reviews.csv`) before and after the
fix - 500 before, 200 with a fully-rendered report (15 themes, 5 "what stands out" findings, working
filter bar) after, confirmed via `claude-in-chrome`. Confirmed dataset 2 (`Womens Clothing E-Commerce
Reviews.csv`) was unaffected either way (its segment column, `Division Name`, has no missing values).
Full backend suite: 611 passed (610 + the new test), 1 skipped - no regressions.

**Second, separate finding - documented, not fixed in this pass**: on dataset 1, the segment column that
actually ends up selected for the heatmap/filter is `ean` (a product barcode column), visible in the live
screenshot as a filter literally labeled "All ean." This is NOT a bug in the selection mechanism itself -
`pick_structured_columns`/`build_structured_context` correctly try every confirmed `segment`-kind column
in upload order and use the first one whose groups clear the suppression floor, exactly as designed
(confirmed: `brand` has only 1 group above the 100-answer floor - Moshi, n=12, is suppressed - so it's
correctly skipped; `colors` similarly only has 1 surviving group after NaN rows are now correctly excluded).
The real gap is one layer earlier: the column *profiler* classifies ID-like columns such as `ean`/`upc`/
`manufacturerNumber` as `segment` kind in the first place, alongside genuinely meaningful segments like
`brand`/`colors`/`manufacturer` - a barcode is not a meaningful audience segment even though it has low
cardinality. This is the same category of gap `docs/TODO.md`'s existing "Column profiling & report
adaptivity" section already tracks (segment-kind heuristics, `open_text` uniqueness gating, etc.) - added
as a new explicit line item there rather than fixed here, since it's a profiler-heuristic change (risk of
affecting every dataset's column guesses), not a report-rendering bug, and out of scope for "fix the
reporting crash."

## 2026-10-21 (fixed: theme-labelling JSON truncation on datasets with enough distinct themes)
Reported live on `devapp` (the new Railway staging environment): "Build themes" failed with "Theme
labelling failed: Claude's reply was not valid JSON: Expecting ',' delimiter" - and it failed the SAME
way on both the original call and its one automatic retry (`labeling.py::_retry_on_labeling_error`),
breaking at nearly the same character offset both times (attempt 1: char 10605; attempt 2: char 10458,
per `railway logs --environment devapp`). That near-identical-offset signature is the tell: this is not
the occasional malformed/dropped-cluster reply the existing retry already exists for and usually fixes
(see the retry's own docstring) - it's a hard ceiling being hit the same way every time, which a same-
prompt, same-budget retry can never fix.

Root cause: `app/text_pipeline/labeling.py`'s `MAX_TOKENS = 4096` bounds the ENTIRE theme-labelling
reply, and by design (SPEC.md: "one batched call for all clusters, never one call per cluster") every
theme for the whole dataset has to fit in that one response. JSON-heavy output (quotes, colons, commas
around short label/description/merge_with/note fields) tokenizes far less efficiently than prose -
roughly 2.5-3 characters per token here, not the usual ~4 - so a dataset with enough distinct themes
reliably pushed the reply past 4096 tokens and got it truncated mid-string.

Fix: raised `MAX_TOKENS` to 16000 (same constant used by both `label_clusters` and `label_sub_clusters`,
so sub-theme labelling gets the same headroom). Billing is per token actually generated, not per
`max_tokens` ceiling, so this costs nothing on the overwhelming majority of builds that never needed the
extra room. Full backend suite: 611 passed, 1 skipped, no regressions (no test asserted the old literal
value). Re-ran the exact failing build on `devapp` against the same dataset after deploying the fix -
succeeded, themes built with no labelling error.

Deliberately NOT done (at the time): scaling `MAX_TOKENS` dynamically with cluster count (mirroring
`api_themes.py::_themes_deadline_for`'s pattern). The `ClaudeClient` protocol (`complete(system, prompt)
-> str`) is shared across `labeling.py`, `sentiment.py`, `jev_sentiment.py`, `findings.py`, and their
fakes/tests - threading a dynamic `max_tokens` through all of them for one constant's value is a much
larger, riskier change than this bug warranted. A single generous static bump is the right-sized fix
unless a future dataset's cluster count is large enough to need scaling too - if that happens, revisit.

## 2026-10-21 (same day, follow-up: the flat 16000 bump above was not enough either - now scaled)
Re-tested the flat `MAX_TOKENS=16000` bump against the SAME real devapp dataset (75,000 rows) that
exposed the original bug. It failed again, the same way, on BOTH the call and its retry: `Expecting ','
delimiter` at char 41212 (first attempt) and char 40518 (the final, user-visible error) - both landing
at essentially the same ~41,000-character offset the earlier root-cause analysis predicted
(~16,000-16,400 tokens at JSON's ~2.5-3 chars/token rate), confirming this dataset's real theme count
needs noticeably more than 16000 output tokens, not just "a bit more."

Revisited the "deliberately not done" call above given this new evidence: a second flat-number guess
risked being wrong again for the same reason the first one was, so implemented the deferred dynamic
scaling instead - and it turned out smaller and safer than feared once actually traced through every
real caller instead of guessed at. `ClaudeClient.complete` gained an optional `max_tokens: int =
MAX_TOKENS` keyword (every existing caller keeps working unchanged via the default). The worry about a
protocol shared across four modules turned out overstated: the actual single-method `complete(system,
prompt) -> str` Protocol this threads through is only `labeling.py`'s own `AnthropicClaudeClient`/
`FakeClaudeClient`; `findings.py` imports and calls `AnthropicClaudeClient()` directly (no override
needed - it never asks for a bigger budget), `sentiment.py`'s `ClaudeClient` is an unrelated `Any`-typed
raw-SDK shape, and `jev_sentiment.py` is a separate vendor entirely - none of those needed touching.

New `_max_tokens_for(n_clusters) -> int` (`labeling.py`): `min(MAX_TOKENS_CEILING, max(MAX_TOKENS,
n_clusters * TOKENS_PER_CLUSTER))` - `TOKENS_PER_CLUSTER = 300` (a generous per-entry allowance: cluster
id, label, description, merge_with, note, JSON punctuation), `MAX_TOKENS_CEILING = 48000` (a sanity
backstop, far under Sonnet 5's real 128K synchronous-API output ceiling - confirmed via Anthropic's own
docs, not assumed). `MAX_TOKENS` itself (16000) stays as the floor for ordinary datasets, so a normal
build's cost is unchanged. Both `label_clusters` and `label_sub_clusters` now compute and pass their own
scaled `max_tokens`, logged (`log.info("Theme labeling: %d clusters, max_tokens=%d", ...)`) so a future
truncation (if the real cluster count ever exceeds what 48000 tokens can cover) is diagnosable from logs
alone, not re-discovered by trial and error the way this one was.

New tests in `tests/test_text_pipeline_labeling.py`: `_max_tokens_for` at the floor, scaling past the
floor, clamped at the ceiling, and `label_clusters` actually passing the scaled value through to
`client.complete`. Full suite: 615 passed (611 + 4 new), 1 skipped, no regressions.

**Not yet re-verified live** against the actual 75,000-row dataset that triggered this - deploying to
devapp and a fresh "Try again" build is the next step, to confirm the real cluster count for this
dataset falls within the new ceiling (not just that the formula is correct in isolation).

## 2026-10-21 (same day, follow-up #2: the scaled max_tokens itself broke a different way)
Deployed the cluster-count-scaled fix above and re-ran the build on the same devapp dataset. It no
longer hit the JSON-truncation error - but the build still failed, this time with a generic "Something
went wrong while building this" (not the specific labelling-failure message), and the background thread
crashed outright per Railway logs:

```
ValueError: Streaming is required for operations that may take longer than 10 minutes.
```

Root cause: the Anthropic Python SDK itself refuses a plain, non-streaming `messages.create()` call once
`max_tokens` is large enough that generation could plausibly take over 10 minutes - this guard only
started firing because `_max_tokens_for` now asks for a genuinely large budget on theme-rich datasets
(the earlier flat 4096/16000 values never came close to tripping it). This is a `ValueError`, not a
`LabelingError`, so `_retry_on_labeling_error` never caught it - it propagated straight past the
labelling retry logic and crashed `app/jobs.py`'s background worker thread, which is why the user-facing
message was the generic background-job failure, not the specific labelling-error text.

Fix: `AnthropicClaudeClient.complete` (`labeling.py`) now calls `self._client.messages.stream(...)`
inside a `with` block and reads `stream.get_final_message()`, instead of `self._client.messages.create(...)`
directly. Confirmed against the installed SDK itself (`anthropic==1.8.0`) that `Messages.stream`'s
signature accepts the same `model`/`max_tokens`/`system`/`thinking`/`messages` kwargs this call already
passes - no other call-site change needed. This call site is still synchronous from its own caller's
point of view (`complete()` still blocks until the full reply is available) - `stream=True` only changes
how the SDK transports the response over the wire, not this method's blocking behaviour, so nothing
upstream of `complete()` needed to change. No test mocked the internal `messages.create`/`.stream` SDK
shape directly (confirmed via grep), so no test needed updating. Full suite: 615 passed, 1 skipped.

**Verified live, third attempt, success**: deployed and re-ran "Try again" on the same 75,000-row
dataset. Theme-build job completed with no error, the app auto-triggered the report-build job right
after, and `GET .../report` returned 200 with a fully-rendered report - 7 top-level themes (Console/brand
loyalty talk, General love for a game, Anger at NBA2K, Verizon service complaints, Nvidia product
reactions, Twitch stream promotion, Anger at Madden NFL) plus sub-themes, "Other" absorbing 82.7% of
answers. That high "Other" share is consistent with this being an unusually broad/noisy real-world
dataset (game-related social text, not a structured survey) - which is exactly why it needed enough
distinct theme labels to repeatedly trip both the flat-token-budget bug and the streaming-requirement
bug above. Confirms both of this day's fixes together (cluster-count-scaled `MAX_TOKENS`, plus the
streaming API switch) resolve the original crash end to end on the real dataset that exposed it.

## 2026-10-21 (same day: investigating an unexpectedly high "Other" share at large scale - diagnostics added, not yet root-caused)
User reported a SECOND, unrelated large dataset (~40,000 rows, a structured workplace-facilities survey -
building satisfaction, office noise, desk space, cleanliness, temperature) also landing at ~80.7% "Other"
- essentially the same share as the 75,000-row meme/chat dataset above, despite being a completely
different kind of content (a real structured survey, the kind this app's clustering was specifically
validated against before).

That similarity across two very different content types is suspicious enough to investigate properly
rather than wave off as "diverse content." Checked this project's own prior record: the dataset that
originally motivated the UMAP/HDBSCAN fix (23,486 rows, Amazon reviews) settled at only **18.7% Other**
once correctly tuned (see this file's dated entry on soft-reassigning noise). 18.7% vs ~80% on datasets
roughly 2-3x bigger is a real gap needing an explanation, not a restatement of "some data clusters worse."

**One theory already ruled out by reading the code, not assumed**: `cluster_answers(..., finer_floor=True)`
- the "recover small-but-real topics instead of writing them off" mechanism - is ALREADY the default for
every build (`pipeline.py::embed_and_cluster_with_vectors` always passes `finer_floor=True`). It was
previously suggested to the user as something to "try" - that was wrong information, now corrected. Worse:
both the standard (`adaptive_min_cluster_size`, divisor 50) and fine (`adaptive_fine_min_cluster_size`,
divisor 100) floors clamp to the SAME ceiling of 50 once a dataset passes roughly 2,500-5,000 answers - so
for a 40,000 or 75,000-row dataset, the "finer" pass is mathematically IDENTICAL to the standard one. There
is currently no tuning knob in this codebase more lenient than `min_cluster_size=50` for very large
datasets, and that number is already a tiny fraction (0.07-0.1%) of either failing dataset's size, so a
simple "the floor is too strict" explanation does not obviously fit either - worth confirming with real
numbers rather than theorizing further.

**What was done this pass**: added diagnostic-only logging, no behaviour change.
- `app/text_pipeline/clustering.py::cluster_answers` now logs (at INFO): `n`, `dims`, whether UMAP
  reduction ran, the actual `min_cluster_size`/`min_samples` HDBSCAN was given, how many raw groups
  HDBSCAN itself found (top-10 sizes), how many of those were folded into noise purely for being under
  `min_cluster_size`, HDBSCAN's OWN noise count (its density decision, independent of the size floor), and
  the final cluster/noise counts and percentage. This distinguishes two very different root causes that
  would otherwise look identical from the outside: (a) HDBSCAN finding plenty of real-sized dense groups
  that the size floor then discards, vs (b) HDBSCAN's own density test calling almost everything noise
  before the floor is even applied. Confirmed working locally against a synthetic 3000-answer fixture: the
  log line correctly reported 15 real clusters and attributed noise entirely to HDBSCAN's own density
  decision (0 folded for being under the floor) - proving the log distinguishes the two cases correctly.
- **Separately found and fixed while adding this**: `log.info(...)` calls ANYWHERE in this codebase
  (including `labeling.py`'s own cluster-count/`max_tokens` line from earlier today) were silently
  dropped in production - nothing in this process ever called `logging.basicConfig`, so the root logger
  stayed at Python's own WARNING default and only `log.warning`/`log.error` calls ever reached Railway's
  logs (via Python's `lastResort` handler) - which is exactly why `_retry_on_labeling_error`'s warnings
  were always visible in logs but no INFO line ever was. `alembic upgrade head` configures its own
  logging via `alembic.ini`, but that runs as a separate `preDeployCommand` process before the web
  server even starts, so it never affected this. Fixed in `app/main.py`: one `logging.basicConfig(level=
  logging.INFO, ...)` call at import time, before any router or background job can log anything.
- Full backend suite: 615 passed, 1 skipped, no regressions (logging output is not asserted on by any
  existing test).

**Not yet root-caused.** The actual explanation for why 40,000-75,000-row real datasets land at ~80%
Other, versus 18.7% on a smaller real dataset, is still unknown - this pass only makes the real numbers
visible for the next build. The honest next step is re-running a real large dataset through "Build
themes" now that this logging is deployed, and reading what HDBSCAN actually decided from Railway logs.

## 2026-10-21 (same day, root-caused: the 80%+ "Other" is NOT a clustering bug)
Re-ran "Build themes" on the same 75,000-row dataset (devapp, dataset 1) now that the diagnostic logging
above is deployed, and read the real numbers from Railway logs:

```
cluster_answers: n=72688 dims=1024 reduction_applied=True min_cluster_size=50 min_samples=10 |
HDBSCAN found 234 raw groups (sizes top-10: [2837, 1720, 1700, 1640, 1474, 1416, 1311, 1238, 1220, 1191]),
0 of them folded into noise for being under min_cluster_size | HDBSCAN's own noise: 22164 |
final: 234 real clusters (sizes: [... 234 values, smallest 50 ...]), 22164 noise (30.5% of 72688)
```

**HDBSCAN/UMAP are working correctly - better than the baseline, even.** 234 real, dense clusters found,
only **30.5% genuine noise**, zero clusters discarded for being under the size floor. This is a HEALTHY
clustering result, not meaningfully different in kind from the 18.7%-noise baseline that validated this
pipeline originally. The clustering pipeline is fully exonerated by this evidence - no code change to
`clustering.py` is justified, and none was made.

**The real explanation is one layer up, in `app/findings.py::theme_nodes`, and it's a deliberate,
already-documented design decision**: `kept_real = ranked_real[:7]` caps the REPORT to the top 7 ranked
clusters by size (matching `app/charts.py`'s fixed 7-colour `t1..t7` palette), and folds every cluster
ranked 8th or beyond into the SAME "Other" node as genuine noise (`_merge_into_other`, with its own prior
comment confirming this was intentionally built after a real hotel-reviews dataset with 25+ real themes
produced an unreadable chart of same-coloured slivers). That decision was correct for a dataset with a
handful of dominant themes trailing off into many tiny ones - but this dataset has 234 roughly-comparably-
sized real clusters, an order of magnitude beyond what a fixed top-7 display was ever tuned against.

**Confirmed by arithmetic, not just plausible**: top 7 cluster sizes sum to 12,098 of 72,688 answers
(16.6%) - meaning `theme_nodes` folds the other 227 real clusters (50,524 answers) PLUS the 22,164
genuinely noisy answers into "Other," for an implied 83.4% - matching the observed 82.7% within rounding.
The visual "80%+ Other" the user saw is almost entirely real, meaningfully-clustered content that the
report simply doesn't have room to show as named themes, not uncategorised noise.

**Deliberately NOT changed here, and why**: raising the top-7 cap is a product/design decision, not a
clustering parameter - `app/charts.py`'s palette (`t1`..`t7` plus `--other`) is a fixed, hand-chosen
token set per `CLAUDE.md`'s own design rules ("Theme colours only identify themes... no gradients or
shadows"), and inventing more theme colours, or a "show more themes"/pagination affordance, needs actual
design review, not a quick parameter bump buried in a clustering investigation. This was scoped as a
clustering investigation specifically; the fix (if the product decides one is wanted) belongs to a
separate, explicitly-scoped report/chart-design stream. Added as a new, evidenced line item to
`docs/TODO.md` instead of implemented here.

No code changed this pass beyond this entry; the diagnostic logging from the prior entry stays (useful
for any future large-dataset investigation). Full suite: 615 passed, 1 skipped (unchanged, no new tests
needed - no behaviour changed).

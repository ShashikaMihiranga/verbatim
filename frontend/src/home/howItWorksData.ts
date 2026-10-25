// "How Verbatim works" map (hand-off section 7; design/handoffs/HowItWorksDiagram_UIHandoff.md), ported
// from verbatim-visual-system/generator/gen_howitworks.py. Coordinates are the design's 1312 x 920 box.
// The "leaves" text is the privacy promise: keep it exact, and keep it true to app/cleaning/payload.py.

export const MAP_W = 1312
export const MAP_H = 920

export type NodeId = 'browser' | 'api' | 'profile' | 'share' | 'jobs' | 'themes' | 'db' | 'findings' | 'voyage' | 'claude' | 'jev'

export const NODES: Record<NodeId, [number, number, number, number]> = {
  browser: [20, 52, 190, 716],
  api: [270, 90, 240, 130], profile: [270, 245, 240, 150], share: [270, 470, 240, 150],
  jobs: [570, 90, 240, 205], themes: [570, 335, 240, 300], db: [570, 645, 240, 190], findings: [860, 645, 180, 190],
  voyage: [1090, 100, 202, 100], claude: [1090, 230, 202, 160], jev: [1090, 412, 202, 126],
}

export const ZONES: Array<[string, number, number, number, number]> = [
  ['Your browser', 0, 20, 232, 880],
  ['Verbatim on Railway: web service and Postgres', 250, 20, 810, 880],
  ['Outside services', 1072, 20, 240, 880],
]

// [title, sentence] in Plain English and in Technical mode
export const PLAIN: Record<NodeId, [string, string]> = {
  browser: ['Web app', 'Where you work: upload, check, read the report.'],
  api: ['The front door', 'Checks your role (owner, editor or viewer) and sets limits on every request.'],
  profile: ['Profile, clean, mask', 'Guesses column kinds, cleans, masks personal details, hides groups under 30 in sensitive columns.'],
  share: ['Share and export', 'Links with the right access, and PNG, PowerPoint or PDF files.'],
  jobs: ['Background jobs', 'Every slow step is a job, and the page shows its named step live.'],
  themes: ['Theme engine', 'Finds what people are talking about.'],
  findings: ['Findings and charts', 'Keeps only differences big enough to trust. Charts come from the live themes.'],
  db: ['Your database', 'Everything is kept here and nowhere else.'],
  voyage: ['Voyage AI', 'Reads the meaning of masked answers.'],
  claude: ['Claude', 'Names themes and sub-themes, writes headlines, suggests which themes to merge.'],
  jev: ['Jev', "Sorts Other's answers into themes the grouping missed."],
}
export const TECH: Record<NodeId, [string, string]> = {
  browser: ['Web app', 'React + Vite, served by the same container.'],
  api: ['FastAPI gateway', 'Roles owner/editor/viewer, rate and body size limits, CSP headers.'],
  profile: ['Profile + clean', 'columns.py, engine.py, redact.py, suppression.py (groups under 30).'],
  share: ['Share + export', 'Share and invite links, Playwright Chromium, python-pptx, reportlab.'],
  jobs: ['Job runner', 'Daemon thread and a Job row with a named step. One build per column.'],
  themes: ['Theme pipeline', 'voyage-3.5, UMAP, HDBSCAN, Claude labels, sub-themes, lexicon tone.'],
  findings: ['Findings + charts', 'findings.py gates, charts.py, from the live themes.'],
  db: ['Postgres', 'One FastAPI service + Postgres. Migrations run before each deploy.'],
  voyage: ['Voyage AI', 'Embeddings API. Masked text in, vectors out.'],
  claude: ['Anthropic Claude', 'Theme labels, sub-theme names, headlines, merge suggestions, profile hints.'],
  jev: ['Jev (TypeSafe AI)', 'Sorts each Other answer: known theme, new theme, or stays in Other.'],
}

export const ICO: Record<string, string> = {
  browser: '<rect x="6" y="9" width="36" height="30" rx="5"/><path d="M6 18h36"/><circle cx="12" cy="13.5" r="1.2"/><circle cx="17" cy="13.5" r="1.2"/><path d="M14 27h20M14 32h12"/>',
  other: '<circle cx="24" cy="24" r="14"/><path d="M24 14v10l7 4"/>',
  api: '<rect x="7" y="8" width="34" height="13" rx="4"/><rect x="7" y="27" width="34" height="13" rx="4"/><circle cx="14" cy="14.5" r="1.4"/><circle cx="14" cy="33.5" r="1.4"/><path d="M22 14.5h13M22 33.5h13"/>',
  profile: '<rect x="7" y="9" width="34" height="30" rx="4"/><path d="M7 19h34M20 9v30M31 9v30"/><path d="M33 30l2.5 2.5L40 27"/>',
  share: '<rect x="8" y="14" width="26" height="26" rx="5"/><path d="M26 22L40 8M31 8h9v9"/>',
  jobs: '<circle cx="24" cy="24" r="7"/><path d="M24 7v6M24 35v6M7 24h6M35 24h6M12 12l4.2 4.2M31.8 31.8L36 36M36 12l-4.2 4.2M16.2 31.8L12 36"/>',
  themes: '<circle cx="17" cy="19" r="9"/><circle cx="33" cy="16" r="6"/><circle cx="30" cy="33" r="8"/>',
  findings: '<path d="M8 38V26M18 38V16M28 38V22M38 38V10"/><path d="M6 40h36"/>',
  db: '<ellipse cx="24" cy="12" rx="14" ry="5"/><path d="M10 12v24c0 2.8 6.3 5 14 5s14-2.2 14-5V12"/><path d="M10 24c0 2.8 6.3 5 14 5s14-2.2 14-5"/>',
  voyage: '<circle cx="12" cy="14" r="2.4"/><circle cx="24" cy="10" r="2.4"/><circle cx="36" cy="16" r="2.4"/><circle cx="16" cy="28" r="2.4"/><circle cx="30" cy="30" r="2.4"/><path d="M12 14l12-4 12 6M16 28l14 2M12 14l4 14M36 16l-6 14"/>',
  claude: '<path d="M24 6l3.4 9.6L37 19l-9.6 3.4L24 32l-3.4-9.6L11 19l9.6-3.4z"/><path d="M36 30l1.5 4 4 1.5-4 1.5L36 41l-1.5-4-4-1.5 4-1.5z"/>',
  refresh: '<path d="M10 24a14 14 0 0124-9.9M38 8v8h-8"/><path d="M38 24a14 14 0 01-24 9.9M10 40v-8h8"/>',
  jev: '<path d="M7 34a17 17 0 0134 0"/><path d="M24 34l8-11"/><circle cx="24" cy="34" r="2.2"/>',
}

// Theme engine sub-steps: [Technical label, Plain sentence]
export const SUBSTEPS: Array<[string, string]> = [
  ['Embed', 'Answers become vectors (Voyage)'], ['Cluster', 'Grouped by code, no AI'], ['Label', 'Claude names each group'],
  ['Sub-themes', 'Sub-themes found, named'], ['Score tone', 'A word list scores tone'],
]
export const OTHER_STEPS: Array<[string, string, string]> = [
  ['New groups', 'Voyage', 'voyage'], ['Name them', 'Claude', 'claude'], ['Sort answers', 'Jev', 'jev'], ['Update themes', 'Code', 'refresh'],
]
export const DB_CHIPS = ['files', 'cleaned files', 'themes', 'theme edits', 'findings', 'reports', 'jobs']
export const EDIT_CHIPS = ['Rename', 'Merge', 'Split', 'Own theme', 'Undo', 'Rebuild report']
export const REPORT_BARS: Array<[string, number]> = [['Cost', 86], ['Charging', 62], ['Range', 44], ['Not needed', 26]]
export const MAP_DOTS: Array<[number, number, number]> = [
  [18, 20, 0], [30, 14, 0], [24, 32, 0], [40, 24, 0], [34, 38, 0], [14, 40, 0], [80, 16, 1], [94, 24, 1], [88, 34, 1], [102, 14, 1], [76, 30, 1], [98, 38, 1],
  [22, 66, 2], [36, 72, 2], [28, 84, 2], [48, 76, 2], [14, 80, 2], [42, 90, 2], [92, 68, 3], [106, 76, 3], [84, 82, 3], [100, 90, 3], [118, 66, 3], [74, 72, 3],
]
export const MAP_COLOURS = ['#0f6688', '#3f8a57', '#b8651b', '#7a5aa6']

// Orthogonal polyline with rounded corners (gen_howitworks.rpath).
export function rpath(pts: Array<[number, number]>, r = 14): string {
  let d = `M${pts[0][0]} ${pts[0][1]}`
  for (let i = 1; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], [x2, y2] = pts[i + 1]
    const l1 = Math.abs(x1 - x0) + Math.abs(y1 - y0), l2 = Math.abs(x2 - x1) + Math.abs(y2 - y1)
    const rr = Math.min(r, l1 / 2, l2 / 2)
    const ux = (x1 - x0) / l1, uy = (y1 - y0) / l1, vx = (x2 - x1) / l2, vy = (y2 - y1) / l2
    d += ` L${(x1 - ux * rr).toFixed(1)} ${(y1 - uy * rr).toFixed(1)} Q${x1} ${y1} ${(x1 + vx * rr).toFixed(1)} ${(y1 + vy * rr).toFixed(1)}`
  }
  return d + ` L${pts[pts.length - 1][0]} ${pts[pts.length - 1][1]}`
}

export type WireStyle = 'solid' | 'dash' | 'dot'
// Wires run only in the gaps between cards. solid = your data through your own server, dash = optional
// or keys, dot = progress and results sent back.
export const WIRES: Record<string, [string, WireStyle]> = {
  req: [rpath([[210, 115], [270, 115]]), 'solid'],
  progress: [rpath([[270, 175], [210, 175]]), 'dot'],
  guess: [rpath([[270, 330], [210, 330]]), 'solid'],
  toprofile: [rpath([[390, 220], [390, 245]]), 'solid'],
  startjob: [rpath([[510, 115], [570, 115]]), 'solid'],
  apidb: [rpath([[510, 170], [558, 170], [558, 670], [570, 670]]), 'solid'],
  cleandb: [rpath([[510, 350], [546, 350], [546, 710], [570, 710]]), 'solid'],
  sharedb: [rpath([[510, 545], [534, 545], [534, 750], [570, 750]]), 'solid'],
  refine: [rpath([[510, 290], [522, 290], [522, 312], [1090, 312]]), 'dash'],
  group: [rpath([[510, 205], [522, 205], [522, 312], [1090, 312]]), 'dash'],
  tothemes: [rpath([[690, 295], [690, 335]]), 'solid'],
  themesdb: [rpath([[690, 635], [690, 645]]), 'solid'],
  tovoyage: [rpath([[810, 365], [832, 365], [832, 135], [1090, 135]]), 'solid'],
  fromvoyage: [rpath([[1090, 170], [850, 170], [850, 400], [810, 400]]), 'solid'],
  toclaude: [rpath([[810, 440], [868, 440], [868, 252], [1090, 252]]), 'solid'],
  fromclaude: [rpath([[1090, 330], [886, 330], [886, 470], [810, 470]]), 'solid'],
  toother: [rpath([[810, 500], [922, 500], [922, 448], [1090, 448]]), 'solid'],
  fromother: [rpath([[1090, 488], [940, 488], [940, 522], [810, 522]]), 'solid'],
  tofind: [rpath([[810, 150], [950, 150], [950, 645]]), 'solid'],
  findclaude: [rpath([[1040, 670], [1052, 670], [1052, 272], [1090, 272]]), 'solid'],
  findback: [rpath([[1090, 355], [1064, 355], [1064, 700], [1040, 700]]), 'solid'],
  finddb: [rpath([[860, 720], [810, 720]]), 'solid'],
  toshare: [rpath([[210, 470], [250, 470], [250, 525], [270, 525]]), 'solid'],
  download: [rpath([[270, 565], [240, 565], [240, 500], [210, 500]]), 'solid'],
}

// [wire, packet glyph, start ms, packet only (wire already drawn)?]
export type Conn = [string, string, number, boolean?]
export interface MapStage {
  title: string
  plain: string
  tech: string
  leaves: string // what leaves your data, exact hand-off text
  conns: Conn[]
  focus: NodeId[]
  db: string[]
}

export const MAP_STAGES: MapStage[] = [
  { title: 'Upload',
    plain: 'You drop in an Excel or CSV file. Verbatim stores it once per unique file in your own database, and guesses what kind each column is.',
    tech: 'POST /api/upload takes .csv, .xlsx or .xls up to MAX_UPLOAD_MB (50 by default), rate limited. The bytes are stored by sha256 in Postgres (uploaded_files). A short-lived temp file feeds openpyxl or xlrd and is deleted. profiling/columns.py guesses each column\'s kind with a reason and a confidence.',
    leaves: "Optional: headers and up to 30 sample values per column go to Claude. Sensitive columns send the header only.",
    conns: [['req', 'file', 0], ['apidb', 'file', 900], ['toprofile', 'file', 1000], ['guess', 'grid', 2000], ['refine', 'text', 2600]],
    focus: ['browser', 'api', 'db', 'profile', 'claude'], db: ['files'] },
  { title: 'Check columns',
    plain: 'You confirm or fix each guess, switch columns off, and set the question and the question type. The type shapes how themes are named and how the report is built.',
    tech: 'PATCH /api/datasets/{id}/columns saves the confirmed kinds, the switch-offs, the question text and the question type. Nothing is read from the file again.',
    leaves: "Nothing.",
    conns: [['req', 'grid', 0], ['apidb', 'grid', 900]], focus: ['browser', 'api', 'db'], db: ['files'] },
  { title: 'Clean and mask',
    plain: 'Verbatim proposes cleaning steps, hides names, emails and numbers, and hides groups under 30 in sensitive columns. Only the masked copy is used for text analysis.',
    tech: 'cleaning/engine.plan_cleaning proposes steps, apply_plan runs them. redact.py masks personal details even if you switched the step off. suppression.py hides groups under 30 for sensitive columns. The cleaned CSV is stored as cleaned_files.',
    leaves: "Nothing. Only the masked copy is used for text analysis. Groups under 30 are hidden in sensitive columns.",
    conns: [['cleandb', 'masked', 0]], focus: ['profile', 'db'], db: ['cleaned files'] },
  { title: 'Find themes',
    plain: 'A background job does the slow work and the page shows each named step live: turning answers into vectors, naming each group, finding sub-themes, naming sub-themes, scoring tone. Every answer then lands on the answer map. Look inside Other then re-sorts the answers that fit no theme, and Jev does the sorting.',
    tech: 'start_job creates a Job row and a daemon thread, and the page polls its step name. A report build and a theme rebuild for the same column never run at once: the second is refused with a message, then allowed when the first finishes. model_safe_column masks every answer, Voyage voyage-3.5 embeds them in batches of 128, UMAP then HDBSCAN groups them (no AI), Claude names each group from about 15 to 25 samples, sub-themes are found and named, and tone is a word list in code. Look inside Other: Voyage and clustering on Other\'s answers, Claude names the groups, Jev sorts each answer into a known theme, a new theme, or leaves it in Other.',
    leaves: "To Voyage: every masked answer in the chosen column. To Claude: about 15 to 25 masked samples per group. Look inside Other: to Voyage, Other's masked samples; to Jev, each masked Other answer plus the list of theme names.",
    conns: [['req', 'grid', 0], ['startjob', 'grid', 600], ['tothemes', 'masked', 1300], ['tovoyage', 'masked', 2000], ['fromvoyage', 'vectors', 3200],
      ['toclaude', 'text', 5200], ['fromclaude', 'text', 6300], ['themesdb', 'themes', 7300], ['progress', 'bar', 3000],
      ['tovoyage', 'masked', 9600, true], ['toclaude', 'text', 10800, true], ['toother', 'masked', 12000], ['fromother', 'themes', 12800], ['themesdb', 'themes', 13800, true]],
    focus: ['browser', 'api', 'jobs', 'themes', 'voyage', 'claude', 'db', 'jev'], db: ['themes', 'jobs'] },
  { title: 'Build the report',
    plain: 'Verbatim compares themes across groups (scores by theme) and across time (themes over time; years, financial years and quarters count as time), keeps only differences big enough to trust, and draws the answer map. Claude writes one headline per finding from numbers only.',
    tech: 'findings.candidate_findings applies size and group-size gates, label_confidence marks each Solid or Tentative, and the question type with pick_chart chooses the chart. One batched Claude call writes the headlines from numbers only. charts.py draws everything from the live themes, and Finding and Report rows are saved.',
    leaves: "To Claude: aggregate numbers only, no answers.",
    conns: [['tofind', 'themes', 0], ['findclaude', 'numbers', 1100], ['findback', 'text', 2300], ['finddb', 'report', 3300], ['progress', 'report', 4300]],
    focus: ['jobs', 'findings', 'claude', 'db', 'api', 'browser'], db: ['findings', 'reports'] },
  { title: 'Edit, share, export',
    plain: 'Rename, merge, split, make a sub-theme its own theme, or undo the newest edit. Each edit is previewed first with real counts. Claude can suggest which themes to merge when you ask. Viewers see no edit controls. An edit marks the report out of date until you press Rebuild report. Share links carry the right access, and you can export PNG, PowerPoint or PDF.',
    tech: 'Every edit is a ThemeEdit row, so the newest can be undone; the report is marked out of date until you press Rebuild report. theme_grouping.py makes one Claude call from names, counts, shares and 3 masked samples per theme, then validates the reply and never trusts it. Roles are owner, editor and viewer, with invite and share links. export.py renders each block in headless Chromium for PNG, PPTX and PDF.',
    leaves: "Only if grouping is asked: theme names, counts, shares and 3 masked samples per theme.",
    conns: [['req', 'text', 0], ['apidb', 'text', 900], ['group', 'text', 1800], ['toshare', 'report', 2800], ['sharedb', 'key', 3700], ['download', 'file', 4600]],
    focus: ['browser', 'api', 'db', 'share', 'claude'], db: ['theme edits', 'reports'] },
]

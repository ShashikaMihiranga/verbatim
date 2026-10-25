// The report-tab charts from the Home D mockup (verbatim-visual-system/generator/home_blocks.py, "fill"
// mode): flat example charts in a 480 x 300 box, made-up EV-survey numbers, no customer data. Classes drive
// the reveal (ReportTabs): cb-d strokes draw, cb-r bars grow up, cb-rx bars grow right, cb-c cells pop,
// cb-f labels fade. User's decision (2026-10-26): the tabs use these, as in the mockup, not real charts.

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const ON: Record<string, string> = { t1: '#ffffff', t2: '#ffffff', t3: '#12303a', t4: '#12303a', t5: '#ffffff', t6: '#12303a' }

function T(x: number, y: number, s: string, size = 13, w = 600, fill = 'var(--ink)', anchor = 'start', cls = 'cb-f') {
  return `<text class="${cls}" x="${x}" y="${y}" text-anchor="${anchor}" style="font-size:${size}px;font-weight:${w};fill:${fill}">${esc(s)}</text>`
}

function treemap() {
  const tiles: Array<[string, number, number, number, number, string]> = [
    ['Cost', 10, 10, 226, 176, 't1'], ['Charging', 242, 10, 228, 108, 't2'], ['Range', 242, 124, 112, 62, 't3'],
    ['Not needed', 358, 124, 112, 62, 't4'], ['Doubts', 10, 192, 226, 98, 't5'], ['Availability', 242, 192, 228, 98, 't6'],
  ]
  return tiles.map(([n, x, y, w, h, c]) =>
    `<g class="cb-c" style="transform-box:fill-box;transform-origin:center"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" style="fill:var(--${c});stroke:none"/></g>`
    + T(x + 12, y + 24, n, 14, 600, ON[c])).join('')
}

function rank() {
  const rows: Array<[string, number]> = [['Delivery speed', 0.94], ['Customer support', 0.76], ['Pricing', 0.6], ['Product quality', 0.46], ['Website and app', 0.32], ['Other', 0.2]]
  const cols = ['var(--neg)', 'color-mix(in srgb,var(--neg) 55%,var(--neu))', 'color-mix(in srgb,var(--neg) 25%,var(--neu))', 'var(--neu)', 'color-mix(in srgb,var(--pos) 40%,var(--neu))', 'var(--neu)']
  let o = ''
  rows.forEach(([n, v], i) => {
    const y = 18 + i * 46
    o += T(8, y + 20, n, 14, 500)
    o += `<rect class="cb-rx" x="150" y="${y}" width="${Math.round(v * 290)}" height="28" rx="4" style="fill:${cols[i]};transform-box:fill-box;transform-origin:0% 50%"/>`
  })
  return o + T(150 + 0.94 * 290 + 10, 18 + 19, 'Most negative', 13, 600, 'var(--neg)')
}

function heat() {
  const rows = ['Cost', 'Charging', 'Range', 'Not needed', 'Doubts']
  const cols = ['Under 25', '25-34', '35-44', '45-54', '55+']
  const V = [[0.9, 0.8, 0.6, 0.45, 0.3], [0.5, 0.6, 0.55, 0.4, 0.25], [0.4, 0.45, 0.5, 0.4, 0.35], [0.15, 0.2, 0.3, 0.5, 0.95], [0.3, 0.3, 0.25, 0.3, 0.4]]
  let o = cols.map((c, j) => T(150 + j * 64 + 28, 20, c, 12, 500, 'var(--muted)', 'middle')).join('')
  rows.forEach((r, i) => {
    const y = 48 + i * 46
    o += T(8, y + 20, r, 14, 500)
    V[i].forEach((v, j) => {
      o += `<g class="cb-c" style="transform-box:fill-box;transform-origin:center"><rect x="${150 + j * 64}" y="${y}" width="56" height="36" rx="5" style="fill:color-mix(in srgb,var(--ramp) ${Math.round(10 + v * 85)}%,var(--surface))"/></g>`
    })
  })
  const hx = 150 + 4 * 64, hy = 48 + 3 * 46
  o += `<rect class="cb-d" x="${hx - 3}" y="${hy - 3}" width="62" height="42" rx="7" style="fill:none;stroke:var(--ink);stroke-width:2.4"/>`
  return o + T(8, 292, 'Older group raises Not needed far more often', 13, 500, 'var(--muted)')
}

function trend() {
  const months = ['Jan', 'Mar', 'May', 'Jul', 'Sep', 'Nov']
  const X = (i: number) => 40 + (340 * i) / 5, Y = (v: number) => 260 - ((v - 15) / 25) * 230
  let o = '<path class="cb-d" d="M30 260H400" style="stroke:var(--line);stroke-width:2"/>'
  const series: Array<[string, number[], string]> = [['Cost', [26, 27, 29, 30, 32, 34], 't1'], ['Charging', [33, 31, 28, 26, 24, 22], 't2']]
  for (const [nm, vals, c] of series) {
    const pts = vals.map((v, i) => `${Math.round(X(i))},${Math.round(Y(v))}`).join(' ')
    o += `<polygon class="cb-f" points="${Math.round(X(0))},260 ${pts} ${Math.round(X(5))},260" style="fill:var(--${c});fill-opacity:.12;stroke:none"/>`
    o += `<polyline class="cb-d" points="${pts}" style="fill:none;stroke:var(--${c});stroke-width:3"/>`
    o += `<circle class="cb-f" cx="${Math.round(X(5))}" cy="${Math.round(Y(vals[5]))}" r="5" style="fill:var(--${c});stroke:none"/>` + T(X(5) + 14, Y(vals[5]) + 5, nm, 15, 600, `var(--${c})`)
  }
  return o + months.map((m, i) => T(X(i), 284, m, 12, 400, 'var(--muted)', 'middle')).join('')
}

function flow() {
  const L: Array<[string, number, number]> = [['Low score', 20, 70], ['Middle', 110, 80], ['High score', 210, 70]]
  const R: Array<[string, number, number, string]> = [['Cost', 10, 90, 't1'], ['Charging', 106, 90, 't2'], ['Not needed', 202, 90, 't4']]
  const links: Array<[number, number, number]> = [[0, 2, 30], [0, 0, 20], [0, 1, 20], [1, 0, 40], [1, 1, 28], [1, 2, 12], [2, 0, 34], [2, 1, 22], [2, 2, 14]]
  const offL = [0, 0, 0], offR = [0, 0, 0]
  let o = ''
  for (const [a, b, w] of links) {
    const ly = L[a][1] + offL[a], ry = R[b][1] + offR[b], lw = w * 0.62
    offL[a] += lw; offR[b] += lw
    o += `<path class="cb-f" d="M110 ${Math.round(ly)} C230 ${Math.round(ly)} 250 ${Math.round(ry)} 370 ${Math.round(ry)}L370 ${Math.round(ry + lw)} C250 ${Math.round(ry + lw)} 230 ${Math.round(ly + lw)} 110 ${Math.round(ly + lw)}Z" style="fill:var(--${R[b][3]});fill-opacity:.34;stroke:none"/>`
  }
  for (const [n, y, h] of L) o += `<rect class="cb-d" x="100" y="${y + 6}" width="10" height="${h * 0.62}" style="fill:none;stroke:var(--ink);stroke-width:2.2"/>` + T(92, y + 22, n, 13, 600, 'var(--ink)', 'end')
  for (const [n, y, h, c] of R) o += `<rect class="cb-d" x="370" y="${y}" width="10" height="${Math.round(h * 0.6)}" style="fill:none;stroke:var(--${c});stroke-width:2.2"/>` + T(390, y + 18, n, 13, 600, `var(--${c})`)
  return o
}

function quotes() {
  const Q: Array<[string, string, string]> = [
    ['Deliveries keep arriving a day late.', 'Delivery speed', 't2'], ['Nobody answers the phone after five.', 'Customer support', 't1'],
    ['The app logs me out constantly.', 'Website and app', 't7'],
  ]
  return Q.map(([q, t, c], i) => {
    const y = 20 + i * 92
    return `<g class="cb-d" style="fill:none;stroke:var(--${c});stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round"><path d="M8 ${y + 14}h8v12H8c0 6 3 8 6 8M24 ${y + 14}h8v12H24c0 6 3 8 6 8"/></g>`
      + T(50, y + 22, q, 16, 300, 'var(--ink)') + T(50, y + 46, t, 13, 600, `var(--${c})`)
      + `<path class="cb-d" d="M50 ${y + 62}H440" style="stroke:var(--line);stroke-width:1.6"/>`
  }).join('')
}

export interface BlockTab { key: string; name: string; chapter: string; sentence: string; needs: string; svg: string }

// Name, chapter, sentence (no figures), what the block needs: the mockup's six tabs.
export const BLOCK_TABS: BlockTab[] = [
  { key: 'treemap', name: 'Theme map', chapter: 'The big picture', sentence: 'Cost and Charging make up more than half of the reasons.', needs: 'Any written answers', svg: treemap() },
  { key: 'rank', name: 'Rank, tinted by tone', chapter: 'What matters most', sentence: 'Delivery speed is the first thing to fix, and it sounds the most negative.', needs: 'An improvements question', svg: rank() },
  { key: 'heat', name: 'Themes by group', chapter: 'Who sees it differently', sentence: 'Older customers mention Not needed far more often than anyone else.', needs: 'A group column, like age', svg: heat() },
  { key: 'trend', name: 'Over time', chapter: 'What is changing', sentence: 'Cost is rising through the year while Charging is fading.', needs: 'A date column', svg: trend() },
  { key: 'flow', name: 'Score to theme to tone', chapter: 'Who sees it differently', sentence: 'People who score low talk most about Not needed, and sound negative.', needs: 'A score column', svg: flow() },
  { key: 'quotes', name: 'In their own words', chapter: 'In their own words', sentence: 'Real answers, so the numbers are believable.', needs: 'Any written answers', svg: quotes() },
]

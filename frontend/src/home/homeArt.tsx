// Line art from the Home D design (verbatim-visual-system/generator/home_common.py and home_modern.py):
// the 3D bars logo, the 96-box icons and the five animated step icons.

const LOGO_POLYS = [
  '14.0,68.0 27.9,76.0 27.9,24.0 14.0,16.0', '27.9,76.0 41.8,68.0 41.8,16.0 27.9,24.0', '27.9,8.0 41.8,16.0 27.9,24.0 14.0,16.0',
  '28.7,76.0 42.6,84.0 42.6,44.0 28.7,36.0', '42.6,84.0 56.5,76.0 56.5,36.0 42.6,44.0', '42.6,28.0 56.5,36.0 42.6,44.0 28.7,36.0',
  '43.4,84.0 57.3,92.0 57.3,62.0 43.4,54.0', '57.3,92.0 71.2,84.0 71.2,54.0 57.3,62.0', '57.3,46.0 71.2,54.0 57.3,62.0 43.4,54.0',
  '58.1,92.0 72.0,100.0 72.0,80.0 58.1,72.0', '72.0,100.0 85.9,92.0 85.9,72.0 72.0,80.0', '72.0,64.0 85.9,72.0 72.0,80.0 58.1,72.0',
]

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="6 0 88 108" aria-hidden="true" style={{ overflow: 'visible' }}>
      {LOGO_POLYS.map((p) => (
        <polygon key={p} points={p} style={{ fill: 'none', stroke: 'var(--ink)', strokeWidth: 2.4, strokeLinejoin: 'round' }} />
      ))}
    </svg>
  )
}

const ICON_PATHS: Record<string, string[]> = {
  lock: ['M20 50a8 8 0 018-8h40a8 8 0 018 8v26a8 8 0 01-8 8H28a8 8 0 01-8-8z', 'M32 42V30a16 16 0 0132 0v12', 'M48 58v10'],
  people: ['M22 34a12 12 0 1024 0 12 12 0 10-24 0', 'M12 80c0-14 10-22 22-22s22 8 22 22', 'M57 38a9 9 0 1018 0 9 9 0 10-18 0', 'M60 60c14-4 26 4 26 20'],
  claude: ['M18 18h60a6 6 0 016 6v34a6 6 0 01-6 6H44L30 80V64H18a6 6 0 01-6-6V24a6 6 0 016-6z', 'M48 27l3.5 9.5L61 40l-9.5 3.5L48 53l-3.5-9.5L35 40l9.5-3.5z'],
  person: ['M34 32a14 14 0 1028 0 14 14 0 10-28 0', 'M20 82c0-17 12-26 28-26s28 9 28 26'],
  auto: ['M48 10l8 22 22 8-22 8-8 22-8-22-22-8 22-8z'],
}

export function Icon({ name, size = 34, sw = 2.6 }: { name: keyof typeof ICON_PATHS | string; size?: number; sw?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 96 96" fill="none" stroke="var(--accent)" strokeWidth={sw}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ overflow: 'visible', flex: 'none' }}>
      {(ICON_PATHS[name] ?? []).map((d) => <path key={d} d={d} />)}
    </svg>
  )
}

export function Arrow({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  )
}

const TB = { transformBox: 'fill-box', transformOrigin: 'center' } as const
const BAR_ORIGIN = { transformBox: 'fill-box', transformOrigin: '50% 100%' } as const
const FADED = { fill: 'var(--accent)', fillOpacity: 0.25, stroke: 'none' } as const
const THEME_DOTS: Array<[number, number, number, number]> = [[8, 12, 22, 24], [88, 10, -18, 22], [8, 52, 24, -6], [90, 54, -26, 4], [10, 88, 36, -30], [84, 86, -20, -12]]

// The five step icons, each with the parts its own loop moves (class names match HomeSteps' animations).
export function StepIcon({ name }: { name: 'upload' | 'columns' | 'themes' | 'find' | 'report' }) {
  return (
    <svg width={52} height={52} viewBox="0 0 96 96" fill="none" stroke="var(--accent)" strokeWidth={2.6} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" style={{ overflow: 'visible', flex: 'none' }}>
      {name === 'upload' && (
        <>
          <path d="M14 64v16a4 4 0 004 4h60a4 4 0 004-4V64" />
          <g className="u-arrow" style={TB}><path d="M48 66V24" /><path d="M32 40l16-16 16 16" /></g>
        </>
      )}
      {name === 'columns' && (
        <>
          <rect x="14" y="16" width="68" height="62" rx="6" />
          <path d="M37 16v62M60 16v62M14 34h68" />
          <rect className="c-hl" x="14" y="16" width="23" height="62" rx="5" style={{ fill: 'var(--accent)', fillOpacity: 0.16, stroke: 'none', opacity: 0 }} />
          <path className="c-check" d="M62 58l6 6 12-14" />
        </>
      )}
      {name === 'themes' && (
        <>
          <circle className="t-circ" cx="36" cy="40" r="20" style={TB} />
          <circle className="t-circ" cx="66" cy="34" r="12" style={TB} />
          <circle className="t-circ" cx="58" cy="66" r="16" style={TB} />
          {THEME_DOTS.map(([x, y, dx, dy]) => (
            <circle key={`${x}-${y}`} className="t-dot" data-dx={dx} data-dy={dy} cx={x} cy={y} r={2.6} style={{ fill: 'var(--accent)', stroke: 'none', opacity: 0 }} />
          ))}
        </>
      )}
      {name === 'find' && (
        <>
          <rect x="14" y="62" width="12" height="22" rx="3" style={FADED} />
          <rect x="32" y="48" width="12" height="36" rx="3" style={FADED} />
          <rect x="50" y="68" width="12" height="16" rx="3" style={FADED} />
          <rect className="f-hi" x="68" y="42" width="12" height="42" rx="3" style={FADED} />
          <g className="f-lens"><circle cx="26" cy="36" r="14" /><path d="M36 46l12 12" /></g>
        </>
      )}
      {name === 'report' && (
        <>
          <path d="M22 10h38l16 16v60H22z" />
          <path d="M60 10v16h16" />
          <rect className="r-bar" x="32" y="52" width="9" height="22" rx="2" style={{ fill: 'var(--accent)', stroke: 'none', ...BAR_ORIGIN }} />
          <rect className="r-bar" x="45" y="42" width="9" height="32" rx="2" style={{ fill: 'var(--accent)', stroke: 'none', ...BAR_ORIGIN }} />
          <rect className="r-bar" x="58" y="58" width="9" height="16" rx="2" style={{ fill: 'var(--accent)', stroke: 'none', ...BAR_ORIGIN }} />
        </>
      )}
    </svg>
  )
}

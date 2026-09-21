import type { CSSProperties } from 'react'
import { useInView, useRevealed } from './motion'

const CHIPS = ['Open-ended text', 'Score, 0 to 10', 'Date, by month', 'Age group', 'Respondent ID, ignored']

export default function Steps() {
  const { ref, seen } = useInView<HTMLOListElement>()
  const on = useRevealed(seen)
  return (
    <section className="lp-section" id="how" aria-labelledby="lp-how-h">
      <div className="lp-section-head">
        <h2 id="lp-how-h">From spreadsheet to story in three steps.</h2>
        <p>Nothing happens behind your back. You see what Verbatim understood and what it cleaned before it builds the report.</p>
      </div>
      <ol ref={ref} className={`lp-steps ${on ? 'on' : ''}`}>
        <li>
          <span className="s-num" aria-hidden="true">1</span>
          <h3>Upload a spreadsheet</h3>
          <p>Drop in an .xlsx or .csv file. Verbatim reads the headers and a small sample of each column.</p>
          <div className="mini-table" aria-hidden="true">
            {[0, 1, 2, 3].map((r) => (
              <div key={r} className="mt-row">
                {[92, 64, 78].map((w, c) => (
                  <i key={c} style={{ width: `${w - r * 6}%`, '--d': `${(r * 3 + c) * 70}ms` } as CSSProperties} />
                ))}
              </div>
            ))}
          </div>
        </li>
        <li>
          <span className="s-num" aria-hidden="true">2</span>
          <h3>Check what each column is</h3>
          <p>Verbatim guesses which column holds the answers, which is a score, a date or a group, and which to ignore. You confirm.</p>
          <ul className="mini-chips">
            {CHIPS.map((c, i) => (
              <li key={c} className={i === CHIPS.length - 1 ? 'muted-chip' : ''} style={{ '--d': `${i * 140}ms` } as CSSProperties}>
                <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.5 5 9.5 10 3" pathLength={1} /></svg>
                {c}
              </li>
            ))}
          </ul>
        </li>
        <li>
          <span className="s-num" aria-hidden="true">3</span>
          <h3>Read a short report</h3>
          <p>One finding per block, each with one sentence and one chart. Open any theme to see the real answers behind it.</p>
          <div className="mini-report" aria-hidden="true">
            <b className="mr-line" />
            {[100, 82, 47].map((w, i) => (
              <i key={i} className="mr-bar" style={{ width: `${w}%`, '--d': `${300 + i * 130}ms` } as CSSProperties} />
            ))}
          </div>
        </li>
      </ol>
    </section>
  )
}

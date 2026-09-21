import { Link } from 'react-router-dom'
import Charts from './Charts'
import Hero from './Hero'
import Steps from './Steps'
import './home.css'

const TRUST = [
  { h: 'Every theme opens the real answers.', p: 'Each theme and each sentence in a report links back to the words people wrote.' },
  { h: 'You see what was cleaned.', p: 'Blank answers, duplicates and spelling variants are listed with counts. You can switch any step off.' },
  { h: 'Small groups stay hidden.', p: 'Groups below a minimum size are left out, so no one is singled out by age, sex or income.' },
  { h: 'The AI sees samples, not your file.', p: 'Only short samples and totals go to the model. The rest is done by ordinary code on the server.' },
]

export default function Landing() {
  return (
    <div className="lp">
      <header className="lp-header">
        <Link to="/" className="lp-logo" aria-label="Verbatim home">Verbatim</Link>
        <nav aria-label="Main">
          <a href="#how">How it works</a>
          <a href="#charts">Charts</a>
          <a href="#trust">Trust</a>
          <Link to="/sign-in">Sign in</Link>
          <Link className="lp-btn primary small" to="/sign-up">Create an account</Link>
        </nav>
      </header>
      <main>
        <Hero />
        <Steps />
        <Charts />
        <section className="lp-section" id="trust" aria-labelledby="lp-trust-h">
          <div className="lp-section-head">
            <h2 id="lp-trust-h">Built so you can check its work.</h2>
          </div>
          <ul className="lp-trust">
            {TRUST.map((t) => (
              <li key={t.h}>
                <h3>{t.h}</h3>
                <p>{t.p}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="lp-final" aria-labelledby="lp-final-h">
          <h2 id="lp-final-h">Try it on your own spreadsheet.</h2>
          <div className="lp-cta">
            <Link className="lp-btn primary" to="/sign-up">Create an account</Link>
            <Link className="lp-btn" to="/sign-in">Sign in</Link>
          </div>
        </section>
      </main>
      <footer className="lp-footer">
        <span>Verbatim</span>
        <span className="muted">Open-ended answers, made readable.</span>
      </footer>
    </div>
  )
}

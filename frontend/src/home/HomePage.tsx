import { animate, createScope, splitText, stagger, utils } from 'animejs'
import { useEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import HeroStage from './HeroStage'
import HomeSteps from './HomeSteps'
import HowItWorksMap from './HowItWorksMap'
import ReportTabs from './ReportTabs'
import { Arrow, Icon, Logo } from './homeArt'
import { MAP_STAGES } from './howItWorksData'
import { onView, useReducedMotion } from './homeMotion'
import './home-d.css'

// The public home page, Home D (design/handoffs/HomePageD_UIHandoff.md, design/screens/Home-D.dc.html).
// Order: sticky top bar, hero, five steps, what is in a report, privacy, call to action, the "How Verbatim
// works" map, footer. Sign in goes to Clerk's sign-in, Get started to sign-up, See a sample report to /sample.

const SAMPLE = '/sample'

function Buttons() {
  return (
    <div className="hd-btns">
      <Link className="hd-btn main" to="/sign-up">Get started<Arrow /></Link>
      <Link className="hd-btn ghost" to={SAMPLE}>See a sample report</Link>
    </div>
  )
}

const CLAIMS = [
  { icon: 'lock', title: 'Masked first', text: 'Names, emails and numbers are hidden before anything leaves your data.' },
  { icon: 'people', title: 'Small groups hidden', text: 'No one can be picked out of a chart.' },
  { icon: 'claude', title: 'Samples only', text: 'Claude reads a few sample answers and totals, never your whole file.' },
]

// Rises in, one after another, when scrolled into view.
function useRiseIn<T extends HTMLElement>(selector: string, opts: { y: number; stagger: number; duration: number; fallback: number }) {
  const ref = useRef<T | null>(null)
  const reduce = useReducedMotion()
  useEffect(() => {
    const el = ref.current
    if (!el || reduce) return
    let stop = () => {}
    const scope = createScope({ root: el }).add(() => {
      const items = Array.from(el.querySelectorAll<HTMLElement>(selector))
      utils.set(items, { opacity: 0, y: opts.y })
      stop = onView(el, () => animate(items, { opacity: [0, 1], y: [opts.y, 0], duration: opts.duration, delay: stagger(opts.stagger), ease: 'outExpo' }), opts.fallback, 0.15)
    })
    return () => { stop(); scope.revert() }
  }, [reduce, selector, opts.y, opts.stagger, opts.duration, opts.fallback])
  return ref
}

function FooterLink({ to, children }: { to?: string; children: ReactNode }) {
  if (!to) return <li className="is-soon">{children}</li>
  return <li>{to.startsWith('#') ? <a href={to}>{children}</a> : <Link to={to}>{children}</Link>}</li>
}

export default function HomePage() {
  const reduce = useReducedMotion()
  const h1 = useRef<HTMLHeadingElement | null>(null)
  const claims = useRiseIn<HTMLDivElement>('.hd-claim, .hd-claim-note', { y: 16, stagger: 140, duration: 600, fallback: 9000 })
  const footer = useRiseIn<HTMLElement>('.hd-fcol', { y: 20, stagger: 110, duration: 900, fallback: 9000 })

  useEffect(() => { document.title = 'Verbatim: survey answers, made clear' }, [])
  useEffect(() => {
    const el = h1.current
    if (!el || reduce) return
    // Headline words rise in. splitText keeps an accessible copy of the full sentence.
    const scope = createScope({ root: el }).add(() => {
      const split = splitText(el, { words: { wrap: 'clip' } })
      animate(split.words, { y: ['110%', '0%'], duration: 900, delay: stagger(90), ease: 'outExpo' })
    })
    return () => scope.revert()
  }, [reduce])

  return (
    <div className="hd">
      <header className="hd-nav">
        <div className="hd-wrap hd-x hd-nav-in">
          <Link to="/" className="hd-brand" aria-label="Verbatim home"><Logo size={40} /><span>Verbatim</span></Link>
          <nav className="hd-links" aria-label="Main">
            <a className="hd-hide-s" href="#how-it-works">How it works</a>
            <a className="hd-hide-s" href="#what-you-get">What you get</a>
            <a className="hd-hide-s" href="#privacy">Privacy</a>
            <Link className="hd-signin hd-hide-xs" to="/sign-in">Sign in</Link>
            <Link className="hd-outline" to="/sign-up">Get started</Link>
          </nav>
        </div>
      </header>

      <main className="hd-wrap">
        <section className="hd-hero hd-x" aria-labelledby="hd-h1">
          <div className="hd-hero-text">
            <div className="hd-eye">Survey answers, made clear</div>
            {/* aria-label: splitText's word spans would otherwise be read on top of its accessible copy */}
            <h1 id="hd-h1" ref={h1} className="hd-h1" aria-label="From a messy sheet to a clear report.">From a messy sheet to a clear report.</h1>
            <p className="hd-lead">Verbatim reads every answer, finds the themes and who feels differently, and gives you a short report anyone can read.</p>
            <div style={{ marginTop: 34 }}><Buttons /></div>
            <p className="hd-note">Works with Excel and CSV files.</p>
          </div>
          <HeroStage />
        </section>

        <section className="hd-x" style={{ marginTop: 40 }} aria-labelledby="hd-steps-h">
          <h2 id="hd-steps-h" className="hd-h2">Five steps. You stay in control.</h2>
          <HomeSteps />
        </section>

        <section id="what-you-get" className="hd-x hd-anchor" style={{ marginTop: 100 }} aria-labelledby="hd-report-h">
          <div className="hd-eye">What is in a report</div>
          <h2 id="hd-report-h" className="hd-h2" style={{ marginTop: 12 }}>Small blocks. One idea each.</h2>
          <p className="hd-sub">Each block says one thing in one sentence with one chart. Verbatim picks only the blocks your file can support.</p>
          <ReportTabs />
        </section>

        <section id="privacy" className="hd-x hd-anchor" style={{ marginTop: 100 }} aria-labelledby="hd-priv-h">
          <h2 id="hd-priv-h" className="hd-priv-h">Your answers stay yours.</h2>
          <div ref={claims}>
            <div className="hd-claims">
              {CLAIMS.map((c) => (
                <div key={c.title} className="hd-claim">
                  <div className="hd-tile-ico"><Icon name={c.icon} /></div>
                  <div><div className="hd-claim-t">{c.title}</div><div className="hd-claim-b">{c.text}</div></div>
                </div>
              ))}
            </div>
            <p className="hd-claim-note">An embeddings service reads the masked answers to find their meaning.</p>
          </div>
        </section>

        <section className="hd-x" style={{ marginTop: 100 }} aria-labelledby="hd-cta-h">
          <div className="hd-cta">
            <div>
              <h2 id="hd-cta-h" className="hd-cta-h">Turn your next survey into a clear report.</h2>
              <p className="hd-cta-s">Upload a sheet. Check the columns. Read the story.</p>
            </div>
            <div className="hd-cta-btns">
              <Link className="hd-cta-btn white" to="/sign-up">Get started</Link>
              <Link className="hd-cta-btn line" to={SAMPLE}>See a sample report</Link>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="hd-x hd-anchor" style={{ marginTop: 85 }} aria-labelledby="hd-map-h">
          <div className="hd-map-head">
            <div className="hd-eye">How Verbatim works</div>
            <h2 id="hd-map-h" className="hd-map-h">From your spreadsheet to a report, and what leaves your data on the way.</h2>
            <p className="hd-sub" style={{ maxWidth: 820 }}>Follow one file through six steps. Boxes light up where work happens, packets show what moves.</p>
          </div>
          <HowItWorksMap />
          <ol className="hd-maplist">
            {MAP_STAGES.map((s, i) => (
              <li key={s.title}>
                <div className="hd-ml-n">Step {i + 1}</div>
                <div className="hd-ml-t">{s.title}</div>
                <p className="hd-ml-p">{s.plain}</p>
                <p className="hd-ml-leave"><b>What leaves your data: </b>{s.leaves}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer ref={footer} className="hd-foot">
        <div className="hd-wrap hd-x">
          <div className="hd-foot-top">
            <div className="hd-fcol hd-foot-brand">
              <div className="hd-foot-logo"><Logo size={46} /><span>Verbatim</span></div>
              <p className="hd-foot-tag">Survey answers, made clear.</p>
              <p className="hd-foot-sub">Upload a sheet. Check the columns. Read the story.</p>
              <div style={{ marginTop: 28 }}><Buttons /></div>
            </div>
            <nav className="hd-fcol hd-foot-col" aria-labelledby="hd-f-product">
              <h3 id="hd-f-product">Product</h3>
              <ul>
                <FooterLink to="#how-it-works">How it works</FooterLink>
                <FooterLink to="#what-you-get">What is in a report</FooterLink>
                <FooterLink to="#what-you-get">Themes you can steer</FooterLink>
                <FooterLink>Made for teams</FooterLink>
              </ul>
            </nav>
            <nav className="hd-fcol hd-foot-col" aria-labelledby="hd-f-trust">
              <h3 id="hd-f-trust">Trust</h3>
              <ul>
                <FooterLink to="#privacy">Masked first</FooterLink>
                <FooterLink to="#privacy">Small groups hidden</FooterLink>
                <FooterLink to="#privacy">Samples only</FooterLink>
                <FooterLink to="#how-it-works">What leaves your data</FooterLink>
              </ul>
            </nav>
            <nav className="hd-fcol hd-foot-col" aria-labelledby="hd-f-start">
              <h3 id="hd-f-start">Start</h3>
              <ul>
                <FooterLink to="/sign-up">Upload a sheet</FooterLink>
                <FooterLink to="/sign-up">Check the columns</FooterLink>
                <FooterLink to={SAMPLE}>See a sample report</FooterLink>
                <FooterLink to="/sign-in">Sign in</FooterLink>
              </ul>
            </nav>
          </div>
          <div className="hd-fcol hd-facts">
            {CLAIMS.map((c) => (
              <span key={c.title} className="hd-fact"><span className="hd-fact-ico"><Icon name={c.icon} size={20} sw={3.2} /></span>{c.title}</span>
            ))}
          </div>
          <div className="hd-fcol hd-foot-bottom">
            <span>&copy; 2026 Verbatim. Made for open-ended answers.</span>
            <span><a href="#privacy">Privacy</a><span className="is-soon">Terms</span><span className="is-soon">Contact</span></span>
          </div>
        </div>
      </footer>
    </div>
  )
}

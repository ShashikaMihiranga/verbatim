import { useEffect, useState } from 'react'
import {
  Check, ChevronDown, Circle, CircleCheck, Eye, ICON, Info, Layers, Loader, Lock, Merge, RefreshCw, Shield, ShieldAlert,
  ShieldCheck, Sparkles, X,
} from './icons'
import type { Job } from './jobsApi'
import type { GroupingPayload, GroupingResult, GroupSuggestion } from './themeEditorApi'
import { fmt } from './themeEditorModel'

// "Group matching themes" (design/handoffs/ThemeGrouping_UIHandoff.md): Claude proposes groups of themes
// that mean the same thing, the user accepts or skips each, and Apply merges the accepted ones together,
// with one Undo. Four states: idle, running, review, applied. Nothing merges until Apply.
type Decision = 'accept' | 'skip'
type Phase = 'idle' | 'running' | 'review' | 'applied' | 'failed'

export interface GroupingProps {
  themeIds: Set<number> // the live theme list: members that no longer exist drop out of their group
  totalThemes: number
  loadPayload: () => Promise<GroupingPayload>
  start: () => Promise<{ job_id: number }>
  poll: (jobId: number, onUpdate: (job: Job) => void) => () => void
  onApply: (groups: Array<{ name: string; theme_ids: number[] }>, summary: string) => Promise<number>
  undoneToken: number | null // the editor undid this edit; if it was our Apply, go back to review
}

export default function ThemeGrouping({ themeIds, totalThemes, loadPayload, start, poll, onApply, undoneToken }: GroupingProps) {
  const [phaseState, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<GroupingResult | null>(null)
  const [groups, setGroups] = useState<GroupSuggestion[]>([])
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [showPayload, setShowPayload] = useState(false)
  const [payload, setPayload] = useState<GroupingPayload | null>(null)
  const [applied, setApplied] = useState<{ token: number; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  // The editor undid our Apply: back to the review, with the earlier accept and skip choices kept.
  const phase = phaseState === 'applied' && applied && undoneToken === applied.token ? 'review' : phaseState


  useEffect(() => {
    if (!showPayload || payload) return
    let live = true
    loadPayload().then((p) => { if (live) setPayload(p) }).catch((e) => { if (live) setError((e as Error).message) })
    return () => { live = false }
  }, [showPayload, payload, loadPayload])

  async function find() {
    setError(null)
    setPhase('running')
    try {
      const { job_id } = await start()
      // The update may arrive before `poll` returns its stop function: stop as soon as both exist.
      let stop: (() => void) | null = null
      let finished = false
      stop = poll(job_id, (job) => {
        if (job.status === 'running') return
        finished = true
        stop?.()
        if (job.status === 'failed') {
          setError(job.error ?? 'Could not reach Claude. Try again.')
          setPhase('failed')
          return
        }
        const r = job.result as GroupingResult
        setResult(r)
        setGroups(r.groups)
        setDecisions({})
        setPhase('review')
      })
      if (finished) stop()
    } catch (e) {
      setError((e as Error).message)
      setPhase('failed')
    }
  }

  // Members of themes that are gone (merged by hand meanwhile) drop out; a group under 2 disappears.
  const live = groups
    .map((g) => ({ ...g, members: g.members.filter((m) => themeIds.has(m.id)) }))
    .filter((g) => g.members.length >= 2)
  const accepted = live.filter((g) => decisions[g.id] === 'accept')
  const toCheck = live.filter((g) => !decisions[g.id])
  const highOpen = toCheck.filter((g) => g.band === 'High')
  const merging = accepted.reduce((n, g) => n + g.members.length, 0)
  const after = totalThemes - merging + accepted.length

  const decide = (id: string, d: Decision) =>
    setDecisions((prev) => {
      const next = { ...prev }
      if (next[id] === d) delete next[id]
      else next[id] = d
      return next
    })
  const edit = (id: string, change: Partial<GroupSuggestion>) => setGroups((gs) => gs.map((g) => (g.id === id ? { ...g, ...change } : g)))

  async function apply() {
    setBusy(true)
    setError(null)
    const text = `Done: ${merging} themes became ${accepted.length} group${accepted.length === 1 ? '' : 's'}, so the list now has ${after} themes. One Undo reverses them all.`
    try {
      const token = await onApply(
        accepted.map((g) => ({ name: g.name.trim() || g.members[0].label, theme_ids: g.members.map((m) => m.id) })),
        `Merged ${merging} themes into ${accepted.length} group${accepted.length === 1 ? '' : 's'}.`,
      )
      setApplied({ token, text })
      setPhase('applied')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="tg" aria-labelledby="tg-title">
      <div className="tg-head">
        <div>
          <h3 id="tg-title" className="tg-title"><Layers size={20} {...ICON} />Group matching themes</h3>
          <p className="te-note">Claude spots themes that mean the same. You check.</p>
        </div>
        {(phase === 'review' || phase === 'failed') && (
          <button type="button" className="te-btn" onClick={() => { setPhase('idle'); setGroups([]); setDecisions({}); setError(null) }}>
            <RefreshCw size={16} {...ICON} />Start over
          </button>
        )}
      </div>

      <div aria-live="polite">
        {phase === 'idle' && (
          <div className="tg-idle">
            <ol className="tg-steps">
              <li title="Claude reads each theme's name, size and three masked sample answers."><Sparkles size={16} {...ICON} />Claude reads the topics</li>
              <ChevronDown size={14} {...ICON} className="tg-step-sep" />
              <li title="It proposes groups of themes that mean the same, with a reason and a confidence."><Layers size={16} {...ICON} />It proposes groups</li>
              <ChevronDown size={14} {...ICON} className="tg-step-sep" />
              <li title="Nothing merges until you accept groups and apply them."><Check size={16} {...ICON} />You double-check</li>
            </ol>
            <div className="te-buttons">
              <button type="button" className="te-btn is-primary" onClick={() => void find()}><Sparkles size={18} {...ICON} />Find matches</button>
              <button type="button" className="te-link tg-disclose" aria-expanded={showPayload} onClick={() => setShowPayload(!showPayload)}>
                <Lock size={14} {...ICON} />{showPayload ? 'Hide what Claude sees' : 'What Claude sees'}
              </button>
            </div>
            {showPayload && <PayloadPanel payload={payload} />}
          </div>
        )}

        {phase === 'running' && (
          <div className="tg-running" role="status">
            <Loader size={18} {...ICON} className="tg-spin" />
            <div>
              <div className="tg-strong">Claude is reading the topics</div>
              <div className="te-note">{totalThemes} themes, a few seconds.</div>
            </div>
            <span className="tg-bar" aria-hidden="true"><span /></span>
          </div>
        )}

        {phase === 'failed' && (
          <div className="tg-failed">
            <p className="te-error" role="alert">{error ?? 'Could not reach Claude. Try again.'}</p>
            <button type="button" className="te-btn" onClick={() => void find()}><RefreshCw size={16} {...ICON} />Try again</button>
          </div>
        )}

        {phase === 'applied' && applied && (
          <p className="tg-done"><CircleCheck size={18} {...ICON} />{applied.text}</p>
        )}
      </div>

      {phase === 'review' && (
        <>
          <div className="tg-summary">
            <span>
              {live.length === 0 ? 'No matching themes found.' : `${live.length} group${live.length === 1 ? '' : 's'} found. ${toCheck.length} still to check.`}
              {result?.cached && <span className="te-note"> From the last run: the themes have not changed.</span>}
            </span>
            {live.some((g) => g.band === 'High') && (
              <button type="button" className="te-btn" disabled={highOpen.length === 0}
                onClick={() => setDecisions((d) => ({ ...d, ...Object.fromEntries(highOpen.map((g) => [g.id, 'accept' as const])) }))}>
                <Check size={16} {...ICON} />{highOpen.length ? `Accept all High (${highOpen.length})` : 'High groups accepted'}
              </button>
            )}
          </div>
          <ul className="tg-groups">
            {live.map((g) => (
              <GroupRow
                key={g.id} group={g} decision={decisions[g.id]} open={open.has(g.id)}
                onDecide={(d) => decide(g.id, d)} onRename={(name) => edit(g.id, { name })}
                onToggleAnswers={() => setOpen((o) => { const n = new Set(o); if (n.has(g.id)) n.delete(g.id); else n.add(g.id); return n })}
                onRemove={(themeId) => edit(g.id, { members: groups.find((x) => x.id === g.id)!.members.filter((m) => m.id !== themeId) })}
              />
            ))}
          </ul>
          {result && result.kept_apart.length > 0 && (
            <p className="tg-apart">
              <Info size={14} {...ICON} /><span className="tg-strong">Left apart on purpose.</span>{' '}
              {result.kept_apart.map((k, i) => (
                <span key={i}>{k.names.join(' and ')}{k.reason ? `: ${k.reason}` : ''}{i < result.kept_apart.length - 1 ? ' ' : ''}</span>
              ))}
            </p>
          )}
          {error && <p className="te-error" role="alert">{error}</p>}
          <div className={`tg-apply${accepted.length ? ' is-ready' : ''}`}>
            <span>
              {accepted.length
                ? `${accepted.length} group${accepted.length === 1 ? '' : 's'} accepted. ${merging} themes become ${accepted.length}. The list goes from ${totalThemes} to ${after} themes.`
                : 'Accept the groups you agree with, then apply them together.'}
            </span>
            <button type="button" className="te-btn is-primary" disabled={!accepted.length || busy} onClick={() => void apply()}>
              <Merge size={18} {...ICON} />Apply {accepted.length || ''} merge{accepted.length === 1 ? '' : 's'}
            </button>
          </div>
        </>
      )}
    </section>
  )
}

function Badge({ band, confidence }: { band: GroupSuggestion['band']; confidence: number }) {
  const Icon = band === 'High' ? ShieldCheck : band === 'Medium' ? Shield : ShieldAlert
  return <span className={`tg-badge is-${band.toLowerCase()}`}><Icon size={14} {...ICON} />{band} {confidence}%</span>
}

function GroupRow({ group, decision, open, onDecide, onRename, onToggleAnswers, onRemove }: {
  group: GroupSuggestion
  decision: Decision | undefined
  open: boolean
  onDecide: (d: Decision) => void
  onRename: (name: string) => void
  onToggleAnswers: () => void
  onRemove: (themeId: number) => void
}) {
  const share = Math.round(group.members.reduce((n, m) => n + m.share, 0) * 10) / 10
  const state = decision === 'accept' ? 'Accepted' : decision === 'skip' ? 'Skipped' : 'To check'
  const StateIcon = decision === 'accept' ? CircleCheck : decision === 'skip' ? X : Circle
  return (
    <li className={`tg-group${decision === 'accept' ? ' is-accepted' : ''}${decision === 'skip' ? ' is-skipped' : ''}`}>
      <div className="tg-group-top">
        <Badge band={group.band} confidence={group.confidence} />
        <span className="te-note">{group.members.length} themes, {share}% of answers</span>
        <span className={`tg-state${decision === 'skip' ? ' is-struck' : ''}`}><StateIcon size={14} {...ICON} />{state}</span>
      </div>
      <input className="tg-name" aria-label="Group name" value={group.name} onChange={(e) => onRename(e.target.value)} />
      {group.reason && <p className="tg-reason">{group.reason}</p>}
      {group.similarity === null && <p className="te-note">Similarity not checked: these themes were built before it was stored.</p>}
      <ul className="tg-members">
        {group.members.map((m) => (
          <li key={m.id} className="tg-pill">
            {m.label}<span className="te-num">{m.share}%</span>
            <button type="button" className="tg-pill-x" onClick={() => onRemove(m.id)}
              aria-label={`Take ${m.label} out of this group`} title={`Take ${m.label} out of this group`}>
              <X size={14} {...ICON} />
            </button>
          </li>
        ))}
      </ul>
      <div className="te-buttons">
        <button type="button" className="te-btn is-small" aria-pressed={decision === 'accept'} onClick={() => onDecide('accept')}>
          <Check size={16} {...ICON} />Accept
        </button>
        <button type="button" className="te-btn is-small" aria-pressed={decision === 'skip'} title="Not a match" onClick={() => onDecide('skip')}>
          <X size={16} {...ICON} />Skip
        </button>
        <button type="button" className="te-btn is-small" aria-expanded={open} onClick={onToggleAnswers}>
          <Eye size={16} {...ICON} />{open ? 'Hide' : 'Answers'}
        </button>
      </div>
      {open && (
        <ul className="tg-answers">
          {group.members.map((m) => (
            <li key={m.id}>
              <div className="te-samples-name">{m.label} <span className="te-note">{fmt(m.size)} answers</span></div>
              {m.samples.map((a, i) => <blockquote key={i}>{a}</blockquote>)}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function PayloadPanel({ payload }: { payload: GroupingPayload | null }) {
  if (!payload) return <p className="te-note" role="status">Loading what would be sent…</p>
  const example = payload.payload.themes[0]
  return (
    <div className="tg-payload">
      <p className="te-note">
        Sent for each of the {payload.themes} themes: its name, answer count, share and 3 sample answers, with names,
        emails, phone numbers and other numbers masked. Not sent: the rest of the file, row ids or any other column.
        About {fmt(payload.words)} words in all. One theme, exactly as sent:
      </p>
      {example && <pre className="tg-pre">{JSON.stringify(example, null, 2)}</pre>}
    </div>
  )
}

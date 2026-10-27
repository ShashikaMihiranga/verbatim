import type { Job } from './jobsApi'

// Steps, tips and timing for the waiting card (ReportWaiting.tsx); the step names are the theme build's own
// (app/api_themes.py build_themes).
export const STEPS = [
  { name: 'Turning answers into vectors', desc: 'Reading the meaning of every masked answer, so similar answers sit close together.' },
  { name: 'Naming each group', desc: 'Grouping similar answers and giving each group a clear name.' },
  { name: 'Finding sub-themes', desc: 'Looking inside each theme for smaller patterns.' },
  { name: 'Naming sub-themes', desc: 'Giving each sub-theme a name.' },
  { name: 'Scoring tone', desc: 'Checking how positive or negative the wording is.' },
]
export const TIPS = [
  'Every theme links back to real answers. Use "See answers" on any card.',
  'Names, emails and numbers are masked before your answers are read.',
  'When it is ready you can merge, split and rename themes, and undo any change.',
  'Claude only sees a few masked sample answers, never your whole file.',
]
export const SLOW_MS = 2 * 60_000 // "taking a little longer than usual"
export const TIMEOUT_MS = 5 * 60_000 // "you do not have to wait here"
// Index 0-4 of the step the job reports; 5 when it is done. "Starting" and anything unknown count as step 1.
export function stepIndex(job: Job): number {
  if (job.status === 'done') return 5
  const i = STEPS.findIndex((s) => s.name === job.step)
  return i < 0 ? 0 : i
}

export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

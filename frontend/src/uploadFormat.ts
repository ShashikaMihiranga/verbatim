// Small text helpers for the Uploads page.

export function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// "Uploaded 2 days ago": minutes, hours, days, then weeks; older than about two months shows the date.
export function uploadedAgo(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const min = Math.max(0, Math.round((now - t) / 60_000))
  const say = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'} ago`
  if (min < 1) return 'just now'
  if (min < 60) return say(min, 'minute')
  const h = Math.round(min / 60)
  if (h < 24) return say(h, 'hour')
  const d = Math.round(h / 24)
  if (d < 14) return say(d, 'day')
  if (d < 60) return say(Math.round(d / 7), 'week')
  return `on ${uploadedOn(iso)}`
}

export function uploadedOn(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
}

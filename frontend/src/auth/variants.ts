// The server picks which sign-in design a visitor sees (GET /api/signin-variant) so the designs can be compared.
export type Variant = 'a' | 'b' | 'c' | 'd'
export const VARIANTS: readonly Variant[] = ['a', 'b', 'c', 'd']
export const DEFAULT_VARIANT: Variant = 'a'

export function parseVariant(value: unknown): Variant {
  return typeof value === 'string' && (VARIANTS as readonly string[]).includes(value) ? (value as Variant) : DEFAULT_VARIANT
}

const KEY = 'verbatim.signin-variant'

// One fetch per visit: the choice is kept for the browser tab session, so a refresh does not re-roll or re-count it.
export async function loadVariant(): Promise<Variant> {
  try {
    const saved = sessionStorage.getItem(KEY)
    if (saved) return parseVariant(saved)
  } catch {
    /* storage blocked: carry on */
  }
  let variant = DEFAULT_VARIANT
  try {
    const r = await fetch('/api/signin-variant', { cache: 'no-store' })
    if (r.ok) variant = parseVariant((await r.json())?.variant)
  } catch {
    /* offline or server error: fall back to design A */
  }
  try {
    sessionStorage.setItem(KEY, variant)
  } catch {
    /* ignore */
  }
  return variant
}

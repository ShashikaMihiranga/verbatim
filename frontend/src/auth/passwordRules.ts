// Password rules shown live on the sign-up and reset forms. Clerk enforces its own rules as well
// (and checks breached passwords); these give instant, plain feedback.
export const MIN_LENGTH = 12

const COMMON = [
  'password', 'passw0rd', 'letmein', 'welcome', 'qwerty', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm',
  'iloveyou', 'admin', 'administrator', 'monkey', 'dragon', 'football', 'baseball', 'sunshine',
  'princess', 'superman', 'trustno1', 'changeme', 'abc123', 'master', 'login', 'starwars',
  'freedom', 'whatever', 'shadow', 'michael', 'jennifer', 'computer', 'summer', 'winter',
  'verbatim', 'company', 'secret', 'internet', 'passwordpassword', 'welcomewelcome',
]

const SEQUENCES = ['0123456789', 'abcdefghijklmnopqrstuvwxyz', 'qwertyuiopasdfghjklzxcvbnm']

export function isCommonPassword(pw: string): boolean {
  const lower = pw.toLowerCase()
  const letters = lower.replace(/[^a-z]/g, '')
  const stripped = lower.replace(/[\d\W_]+$/g, '') // "password2024!" is still "password"
  if (COMMON.includes(lower) || COMMON.includes(stripped) || COMMON.includes(letters)) return true
  if (letters.length >= 6 && COMMON.some((c) => c.length >= 6 && letters === c.repeat(Math.ceil(letters.length / c.length)).slice(0, letters.length))) {
    return true
  }
  if (new Set(pw).size < 5) return true // aaaaaaaaaaaa1, 1212121212ab
  const compact = lower.replace(/[\W_]/g, '')
  return SEQUENCES.some((s) => s.includes(compact) && compact.length >= 6)
}

export interface Rule {
  id: 'length' | 'mix' | 'common'
  label: string
  met: boolean
}

export function checkPassword(pw: string): Rule[] {
  return [
    { id: 'length', label: `At least ${MIN_LENGTH} characters`, met: pw.length >= MIN_LENGTH },
    { id: 'mix', label: 'Letters and numbers', met: /[A-Za-z]/.test(pw) && /\d/.test(pw) },
    { id: 'common', label: 'Not a common password', met: pw.length > 0 && !isCommonPassword(pw) },
  ]
}

export function passwordOk(pw: string): boolean {
  return checkPassword(pw).every((r) => r.met)
}

export function validEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim()) && email.length <= 254
}

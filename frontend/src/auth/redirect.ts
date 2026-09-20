// Only ever go to a path inside this app (no open redirects through router state or query strings).
export const DEFAULT_AFTER_SIGN_IN = '/upload'

export function safeDestination(from: unknown): string {
  if (typeof from !== 'string') return DEFAULT_AFTER_SIGN_IN
  if (!from.startsWith('/') || from.startsWith('//') || from.includes('\\')) return DEFAULT_AFTER_SIGN_IN
  if (from.startsWith('/sign-') || from === '/verify' || from === '/forgot-password' || from === '/sso-callback') {
    return DEFAULT_AFTER_SIGN_IN
  }
  return from
}

// What to do after Clerk answers a password sign-in. Clerk's Client Trust asks for an emailed code the
// first time an account signs in on a new device (status needs_second_factor with an email_code factor),
// so a correct password alone is not always enough.
export type SignInStep =
  | { kind: 'done'; sessionId: string }
  | { kind: 'email_code'; emailAddressId?: string; sentTo?: string }
  | { kind: 'unsupported'; status: string | null }

interface SignInResult {
  status: string | null
  createdSessionId?: string | null
  supportedSecondFactors?: { strategy: string; emailAddressId?: string; safeIdentifier?: string }[] | null
}

export function nextSignInStep(res: SignInResult): SignInStep {
  if (res.status === 'complete' && res.createdSessionId) return { kind: 'done', sessionId: res.createdSessionId }
  if (res.status === 'needs_second_factor' || res.status === 'needs_client_trust') {
    const email = res.supportedSecondFactors?.find((f) => f.strategy === 'email_code')
    if (email) return { kind: 'email_code', emailAddressId: email.emailAddressId, sentTo: email.safeIdentifier }
  }
  return { kind: 'unsupported', status: res.status }
}

export const UNSUPPORTED_STEP =
  'This account needs a sign-in step Verbatim does not support yet. Try Forgot password, or continue with Google or Microsoft.'

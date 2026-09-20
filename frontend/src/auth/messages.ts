export const NOT_RIGHT = 'Email or password is not right.'
export const SOMETHING_WRONG = 'Something went wrong. Please try again.'

// Never say whether an email has an account: unknown email and wrong password read the same.
export function clerkCode(err: unknown): string | undefined {
  const first = (err as { errors?: { code?: string }[] } | null)?.errors?.[0]
  return first?.code
}

export function signInMessage(err: unknown): string {
  switch (clerkCode(err)) {
    case 'form_identifier_not_found':
    case 'form_password_incorrect':
    case 'form_param_format_invalid':
    case 'strategy_for_user_invalid':
    case 'form_password_pwned':
      return NOT_RIGHT
    case 'too_many_requests':
    case 'rate_limit_exceeded':
      return 'Too many tries. Wait a minute and try again.'
    default:
      return SOMETHING_WRONG
  }
}

export function codeMessage(err: unknown): string {
  switch (clerkCode(err)) {
    case 'form_code_incorrect':
      return 'That code is not right. Check it and try again.'
    case 'verification_expired':
    case 'verification_failed':
      return 'That code has expired. Send a new one.'
    case 'too_many_requests':
    case 'rate_limit_exceeded':
      return 'Too many tries. Wait a minute and try again.'
    default:
      return SOMETHING_WRONG
  }
}


export function splitName(full: string): { firstName: string; lastName?: string } {
  const [firstName, ...rest] = full.trim().split(/\s+/)
  return rest.length ? { firstName, lastName: rest.join(' ') } : { firstName }
}

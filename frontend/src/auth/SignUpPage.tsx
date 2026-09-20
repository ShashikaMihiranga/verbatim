import { useSignUp } from '@clerk/clerk-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { passwordOk, validEmail } from './passwordRules'
import { SOMETHING_WRONG, clerkCode, splitName } from './messages'
import { Divider, Field, FormError, Logo, OAuthButtons, PasswordField, RuleList } from './ui'
import './auth.css'

function signUpMessage(err: unknown): string {
  switch (clerkCode(err)) {
    case 'form_identifier_exists':
      // Do not confirm that the address already has an account.
      return 'We could not create that account. If you already have one, sign in or reset your password.'
    case 'form_password_pwned':
      return 'That password has appeared in a data breach. Choose a different one.'
    case 'form_password_length_too_short':
    case 'form_password_not_strong_enough':
    case 'form_password_size_in_bytes_exceeded':
      return 'Choose a stronger password that meets the rules below.'
    case 'too_many_requests':
    case 'rate_limit_exceeded':
      return 'Too many tries. Wait a minute and try again.'
    default:
      return SOMETHING_WRONG
  }
}

export default function SignUpPage() {
  const { isLoaded, signUp } = useSignUp()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [terms, setTerms] = useState(false)
  const [touched, setTouched] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const errorRef = useRef<HTMLDivElement>(null)
  const nameRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    nameRef.current?.focus()
  }, [])
  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  const nameErr = touched && !name.trim() ? 'Enter your full name.' : ''
  const emailErr = touched && !validEmail(email) ? 'Enter a valid work email.' : ''

  async function submit(e: FormEvent) {
    e.preventDefault()
    setTouched(true)
    if (!isLoaded || busy) return
    if (!name.trim() || !validEmail(email)) return
    if (!passwordOk(password)) {
      setError('Choose a password that meets all three rules below.')
      return
    }
    if (!terms) {
      setError('Please agree to the terms to continue.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await signUp.create({ emailAddress: email.trim(), password, ...splitName(name) })
      await signUp.prepareEmailAddressVerification({ strategy: 'email_code' })
      navigate('/verify')
    } catch (err) {
      setError(signUpMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function oauth(strategy: 'oauth_google' | 'oauth_microsoft') {
    if (!isLoaded) return
    try {
      await signUp.authenticateWithRedirect({ strategy, redirectUrl: '/sso-callback', redirectUrlComplete: '/upload' })
    } catch {
      setError(SOMETHING_WRONG)
    }
  }

  return (
    <div className="auth-center">
      <main className="auth-card">
        <Logo />
        <form onSubmit={submit} noValidate className="auth-form" aria-labelledby="signup-title">
          <h1 id="signup-title">Create your account</h1>
          <p className="lead">Free to start. No card needed.</p>
          <FormError message={error} ref={errorRef} />
          <Field label="Full name" autoComplete="name" placeholder="Your name" value={name} onChange={setName} ref={nameRef} error={nameErr} required maxLength={120} />
          <Field label="Work email" type="email" inputMode="email" autoComplete="email" placeholder="sam@company.com" value={email} onChange={setEmail} error={emailErr} required />
          <PasswordField label="Password" autoComplete="new-password" value={password} onChange={setPassword} required maxLength={128} />
          <RuleList password={password} />
          <label className="auth-check">
            <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
            <span>I agree to the terms of use and the privacy notice.</span>
          </label>
          {/* Clerk bot protection renders its challenge here */}
          <div id="clerk-captcha" />
          <button type="submit" className="auth-btn primary" disabled={busy || !isLoaded}>
            {busy ? 'Creating account...' : 'Create account'}
          </button>
          <Divider />
          <OAuthButtons onPick={oauth} disabled={!isLoaded} />
          <p className="auth-foot">
            Already have an account? <Link to="/sign-in">Sign in</Link>
          </p>
        </form>
      </main>
    </div>
  )
}

import { useSignIn } from '@clerk/clerk-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { NOT_RIGHT, SOMETHING_WRONG, signInMessage } from './messages'
import { Divider, Field, FormError, OAuthButtons, PasswordField } from './ui'
import { validEmail } from './passwordRules'
import { safeDestination } from './redirect'

// One form for all four designs. Only the layout around it (SignInPage + SidePanel) changes.
// "Keep me signed in" is left out on purpose: Clerk sets session length in its dashboard, not per sign-in.
export default function SignInForm() {
  const { isLoaded, signIn, setActive } = useSignIn()
  const navigate = useNavigate()
  const location = useLocation()
  const dest = safeDestination((location.state as { from?: string } | null)?.from)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const errorRef = useRef<HTMLDivElement>(null)
  const emailRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    emailRef.current?.focus()
  }, [])
  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!isLoaded || busy) return
    if (!validEmail(email) || !password) {
      setError(NOT_RIGHT)
      return
    }
    setBusy(true)
    setError('')
    try {
      const res = await signIn.create({ identifier: email.trim(), password })
      if (res.status === 'complete' && res.createdSessionId) {
        await setActive({ session: res.createdSessionId })
        navigate(dest, { replace: true })
        return
      }
      setError(SOMETHING_WRONG)
    } catch (err) {
      setError(signInMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function oauth(strategy: 'oauth_google' | 'oauth_microsoft') {
    if (!isLoaded) return
    try {
      await signIn.authenticateWithRedirect({
        strategy,
        redirectUrl: '/sso-callback',
        redirectUrlComplete: dest,
      })
    } catch {
      setError(SOMETHING_WRONG)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="auth-form" aria-labelledby="signin-title">
      <h1 id="signin-title">Sign in</h1>
      <p className="lead">Welcome back. Your projects are private to your workspace.</p>
      <FormError message={error} ref={errorRef} />
      <Field
        label="Email"
        type="email"
        inputMode="email"
        autoComplete="username"
        placeholder="you@company.com"
        value={email}
        onChange={setEmail}
        ref={emailRef}
        required
      />
      <PasswordField label="Password" autoComplete="current-password" value={password} onChange={setPassword} required maxLength={128} />
      <div className="auth-row end">
        <Link to="/forgot-password">Forgot password?</Link>
      </div>
      <button type="submit" className="auth-btn primary" disabled={busy || !isLoaded}>
        {busy ? 'Signing in...' : 'Sign in'}
      </button>
      <Divider />
      <OAuthButtons onPick={oauth} disabled={!isLoaded} />
      <p className="auth-foot">
        New here? <Link to="/sign-up">Create an account</Link>
      </p>
    </form>
  )
}

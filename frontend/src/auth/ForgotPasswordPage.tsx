import { useSignIn } from '@clerk/clerk-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { passwordOk, validEmail } from './passwordRules'
import { SOMETHING_WRONG, codeMessage } from './messages'
import { Field, FormError, Logo, PasswordField, RuleList } from './ui'
import './auth.css'

// Two steps: email us the code, then enter the code with a new password.
// Step 1 always looks like it worked, so this page never reveals whether an email has an account.
export default function ForgotPasswordPage() {
  const { isLoaded, signIn, setActive } = useSignIn()
  const navigate = useNavigate()
  const [step, setStep] = useState<'email' | 'code'>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const errorRef = useRef<HTMLDivElement>(null)
  const firstRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    firstRef.current?.focus()
  }, [step])
  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  async function sendCode(e: FormEvent) {
    e.preventDefault()
    if (!isLoaded || busy) return
    if (!validEmail(email)) {
      setError('Enter the email you signed up with.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await signIn.create({ strategy: 'reset_password_email_code', identifier: email.trim() })
    } catch {
      /* same screen whether or not the account exists */
    }
    setBusy(false)
    setStep('code')
  }

  async function reset(e: FormEvent) {
    e.preventDefault()
    if (!isLoaded || busy) return
    if (!/^\d{6}$/.test(code.trim())) {
      setError('Enter the 6 digit code from your email.')
      return
    }
    if (!passwordOk(password)) {
      setError('Choose a password that meets all three rules below.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const res = await signIn.attemptFirstFactor({ strategy: 'reset_password_email_code', code: code.trim(), password })
      if (res.status === 'complete' && res.createdSessionId) {
        await setActive({ session: res.createdSessionId })
        navigate('/upload', { replace: true })
        return
      }
      setError(SOMETHING_WRONG)
    } catch (err) {
      setError(codeMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-center">
      <main className="auth-card">
        <Logo />
        {step === 'email' ? (
          <form onSubmit={sendCode} noValidate className="auth-form" aria-labelledby="forgot-title">
            <h1 id="forgot-title">Reset your password</h1>
            <p className="lead">Enter your email and we will send you a 6 digit code.</p>
            <FormError message={error} ref={errorRef} />
            <Field label="Email" type="email" inputMode="email" autoComplete="username" placeholder="you@company.com" value={email} onChange={setEmail} ref={firstRef} required />
            <button type="submit" className="auth-btn primary" disabled={busy || !isLoaded}>
              {busy ? 'Sending...' : 'Send code'}
            </button>
            <p className="auth-foot">
              <Link to="/sign-in">Back to sign in</Link>
            </p>
          </form>
        ) : (
          <form onSubmit={reset} noValidate className="auth-form" aria-labelledby="reset-title">
            <h1 id="reset-title">Choose a new password</h1>
            <p className="lead">If that email has an account, a code is on its way. Enter it below.</p>
            <FormError message={error} ref={errorRef} />
            <Field label="Code from your email" inputMode="numeric" autoComplete="one-time-code" placeholder="123456" value={code} onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))} ref={firstRef} maxLength={6} required />
            <PasswordField label="New password" autoComplete="new-password" value={password} onChange={setPassword} required maxLength={128} />
            <RuleList password={password} />
            <button type="submit" className="auth-btn primary" disabled={busy || !isLoaded}>
              {busy ? 'Saving...' : 'Set new password'}
            </button>
            <p className="auth-foot">
              <button type="button" className="auth-link" onClick={() => { setStep('email'); setError('') }}>
                Use a different email
              </button>
            </p>
          </form>
        )}
      </main>
    </div>
  )
}

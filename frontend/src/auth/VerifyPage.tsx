import { useSignUp } from '@clerk/clerk-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { SOMETHING_WRONG, codeMessage } from './messages'
import { Field, FormError, Logo } from './ui'
import './auth.css'

const RESEND_SECONDS = 30

// Step 2 of sign-up: the 6 digit code Clerk emailed. The sign-up in progress lives in Clerk's client state.
export default function VerifyPage() {
  const { isLoaded, signUp, setActive } = useSignUp()
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const [wait, setWait] = useState(0)
  const errorRef = useRef<HTMLDivElement>(null)
  const codeRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    codeRef.current?.focus()
  }, [isLoaded])
  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])
  useEffect(() => {
    if (wait <= 0) return
    const t = setTimeout(() => setWait((w) => w - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])

  const inProgress = isLoaded && signUp && signUp.status !== null && signUp.status !== 'complete'

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!isLoaded || busy) return
    if (!/^\d{6}$/.test(code.trim())) {
      setError('Enter the 6 digit code from your email.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const res = await signUp.attemptEmailAddressVerification({ code: code.trim() })
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

  async function resend() {
    if (!isLoaded || wait > 0) return
    setError('')
    try {
      await signUp.prepareEmailAddressVerification({ strategy: 'email_code' })
      setInfo('We sent a new code.')
      setWait(RESEND_SECONDS)
    } catch (err) {
      setError(codeMessage(err))
    }
  }

  return (
    <div className="auth-center">
      <main className="auth-card">
        <Logo />
        {isLoaded && !inProgress ? (
          <div className="auth-form">
            <h1>Nothing to verify</h1>
            <p className="lead">Start by creating an account, or sign in if you already have one.</p>
            <p className="auth-foot">
              <Link to="/sign-up">Create an account</Link> or <Link to="/sign-in">sign in</Link>
            </p>
          </div>
        ) : (
          <form onSubmit={submit} noValidate className="auth-form" aria-labelledby="verify-title">
            <h1 id="verify-title">Check your email</h1>
            <p className="lead">We sent a 6 digit code to your email address. It works for a few minutes.</p>
            <FormError message={error} ref={errorRef} />
            <Field
              label="Verification code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="123456"
              value={code}
              onChange={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
              ref={codeRef}
              maxLength={6}
              required
            />
            <button type="submit" className="auth-btn primary" disabled={busy || !isLoaded}>
              {busy ? 'Checking...' : 'Verify and continue'}
            </button>
            <p className="auth-foot">
              <button type="button" className="auth-link" onClick={resend} disabled={wait > 0}>
                {wait > 0 ? `Send a new code in ${wait}s` : 'Send a new code'}
              </button>
            </p>
            <p className="sr-only" aria-live="polite">{info}</p>
          </form>
        )}
      </main>
    </div>
  )
}

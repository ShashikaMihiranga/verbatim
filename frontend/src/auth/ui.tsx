import { useId, useState } from 'react'
import type { ReactNode, Ref } from 'react'
import { checkPassword } from './passwordRules'

export function Logo() {
  return (
    <div className="auth-logo" aria-label="Verbatim">
      <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
        <rect x="1" y="12" width="4" height="9" rx="1" fill="var(--t2)" />
        <rect x="9" y="6" width="4" height="15" rx="1" fill="var(--t4)" />
        <rect x="17" y="1" width="4" height="20" rx="1" fill="var(--t1)" />
      </svg>
      <span>Verbatim</span>
    </div>
  )
}

export function FormError({ message, ref }: { message: string; ref: Ref<HTMLDivElement> }) {
  // Always mounted so screen readers announce changes; focus moves here after a failed submit.
  return (
    <div className={message ? 'auth-error on' : 'auth-error'} aria-live="polite" tabIndex={-1} ref={ref}>
      {message}
    </div>
  )
}

interface FieldProps {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  autoComplete?: string
  placeholder?: string
  error?: string
  hint?: string
  inputMode?: 'text' | 'email' | 'numeric'
  required?: boolean
  maxLength?: number
  ref?: Ref<HTMLInputElement>
  action?: ReactNode
}

export function Field({
  label, value, onChange, type = 'text', autoComplete, placeholder, error, hint, inputMode, required, maxLength = 256, ref, action,
}: FieldProps) {
  const id = useId()
  const note = error || hint
  return (
    <div className={error ? 'auth-field invalid' : 'auth-field'}>
      <label htmlFor={id}>{label}</label>
      <div className="auth-input">
        <input
          id={id}
          ref={ref}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          inputMode={inputMode}
          required={required}
          maxLength={maxLength}
          aria-invalid={error ? true : undefined}
          aria-describedby={note ? `${id}-note` : undefined}
          spellCheck={false}
          autoCapitalize="none"
        />
        {action}
      </div>
      {note && (
        <p id={`${id}-note`} className={error ? 'note err' : 'note'}>
          {note}
        </p>
      )}
    </div>
  )
}

export function PasswordField(p: Omit<FieldProps, 'type' | 'action'>) {
  const [show, setShow] = useState(false)
  return (
    <Field
      {...p}
      type={show ? 'text' : 'password'}
      action={
        <button type="button" className="auth-toggle" aria-pressed={show} onClick={() => setShow((s) => !s)}>
          {show ? 'Hide' : 'Show'}
          <span className="sr-only"> password</span>
        </button>
      }
    />
  )
}

export function RuleList({ password }: { password: string }) {
  const rules = checkPassword(password)
  return (
    <ul className="auth-rules" aria-label="Password rules">
      {rules.map((r) => (
        <li key={r.id} className={r.met ? 'met' : ''}>
          <span aria-hidden="true">{r.met ? '✓' : '○'}</span> {r.label}
          <span className="sr-only">{r.met ? ' (met)' : ' (not met yet)'}</span>
        </li>
      ))}
    </ul>
  )
}

export function Divider() {
  return (
    <div className="auth-or" role="separator">
      <span>or</span>
    </div>
  )
}

export function OAuthButtons({ onPick, disabled }: { onPick: (s: 'oauth_google' | 'oauth_microsoft') => void; disabled?: boolean }) {
  return (
    <div className="auth-oauth">
      <button type="button" className="auth-btn ghost" disabled={disabled} onClick={() => onPick('oauth_google')}>
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
          <path fill="#4285F4" d="M17.6 9.2c0-.6-.1-1.2-.2-1.7H9v3.3h4.8a4.1 4.1 0 0 1-1.8 2.7v2.2h2.9c1.7-1.6 2.7-3.9 2.7-6.5z" />
          <path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.8.9-3.1.9-2.4 0-4.4-1.6-5.1-3.8H.9v2.3A9 9 0 0 0 9 18z" />
          <path fill="#FBBC05" d="M3.9 10.7a5.4 5.4 0 0 1 0-3.4V5H.9a9 9 0 0 0 0 8z" />
          <path fill="#EA4335" d="M9 3.6c1.3 0 2.5.5 3.4 1.3l2.6-2.6A9 9 0 0 0 .9 5l3 2.3C4.600 5.200 6.600 3.600 9 3.600z" />
        </svg>
        Continue with Google
      </button>
      <button type="button" className="auth-btn ghost" disabled={disabled} onClick={() => onPick('oauth_microsoft')}>
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
          <rect x="1" y="1" width="7.500" height="7.500" fill="#F25022" />
          <rect x="9.500" y="1" width="7.500" height="7.500" fill="#7FBA00" />
          <rect x="1" y="9.500" width="7.500" height="7.500" fill="#00A4EF" />
          <rect x="9.500" y="9.500" width="7.500" height="7.500" fill="#FFB900" />
        </svg>
        Continue with Microsoft
      </button>
    </div>
  )
}

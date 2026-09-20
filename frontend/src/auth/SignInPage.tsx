import { useAuth } from '@clerk/clerk-react'
import { useEffect, useRef, useState } from 'react'
import { Navigate } from 'react-router-dom'
import SidePanel from './SidePanel'
import SignInForm from './SignInForm'
import { Logo } from './ui'
import { loadVariant } from './variants'
import type { Variant } from './variants'
import './auth.css'

// Layout only: the server picks the design (A to D) once per visit, the form is the same for all.
export function SignInLayout({ variant, children }: { variant: Variant | null; children: React.ReactNode }) {
  return (
    <div className={`auth-split variant-${variant ?? 'pending'}`}>
      <main className="auth-main">
        <Logo />
        {children}
      </main>
      {variant ? <SidePanel variant={variant} /> : <aside className="auth-side" aria-hidden="true" />}
    </div>
  )
}

export default function SignInPage() {
  const { isLoaded, isSignedIn } = useAuth()
  const [variant, setVariant] = useState<Variant | null>(null)
  const asked = useRef(false)

  useEffect(() => {
    if (asked.current) return // once per visit, even under StrictMode
    asked.current = true
    loadVariant().then(setVariant)
  }, [])

  if (isLoaded && isSignedIn) return <Navigate to="/upload" replace />
  return (
    <SignInLayout variant={variant}>
      <SignInForm />
    </SignInLayout>
  )
}

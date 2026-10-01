import { AuthenticateWithRedirectCallback, useAuth } from '@clerk/clerk-react'
import { useLayoutEffect } from 'react'
import type { ReactNode } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { registerAuthBridge } from '../authFetch'
import { clerkConfigured, devUserAllowed } from '../authConfig'
import { Logo } from './ui'
import './auth.css'

export function NotConfigured() {
  return (
    <div className="auth-center">
      <main className="auth-card">
        <Logo />
        <div className="auth-form">
          <h1>Sign-in is not configured yet</h1>
          <p className="lead">
            This copy of Verbatim has no sign-in provider connected, so accounts are switched off. If you run this site,
            follow &ldquo;Set up Clerk&rdquo; in the README.
          </p>
          <p className="auth-foot">
            <Link to="/">Back to home</Link>
          </p>
        </div>
      </main>
    </div>
  )
}

function Loading() {
  return (
    <p className="muted" role="status" style={{ padding: 32 }}>
      Loading...
    </p>
  )
}

function ClerkGuard({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth()
  const location = useLocation()
  if (!isLoaded) return <Loading />
  if (!isSignedIn) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

// Signed-out visitors go to /sign-in. Without a Clerk key nothing is signed in, so it also redirects.
export function RequireAuth({ children }: { children: ReactNode }) {
  // Local-only escape hatch (see authConfig.ts's own comment): skips Clerk entirely, before even
  // checking clerkConfigured, so it works whether or not a real Clerk key also happens to be set.
  if (devUserAllowed) return <>{children}</>
  if (!clerkConfigured) return <Navigate to="/sign-in" replace />
  return <ClerkGuard>{children}</ClerkGuard>
}

// Gives the API helpers the session token and a router-aware "go to sign-in" for 401 answers.
export function ClerkBridge() {
  const { getToken } = useAuth()
  const navigate = useNavigate()
  useLayoutEffect(() => {
    // Layout effects run before any child effect, so the first /api call already has a token.
    registerAuthBridge({
      getToken: () => getToken(),
      onUnauthorized: () => navigate('/sign-in', { replace: true }),
    })
  }, [getToken, navigate])
  return null
}

export function SsoCallback() {
  return (
    <>
      <Loading />
      <AuthenticateWithRedirectCallback signInFallbackRedirectUrl="/upload" signUpFallbackRedirectUrl="/upload" />
    </>
  )
}

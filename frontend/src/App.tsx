import { useAuth, useUser } from '@clerk/clerk-react'
import type { ReactNode } from 'react'
import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import CheckColumns from './CheckColumns'
import Cleaning from './Cleaning'
import Upload from './Upload'
import Landing from './home/Landing'
import './auth/auth.css'
import { clerkConfigured } from './authConfig'
import ForgotPasswordPage from './auth/ForgotPasswordPage'
import SignInPage from './auth/SignInPage'
import SignUpPage from './auth/SignUpPage'
import VerifyPage from './auth/VerifyPage'
import { ClerkBridge, NotConfigured, RequireAuth, SsoCallback } from './auth/guards'
import { useSignOut } from './auth/useSignOut'

// Signed-in visitors skip the landing page and go straight to Upload.
function ClerkHome() {
  const { isLoaded, isSignedIn } = useAuth()
  if (isLoaded && isSignedIn) return <Navigate to="/upload" replace />
  return <Landing />
}

const Placeholder = ({ title }: { title: string }) => (
  <>
    <h1>{title}</h1>
    <p className="muted">Coming soon.</p>
  </>
)

function SignOutControl() {
  const signOut = useSignOut()
  const { user } = useUser()
  const who = user?.primaryEmailAddress?.emailAddress ?? user?.firstName ?? ''
  return (
    <span className="account">
      {who && <span className="muted who">{who}</span>}
      <button type="button" className="auth-link" onClick={() => void signOut()}>
        Sign out
      </button>
    </span>
  )
}

function ClerkAccount() {
  const { isLoaded, isSignedIn } = useAuth()
  if (!isLoaded) return null
  if (isSignedIn) return <SignOutControl />
  return <Link to="/sign-in">Sign in</Link>
}

function Shell() {
  return (
    <div className="page">
      <nav className="top" aria-label="Main">
        <Link to="/">Home</Link>
        <Link to="/projects">Projects</Link>
        <Link to="/upload">Upload</Link>
        <Link to="/report">Report</Link>
        <span className="spacer" />
        {clerkConfigured ? <ClerkAccount /> : <Link to="/sign-in">Sign in</Link>}
      </nav>
      <Outlet />
    </div>
  )
}

const guard = (el: ReactNode) => <RequireAuth>{el}</RequireAuth>

export default function App() {
  const authRoutes = clerkConfigured ? (
    <>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/sign-up" element={<SignUpPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/verify" element={<VerifyPage />} />
      <Route path="/sso-callback" element={<SsoCallback />} />
    </>
  ) : (
    ['/sign-in', '/sign-up', '/forgot-password', '/verify', '/sso-callback'].map((p) => (
      <Route key={p} path={p} element={<NotConfigured />} />
    ))
  )
  return (
    <>
      {clerkConfigured && <ClerkBridge />}
      <Routes>
        {authRoutes}
        <Route path="/" element={clerkConfigured ? <ClerkHome /> : <Landing />} />
        <Route element={<Shell />}>
          <Route path="/projects" element={guard(<Placeholder title="Projects" />)} />
          <Route path="/upload" element={guard(<Upload />)} />
          <Route path="/check-columns" element={guard(<CheckColumns />)} />
          <Route path="/cleaning" element={guard(<Cleaning />)} />
          <Route path="/report" element={guard(<Placeholder title="Report" />)} />
          <Route path="*" element={<Placeholder title="Not found" />} />
        </Route>
      </Routes>
    </>
  )
}

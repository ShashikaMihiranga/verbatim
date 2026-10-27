import { useAuth, useUser } from '@clerk/clerk-react'
import type { ReactNode } from 'react'
import { Link, NavLink, Outlet, Route, Routes } from 'react-router-dom'
import AcceptInvite from './AcceptInvite'
import CheckColumns from './CheckColumns'
import Cleaning from './Cleaning'
import Jobs from './Jobs'
import Projects from './Projects'
import SharedReport from './SharedReport'
import Themes from './Themes'
import Upload from './Upload'
import Landing from './home/HomePage'
import SampleReport from './SampleReport'
import { Logo } from './home/homeArt'
import './auth/auth.css'
import { clerkConfigured, devUserAllowed } from './authConfig'
import ForgotPasswordPage from './auth/ForgotPasswordPage'
import SignInPage from './auth/SignInPage'
import SignUpPage from './auth/SignUpPage'
import VerifyPage from './auth/VerifyPage'
import { ClerkBridge, NotConfigured, RequireAuth, SsoCallback } from './auth/guards'
import { useSignOut } from './auth/useSignOut'

const Placeholder = ({ title }: { title: string }) => (
  <>
    <h1>{title}</h1>
    <p className="muted">Coming soon.</p>
  </>
)

// The signed-in person: a round initial, their email, Sign out (Uploads_UIHandoff.md top bar).
function Who({ name }: { name: string }) {
  return (
    <span className="who">
      <span className="avatar" aria-hidden="true">{(name.trim()[0] ?? '?').toUpperCase()}</span>
      <span className="muted who-name">{name}</span>
    </span>
  )
}

function SignOutControl() {
  const signOut = useSignOut()
  const { user } = useUser()
  const who = user?.primaryEmailAddress?.emailAddress ?? user?.firstName ?? ''
  return (
    <span className="account">
      {who && <Who name={who} />}
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
        <Link to="/" className="brand" aria-label="Verbatim home"><Logo size={30} /><span>Verbatim</span></Link>
        <span className="links">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/upload">Uploads</NavLink>
          <NavLink to="/projects">Projects</NavLink>
          <NavLink to="/report">Reports</NavLink>
          <NavLink to="/jobs">Jobs</NavLink>
        </span>
        <span className="spacer" />
        {devUserAllowed ? (
          <span className="account"><Who name="Dev user (Clerk bypassed)" /></span>
        ) : clerkConfigured ? (
          <ClerkAccount />
        ) : (
          <Link to="/sign-in">Sign in</Link>
        )}
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
        <Route
          path="/"
          element={<Landing />}
        />
        {/* Sharing/roles (docs/TODO.md, fixed 2026-10-22): deliberately OUTSIDE the <Shell/> group below -
            a share link means "no sign-in required", so this page carries none of Shell's signed-in-nav
            assumptions. */}
        <Route path="/shared" element={<SharedReport />} />
        {/* The home page's "See a sample report": public, read-only, from a frozen file (no database). */}
        <Route path="/sample" element={<SampleReport />} />
        {/* The home page for anyone, signed in or not ("/" sends signed-in visitors to Upload). */}
        <Route path="/home" element={<Landing />} />
        <Route element={<Shell />}>
          <Route path="/projects" element={guard(<Projects />)} />
          <Route path="/upload" element={guard(<Upload />)} />
          <Route path="/check-columns" element={guard(<CheckColumns />)} />
          <Route path="/cleaning" element={guard(<Cleaning />)} />
          <Route path="/report" element={guard(<Themes />)} />
          <Route path="/jobs" element={guard(<Jobs />)} />
          <Route path="/accept-invite" element={guard(<AcceptInvite />)} />
          <Route path="*" element={<Placeholder title="Not found" />} />
        </Route>
      </Routes>
    </>
  )
}

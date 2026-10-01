// Public by design: the Clerk publishable key is a build variable (VITE_CLERK_PUBLISHABLE_KEY).
// The Clerk secret key is never used anywhere in this app.
const raw: unknown = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
export const clerkKey: string | null = typeof raw === 'string' && raw.trim() !== '' ? raw.trim() : null
export const clerkConfigured = clerkKey !== null

// Mirrors the backend's own ALLOW_DEV_USER convention exactly (app/auth.py::dev_user_allowed) - a
// build-time flag, never a runtime one, so it can only ever be true when it was baked into THIS build.
// Only ever set in a git-ignored frontend/.env.local (Vite loads it automatically; frontend/.gitignore's
// own `*.local` rule keeps it out of the repo - see README's "Local development without Clerk" section),
// never in Railway's dashboard-configured build variables - same "never in production" guarantee the
// backend flag already relies on. When true, RequireAuth (auth/guards.tsx) skips Clerk entirely and every
// /api call already goes out with no Authorization header regardless (authFetch.ts's default getToken
// returns null), which the backend's own dev user already accepts.
const rawDevUser: unknown = import.meta.env.VITE_ALLOW_DEV_USER
export const devUserAllowed =
  typeof rawDevUser === 'string' && rawDevUser.trim().toLowerCase() === 'true'

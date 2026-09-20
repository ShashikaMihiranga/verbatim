// Public by design: the Clerk publishable key is a build variable (VITE_CLERK_PUBLISHABLE_KEY).
// The Clerk secret key is never used anywhere in this app.
const raw: unknown = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
export const clerkKey: string | null = typeof raw === 'string' && raw.trim() !== '' ? raw.trim() : null
export const clerkConfigured = clerkKey !== null

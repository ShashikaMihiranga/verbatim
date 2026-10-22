import { authFetch } from './authFetch'

// Sharing/roles (docs/TODO.md, fixed 2026-10-22). Owner-only client for every call here except
// `acceptInviteLink` (any signed-in user) and `getPublicReport` (no auth at all - a share link token IS
// the authorization). See app/api_sharing.py's own module docstring for why "invite by email" isn't
// possible (Clerk auth here is JWT-verification only, no user-directory lookup) - an invite LINK that
// grants "editor" to whoever signs in and visits it is the realistic stand-in.

export interface InviteLink {
  id: number
  token: string
  created_at: string
}

export interface Collaborator {
  id: number
  user_id: number
  role: 'editor' | 'viewer'
}

export interface ShareLink {
  id: number
  token: string
  column: string
  expires_at: string | null
  created_at: string
}

async function asError(r: Response): Promise<Error> {
  let msg = `Something went wrong (${r.status}).`
  try {
    const j = await r.json()
    if (typeof j.detail === 'string') msg = j.detail
  } catch {
    /* keep the default message */
  }
  return new Error(msg)
}

export async function createInviteLink(datasetId: number): Promise<InviteLink> {
  const r = await authFetch(`/api/datasets/${datasetId}/invite-links`, { method: 'POST' })
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function listInviteLinks(datasetId: number): Promise<InviteLink[]> {
  const r = await authFetch(`/api/datasets/${datasetId}/invite-links`)
  if (!r.ok) throw await asError(r)
  return (await r.json()).invite_links
}

export async function revokeInviteLink(datasetId: number, linkId: number): Promise<void> {
  const r = await authFetch(`/api/datasets/${datasetId}/invite-links/${linkId}`, { method: 'DELETE' })
  if (!r.ok) throw await asError(r)
}

// Any signed-in user may call this, not just the dataset owner - it's how a recipient actually joins.
export async function acceptInviteLink(token: string): Promise<{ dataset_id: number; role: string }> {
  const r = await authFetch(`/api/invite-links/${token}/accept`, { method: 'POST' })
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function listCollaborators(datasetId: number): Promise<Collaborator[]> {
  const r = await authFetch(`/api/datasets/${datasetId}/collaborators`)
  if (!r.ok) throw await asError(r)
  return (await r.json()).collaborators
}

export async function removeCollaborator(datasetId: number, collaboratorId: number): Promise<void> {
  const r = await authFetch(`/api/datasets/${datasetId}/collaborators/${collaboratorId}`, { method: 'DELETE' })
  if (!r.ok) throw await asError(r)
}

export async function createShareLink(datasetId: number, column: string, expiresAt?: string | null): Promise<ShareLink> {
  const r = await authFetch(`/api/datasets/${datasetId}/share-links`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ column, expires_at: expiresAt ?? null }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function listShareLinks(datasetId: number): Promise<ShareLink[]> {
  const r = await authFetch(`/api/datasets/${datasetId}/share-links`)
  if (!r.ok) throw await asError(r)
  return (await r.json()).share_links
}

export async function revokeShareLink(datasetId: number, linkId: number): Promise<void> {
  const r = await authFetch(`/api/datasets/${datasetId}/share-links/${linkId}`, { method: 'DELETE' })
  if (!r.ok) throw await asError(r)
}

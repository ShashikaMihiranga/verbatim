import { useEffect, useState } from 'react'
import {
  acceptInviteLink, createInviteLink, createShareLink, listCollaborators, listInviteLinks, listShareLinks,
  removeCollaborator, revokeInviteLink, revokeShareLink,
} from './sharingApi'
import type { Collaborator, InviteLink, ShareLink } from './sharingApi'

// Sharing/roles (docs/TODO.md, fixed 2026-10-22). Owner-only panel - every call here 404s for anyone else
// (app/api_sharing.py's own `min_role="owner"` checks), so this is only ever shown from the report page's
// own "Share" toggle, which only the dataset's owner reaches in today's single-owner-aware frontend.
function inviteUrl(token: string): string {
  return `${window.location.origin}/accept-invite?token=${token}`
}

export default function SharePanel({ datasetId, column }: { datasetId: number; column: string }) {
  const [collaborators, setCollaborators] = useState<Collaborator[] | null>(null)
  const [inviteLinks, setInviteLinks] = useState<InviteLink[] | null>(null)
  const [shareLinks, setShareLinks] = useState<ShareLink[] | null>(null)
  const [expiresAt, setExpiresAt] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState<string | null>(null)

  async function refresh() {
    try {
      setCollaborators(await listCollaborators(datasetId))
      setInviteLinks(await listInviteLinks(datasetId))
      setShareLinks(await listShareLinks(datasetId))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId])

  function copy(text: string, key: string) {
    void navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 1500)
  }

  async function handleCreateInvite() {
    setError('')
    try {
      await createInviteLink(datasetId)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function handleCreateShare() {
    setError('')
    try {
      await createShareLink(datasetId, column, expiresAt || null)
      setExpiresAt('')
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="sh-panel">
      {error && <div className="err" role="alert">{error}</div>}

      <div className="sh-section">
        <div className="sh-section-h">Invite an editor</div>
        <p className="sh-note">
          Anyone who signs in and opens this link can edit this dataset - themes, cleaning, reports.
        </p>
        <button type="button" className="btn quiet" onClick={() => void handleCreateInvite()}>
          Create invite link
        </button>
        {inviteLinks?.map((l) => (
          <div className="sh-row" key={l.id}>
            <span className="sh-row-url">{inviteUrl(l.token)}</span>
            <button type="button" className="th-see" onClick={() => copy(inviteUrl(l.token), `inv-${l.id}`)}>
              {copied === `inv-${l.id}` ? 'Copied' : 'Copy'}
            </button>
            <button
              type="button"
              className="th-see"
              onClick={() => void revokeInviteLink(datasetId, l.id).then(refresh).catch((e) => setError(e.message))}
            >
              Revoke
            </button>
          </div>
        ))}
      </div>

      <div className="sh-section">
        <div className="sh-section-h">Collaborators</div>
        {collaborators?.length === 0 && <p className="sh-note muted">No one else has access yet.</p>}
        {collaborators?.map((c) => (
          <div className="sh-row" key={c.id}>
            <span>User #{c.user_id}</span>
            <span className="sh-row-role">{c.role}</span>
            <button
              type="button"
              className="th-see"
              onClick={() => void removeCollaborator(datasetId, c.id).then(refresh).catch((e) => setError(e.message))}
            >
              Remove
            </button>
          </div>
        ))}
      </div>

      <div className="sh-section">
        <div className="sh-section-h">Read-only share link</div>
        <p className="sh-note">
          Anyone with this link can view the report for <b>{column}</b> - no sign-in, no verbatim answers.
        </p>
        <div className="sh-row">
          <label htmlFor="sh-expires" className="sh-note">Expires (optional)</label>
          <input
            id="sh-expires"
            type="date"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
          />
          <button type="button" className="btn quiet" onClick={() => void handleCreateShare()}>
            Create share link
          </button>
        </div>
        {shareLinks?.map((l) => (
          <div className="sh-row" key={l.id}>
            <span className="sh-row-url">{`${window.location.origin}/shared?token=${l.token}`}</span>
            {l.expires_at && <span className="sh-row-role">expires {l.expires_at.slice(0, 10)}</span>}
            <button
              type="button"
              className="th-see"
              onClick={() => copy(`${window.location.origin}/shared?token=${l.token}`, `shr-${l.id}`)}
            >
              {copied === `shr-${l.id}` ? 'Copied' : 'Copy'}
            </button>
            <button
              type="button"
              className="th-see"
              onClick={() => void revokeShareLink(datasetId, l.id).then(refresh).catch((e) => setError(e.message))}
            >
              Revoke
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// Exported so AcceptInvite.tsx (the route an invite link actually opens) can reuse the same call.
export { acceptInviteLink }

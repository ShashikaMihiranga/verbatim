import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { acceptInviteLink } from './sharingApi'

// Sharing/roles (docs/TODO.md, fixed 2026-10-22). This route sits BEHIND the normal sign-in guard
// (App.tsx) - a visitor who isn't signed in yet is sent to sign in first, then lands back here, so by
// the time this component renders a real `current_user` already exists for the accept call to use.
export default function AcceptInvite() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [status, setStatus] = useState<'working' | 'done' | 'error'>('working')
  const [error, setError] = useState('')
  const [datasetId, setDatasetId] = useState<number | null>(null)

  useEffect(() => {
    if (!token) {
      setStatus('error')
      setError('This invite link is missing its token.')
      return
    }
    acceptInviteLink(token)
      .then((r) => {
        setDatasetId(r.dataset_id)
        setStatus('done')
      })
      .catch((e: Error) => {
        setError(e.message)
        setStatus('error')
      })
  }, [token])

  if (status === 'working') return <p className="muted">Joining...</p>
  if (status === 'error') {
    return (
      <>
        <h1>Couldn't join</h1>
        <p className="err" role="alert">{error}</p>
        <Link to="/projects">Back to projects</Link>
      </>
    )
  }
  return (
    <>
      <h1>You're in</h1>
      <p className="muted">You can now edit this dataset.</p>
      <Link to={`/report?dataset=${datasetId}`}>Open the report</Link>
    </>
  )
}

import { useClerk } from '@clerk/clerk-react'
import { useNavigate } from 'react-router-dom'

export function useSignOut() {
  const { signOut } = useClerk()
  const navigate = useNavigate()
  return async () => {
    await signOut()
    navigate('/sign-in', { replace: true })
  }
}

import { ClerkProvider } from '@clerk/clerk-react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { clerkKey } from './authConfig'
import './index.css'

// Without VITE_CLERK_PUBLISHABLE_KEY the app still loads and shows "Sign-in is not configured yet".
const app = <App />

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      {clerkKey ? (
        <ClerkProvider publishableKey={clerkKey} afterSignOutUrl="/sign-in" signInUrl="/sign-in" signUpUrl="/sign-up">
          {app}
        </ClerkProvider>
      ) : (
        app
      )}
    </BrowserRouter>
  </StrictMode>,
)

// Every /api call goes through here so the Clerk session token is attached and a 401 sends the user to sign in.
type TokenGetter = () => Promise<string | null>

let getToken: TokenGetter = async () => null
let onUnauthorized: () => void = () => window.location.assign('/sign-in')

export function registerAuthBridge(bridge: { getToken?: TokenGetter; onUnauthorized?: () => void }) {
  if (bridge.getToken) getToken = bridge.getToken
  if (bridge.onUnauthorized) onUnauthorized = bridge.onUnauthorized
}

export async function authHeaders(extra?: HeadersInit): Promise<Headers> {
  const headers = new Headers(extra)
  let token: string | null = null
  try {
    token = await getToken()
  } catch {
    token = null
  }
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

export function handleUnauthorized(status: number) {
  if (status === 401) onUnauthorized()
}

export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(url, { ...init, headers: await authHeaders(init.headers) })
  handleUnauthorized(r.status)
  return r
}

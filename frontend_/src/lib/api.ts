const ACCESS_TOKEN_KEY = 'access_token'

export function getApiBaseUrl() {
  if (import.meta.env.DEV) return ''
  return import.meta.env.VITE_API_BASE_URL as string
}

export function getAccessToken() {
  return window.localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function saveAccessToken(token: string) {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token)
}

export function clearAccessToken() {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY)
}

export function getAuthHeaders(init?: HeadersInit) {
  const headers = new Headers(init)
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  headers.set('ngrok-skip-browser-warning', 'true')
  return headers
}

export async function apiRequest(path: string, options: RequestInit = {}) {
  const headers = getAuthHeaders(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return fetch(`${getApiBaseUrl()}${path}`, { ...options, headers })
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function readApiError(response: Response, fallback: string) {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg
    if (typeof body?.error?.message === 'string') return body.error.message
    if (typeof body?.message === 'string' && body.message.trim()) return body.message
  } catch {
    // keep fallback
  }
  return fallback
}

/** Fetch JSON from the backend; throws ApiError with a readable message on failure. */
export async function apiJson<T>(path: string, options: RequestInit = {}, fallback = 'Request failed'): Promise<T> {
  let response: Response
  try {
    response = await apiRequest(path, options)
  } catch {
    throw new ApiError('Unable to reach the server. Please try again.', 0)
  }
  if (!response.ok) {
    throw new ApiError(await readApiError(response, fallback), response.status)
  }
  return (await response.json()) as T
}

/** Authenticated URL for an API-served image (screenshots are same-origin via the proxy). */
export function apiUrl(path: string) {
  return `${getApiBaseUrl()}${path}`
}

import { delay } from '@/lib/utils'
import { clearResultCache } from '@/services/analysisApi'
import { apiJson, apiRequest, clearAccessToken, readApiError, saveAccessToken } from '@/lib/api'
import {
  bootstrapStore,
  getPasswordMap,
  getUsers,
  readSession,
  setSession,
  updatePassword,
  updateStoredUser,
} from '@/mock/store'
import type { ChangePasswordInput, UpdateProfileInput, User } from '@/types'

bootstrapStore()

function initials(name: string) {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export const authService = {
  async login(email: string, password: string, remember: boolean) {
    let response: Response
    try {
      response = await apiRequest('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
    } catch {
      throw new Error('Unable to reach the server. Please try again.')
    }
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Invalid email or password'))
    }
    const data = await response.json()
    const profile = data.user
    const user: User = {
      id: profile.id,
      fullName: profile.full_name,
      companyName: profile.company_name,
      email: profile.email,
      avatarInitials: initials(profile.full_name),
    }
    saveAccessToken(data.access_token)
    const session = { user, token: data.access_token }
    setSession(session, remember)
    return session
  },

  async signup(input: {
    fullName: string
    companyName: string
    email: string
    password: string
  }) {
    let response: Response
    try {
      response = await apiRequest('/api/v1/auth/signup', {
        method: 'POST',
        body: JSON.stringify({
          full_name: input.fullName,
          company_name: input.companyName,
          email: input.email,
          password: input.password,
        }),
      })
    } catch {
      throw new Error('Unable to reach the server. Please try again.')
    }
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Unable to create account'))
    }
    const data = await response.json()
    const profile = data.user
    const user: User = {
      id: profile.id,
      fullName: profile.full_name,
      companyName: profile.company_name,
      email: profile.email,
      avatarInitials: initials(profile.full_name),
    }
    saveAccessToken(data.access_token)
    const session = { user, token: data.access_token }
    setSession(session, true)
    return session
  },

  async loginWithGoogle() {
    await delay(400)
    const user = getUsers()[0]
    const session = { user, token: `pg_google_${Date.now()}` }
    setSession(session, true)
    return session
  },

  async forgotPassword(email: string) {
    let response: Response
    try {
      response = await apiRequest('/api/v1/auth/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ email }),
      })
    } catch {
      throw new Error('Unable to reach the server. Please try again.')
    }
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Unable to send reset instructions'))
    }
    return (await response.json()) as { message: string }
  },

  async resetPassword(token: string, password: string) {
    let response: Response
    try {
      response = await apiRequest('/api/v1/auth/reset-password', {
        method: 'POST',
        body: JSON.stringify({ token, password }),
      })
    } catch {
      throw new Error('Unable to reach the server. Please try again.')
    }
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Unable to reset password'))
    }
    return (await response.json()) as { message: string }
  },

  async logout() {
    clearAccessToken()
    clearResultCache()
    setSession(null, false)
  },

  /** Validate the stored token against /auth/me; clears the session when it is rejected. */
  async verifySession() {
    const session = readSession()
    if (!session) return null
    try {
      const profile = await apiJson<{ id: string; full_name: string; company_name: string; email: string }>(
        '/api/v1/auth/me',
      )
      const user: User = {
        id: profile.id,
        fullName: profile.full_name,
        companyName: profile.company_name,
        email: profile.email,
        avatarInitials: initials(profile.full_name),
      }
      setSession({ ...session, user }, window.localStorage.getItem('playguard.session') !== null)
      return user
    } catch (err) {
      if ((err as { status?: number }).status === 401) {
        await authService.logout()
        return null
      }
      return session.user
    }
  },

  getCurrentSession() {
    return readSession()
  },

  async updateProfile(input: UpdateProfileInput) {
    await delay(400)
    const session = readSession()
    if (!session) throw new Error('You need to sign in again')
    const user: User = {
      ...session.user,
      fullName: input.fullName,
      companyName: input.companyName,
      avatarInitials: initials(input.fullName),
    }
    updateStoredUser(user)
    const next = { ...session, user }
    setSession(next, true)
    return user
  },

  async changePassword(input: ChangePasswordInput) {
    await delay(400)
    const session = readSession()
    if (!session) throw new Error('You need to sign in again')
    const passwords = getPasswordMap()
    if (passwords[session.user.email.toLowerCase()] !== input.currentPassword) {
      throw new Error('Current password is incorrect')
    }
    updatePassword(session.user.email, input.newPassword)
  },
}

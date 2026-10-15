import { demoUser, DEMO_PASSWORD } from '@/mock/data'
import type { User } from '@/types'

const USERS_KEY = 'playguard.users'
const SESSION_KEY = 'playguard.session'
const PASSWORDS_KEY = 'playguard.passwords'

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  window.localStorage.setItem(key, JSON.stringify(value))
}

export function bootstrapStore() {
  if (!window.localStorage.getItem(USERS_KEY)) {
    writeJson(USERS_KEY, [demoUser])
    writeJson(PASSWORDS_KEY, { [demoUser.email.toLowerCase()]: DEMO_PASSWORD })
  }
}

export function getUsers(): User[] {
  return readJson<User[]>(USERS_KEY, [demoUser])
}

export function getPasswordMap(): Record<string, string> {
  return readJson<Record<string, string>>(PASSWORDS_KEY, {
    [demoUser.email.toLowerCase()]: DEMO_PASSWORD,
  })
}

export function saveUser(user: User, password: string) {
  const users = getUsers().filter((item) => item.email !== user.email)
  users.push(user)
  writeJson(USERS_KEY, users)
  const passwords = getPasswordMap()
  passwords[user.email.toLowerCase()] = password
  writeJson(PASSWORDS_KEY, passwords)
}

export function updateStoredUser(user: User) {
  const users = getUsers().map((item) => (item.id === user.id ? user : item))
  writeJson(USERS_KEY, users)
}

export function updatePassword(email: string, next: string) {
  const passwords = getPasswordMap()
  passwords[email.toLowerCase()] = next
  writeJson(PASSWORDS_KEY, passwords)
}

export function setSession(session: { user: User; token: string } | null, persist: boolean) {
  if (!session) {
    window.localStorage.removeItem(SESSION_KEY)
    window.sessionStorage.removeItem(SESSION_KEY)
    return
  }
  const payload = JSON.stringify(session)
  if (persist) {
    window.localStorage.setItem(SESSION_KEY, payload)
    window.sessionStorage.removeItem(SESSION_KEY)
  } else {
    window.sessionStorage.setItem(SESSION_KEY, payload)
    window.localStorage.removeItem(SESSION_KEY)
  }
}

export function readSession(): { user: User; token: string } | null {
  const local = window.localStorage.getItem(SESSION_KEY)
  const session = window.sessionStorage.getItem(SESSION_KEY)
  const raw = local ?? session
  if (!raw) return null
  try {
    return JSON.parse(raw) as { user: User; token: string }
  } catch {
    return null
  }
}

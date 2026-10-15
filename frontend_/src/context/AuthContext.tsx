import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTheme } from '@/context/ThemeContext'
import { authService } from '@/services/authService'
import type { User } from '@/types'

interface AuthContextValue {
  user: User | null
  ready: boolean
  login: (email: string, password: string, remember: boolean) => Promise<void>
  signup: (input: {
    fullName: string
    companyName: string
    email: string
    password: string
  }) => Promise<void>
  loginWithGoogle: () => Promise<void>
  logout: () => Promise<void>
  refreshUser: (user: User) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => authService.getCurrentSession()?.user ?? null)
  const [ready] = useState(true)
  const { resetToLight } = useTheme()

  useEffect(() => {
    if (!authService.getCurrentSession()) return
    authService.verifySession().then(setUser)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      ready,
      async login(email, password, remember) {
        const session = await authService.login(email, password, remember)
        resetToLight()
        setUser(session.user)
      },
      async signup(input) {
        const session = await authService.signup(input)
        resetToLight()
        setUser(session.user)
      },
      async loginWithGoogle() {
        const session = await authService.loginWithGoogle()
        resetToLight()
        setUser(session.user)
      },
      async logout() {
        await authService.logout()
        resetToLight()
        setUser(null)
      },
      refreshUser(next) {
        setUser(next)
      },
    }),
    [user, ready, resetToLight],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}

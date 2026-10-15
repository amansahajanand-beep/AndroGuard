import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
  resetToLight: () => void
}

const THEME_KEY = 'playguard.theme'

const ThemeContext = createContext<ThemeContextValue | null>(null)

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    window.localStorage.removeItem(THEME_KEY)
    const stored = window.sessionStorage.getItem(THEME_KEY)
    const next: Theme = stored === 'dark' ? 'dark' : 'light'
    applyTheme(next)
    return next
  })

  useEffect(() => {
    applyTheme(theme)
    window.sessionStorage.setItem(THEME_KEY, theme)
    window.localStorage.removeItem(THEME_KEY)
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  const resetToLight = useCallback(() => {
    setTheme('light')
  }, [])

  const value = useMemo(
    () => ({
      theme,
      toggleTheme,
      resetToLight,
    }),
    [theme, toggleTheme, resetToLight],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used within ThemeProvider')
  return context
}

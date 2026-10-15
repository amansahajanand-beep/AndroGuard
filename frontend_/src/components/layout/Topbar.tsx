import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Bell, ClipboardList, Menu, Moon, Plus, Search, Sun } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useTheme } from '@/context/ThemeContext'
import { auditService } from '@/services/auditService'
import { dashboardService } from '@/services/dashboardService'
import type { Audit, NotificationItem } from '@/types'

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { user } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const showNewAudit = pathname === '/dashboard' || pathname === '/audit-logs'
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Audit[]>([])
  const [openSearch, setOpenSearch] = useState(false)
  const [openNotes, setOpenNotes] = useState(false)
  const [notes, setNotes] = useState<NotificationItem[]>([])
  const searchRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    dashboardService.getNotifications().then(setNotes)
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      return
    }
    const handle = window.setTimeout(() => {
      auditService.search(query).then(setResults)
    }, 200)
    return () => window.clearTimeout(handle)
  }, [query])

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!searchRef.current?.contains(event.target as Node)) {
        setOpenSearch(false)
        setOpenNotes(false)
      }
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [])

  return (
    <header className="app-topbar relative sticky top-0 z-30 flex h-[72px] min-w-0 items-center gap-3 border-b border-line bg-white px-4 dark:border-night-border dark:bg-night-card lg:px-6">
      <button
        type="button"
        className="grid h-10 w-10 shrink-0 place-items-center rounded-lg text-muted hover:bg-subtle lg:hidden"
        onClick={onMenu}
        aria-label="Open navigation"
      >
        <Menu size={20} />
      </button>
      <div className="app-topbar-search relative mx-auto w-full min-w-0 max-w-xl" ref={searchRef}>
        <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={18} />
        <input
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setOpenSearch(true)
          }}
          onFocus={() => setOpenSearch(true)}
          placeholder="Search for anything..."
          className="h-11 w-full min-w-0 rounded-xl border border-transparent bg-canvas pl-10 pr-4 text-sm text-ink placeholder:text-muted/70 focus:border-primary focus:bg-white focus:shadow-glow-sm focus:outline-none dark:bg-night-raised dark:text-slate-100"
        />
        {openSearch && results.length > 0 ? (
          <div className="absolute top-[52px] w-full overflow-hidden rounded-xl border border-line bg-white shadow-soft dark:border-night-border dark:bg-night-card">
            {results.map((item) => (
              <button
                key={item.id}
                type="button"
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm hover:bg-subtle"
                onClick={() => {
                  setOpenSearch(false)
                  setQuery('')
                  navigate(item.status === 'COMPLETED' ? `/audits/${item.id}/report` : `/audit/${item.id}/processing`)
                }}
              >
                <span className="font-medium text-ink">{item.appName}</span>
                <span className="text-xs text-muted">{item.displayId}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <div className="app-topbar-actions ml-auto flex shrink-0 items-center gap-1">
        <button
          type="button"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-lg text-muted hover:bg-subtle"
          onClick={toggleTheme}
          aria-label="Toggle dark mode"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <button
          type="button"
          className="relative grid h-10 w-10 shrink-0 place-items-center rounded-lg text-muted hover:bg-subtle"
          onClick={() => setOpenNotes((value) => !value)}
          aria-label="Notifications"
        >
          <Bell size={18} />
          {notes.some((item) => item.unread) ? <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-danger" /> : null}
        </button>
        <Link
          to={showNewAudit ? '/audit-run' : '/audit-logs'}
          className="app-topbar-new-audit hidden h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg bg-brand px-3 text-sm font-semibold text-primary-ink hover:bg-brand-hover hover:shadow-glow sm:inline-flex"
        >
          {showNewAudit ? (
            <>
              <Plus size={16} />
              New Audit
            </>
          ) : (
            <>
              <ClipboardList size={16} />
              Audit Logs
            </>
          )}
        </Link>
        <Link to="/profile" className="app-topbar-profile ml-1 flex min-w-0 shrink-0 items-center gap-2 rounded-lg p-1.5 hover:bg-subtle">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand text-xs font-bold text-primary-ink">
            {user?.avatarInitials ?? 'PG'}
          </span>
          <span className="app-topbar-user hidden min-w-0 pr-1 leading-tight md:block">
            <span className="block truncate text-sm font-semibold text-ink">{user?.fullName}</span>
            <span className="block truncate text-xs text-muted">{user?.companyName}</span>
          </span>
        </Link>
      </div>
      {openNotes ? (
        <div className="absolute right-4 top-[68px] w-[320px] overflow-hidden rounded-xl border border-line bg-white shadow-soft dark:border-night-border dark:bg-night-card">
          {notes.map((note) => (
            <div key={note.id} className="border-b border-line px-4 py-3 last:border-0 dark:border-night-border">
              <p className="text-sm font-semibold text-ink">{note.title}</p>
              <p className="mt-1 text-xs text-muted">{note.body}</p>
              <p className="mt-1 text-[11px] text-muted">{note.time}</p>
            </div>
          ))}
        </div>
      ) : null}
    </header>
  )
}

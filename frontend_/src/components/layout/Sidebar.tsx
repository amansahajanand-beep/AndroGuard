import { NavLink } from 'react-router-dom'
import {
  Boxes,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  PlayCircle,
  UserRound,
} from 'lucide-react'
import { Logo } from '@/components/layout/Logo'
import { cn } from '@/lib/utils'

const items = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/audit-run', label: 'Audit Run', icon: PlayCircle },
  { to: '/audit-logs', label: 'Audit Logs', icon: ClipboardList },
  { to: '/products', label: 'Other Products', icon: Boxes },
]

export function Sidebar({
  onNavigate,
  onLogout,
}: {
  onNavigate?: () => void
  onLogout: () => void
}) {
  return (
    <aside className="flex h-full w-[250px] flex-col bg-sidebar text-[#8696A8]">
      <div className="flex h-[72px] items-center px-5">
        <Logo light />
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="Main">
        {items.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition',
                  isActive ? 'bg-[#3DDC84]/10 text-[#3DDC84] shadow-glow' : 'hover:bg-white/5 hover:text-[#E6EDF3]',
                )
              }
            >
              <Icon size={18} />
              {item.label}
            </NavLink>
          )
        })}
      </nav>
      <div className="space-y-1 border-t border-[#223041] px-3 py-4">
        <NavLink
          to="/profile"
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition',
              isActive ? 'bg-[#3DDC84]/10 text-[#3DDC84] shadow-glow' : 'hover:bg-white/5 hover:text-[#E6EDF3]',
            )
          }
        >
          <UserRound size={18} />
          Profile
        </NavLink>
        <button
          type="button"
          onClick={onLogout}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[#8696A8] transition hover:bg-[#FF4D5E]/10 hover:text-[#FF4D5E]"
        >
          <LogOut size={18} />
          Logout
        </button>
      </div>
    </aside>
  )
}

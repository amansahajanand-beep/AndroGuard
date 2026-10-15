import { useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { useAuth } from '@/context/AuthContext'

export function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [logoutOpen, setLogoutOpen] = useState(false)
  const { logout } = useAuth()
  const navigate = useNavigate()

  async function confirmLogout() {
    await logout()
    setLogoutOpen(false)
    navigate('/login')
  }

  return (
    <div className="bg-dots min-h-screen bg-canvas">
      <div className="hidden lg:fixed lg:inset-y-0 lg:flex">
        <Sidebar onLogout={() => setLogoutOpen(true)} />
      </div>
      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" className="absolute inset-0 bg-night/70" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />
          <div className="relative h-full w-[250px]">
            <Sidebar onNavigate={() => setMobileOpen(false)} onLogout={() => setLogoutOpen(true)} />
          </div>
        </div>
      ) : null}
      <div className="lg:pl-[250px]">
        <Topbar onMenu={() => setMobileOpen(true)} />
        <main className="px-4 py-6 lg:px-8">
          <div className="mx-auto max-w-app">
            <Outlet />
          </div>
        </main>
      </div>
      <Modal open={logoutOpen} title="Log out?" onClose={() => setLogoutOpen(false)}>
        <p className="text-sm text-muted">You will need to sign in again to view audits and reports.</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setLogoutOpen(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={confirmLogout}>
            Logout
          </Button>
        </div>
      </Modal>
    </div>
  )
}

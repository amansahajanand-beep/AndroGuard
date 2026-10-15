import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { useAuth } from '@/context/AuthContext'
import { CompletedPage } from '@/pages/audit/CompletedPage'
import { NewAuditPage } from '@/pages/audit/NewAuditPage'
import { ProcessingPage } from '@/pages/audit/ProcessingPage'
import { AuditLogsPage } from '@/pages/audits/AuditLogsPage'
import { AuditReportPage } from '@/pages/audits/AuditReportPage'
import { ForgotPasswordPage } from '@/pages/auth/ForgotPasswordPage'
import { LoginPage } from '@/pages/auth/LoginPage'
import { ResetPasswordPage } from '@/pages/auth/ResetPasswordPage'
import { SignupPage } from '@/pages/auth/SignupPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { ProductsPage } from '@/pages/ProductsPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { ReportsPage } from '@/pages/ReportsPage'

function ProtectedRoute() {
  const { user, ready } = useAuth()
  if (!ready) return null
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}

function GuestRoute() {
  const { user } = useAuth()
  if (user) return <Navigate to="/dashboard" replace />
  return <Outlet />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<GuestRoute />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/audit-run" element={<NewAuditPage />} />
          <Route path="/audit/new" element={<Navigate to="/audit-run" replace />} />
          <Route path="/audit/:id/processing" element={<ProcessingPage />} />
          <Route path="/audit/:id/completed" element={<CompletedPage />} />
          <Route path="/audit-logs" element={<AuditLogsPage />} />
          <Route path="/audits" element={<Navigate to="/audit-logs" replace />} />
          <Route path="/audits/:id/report" element={<AuditReportPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Route>
      </Route>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

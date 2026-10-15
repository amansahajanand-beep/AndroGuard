import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { authService } from '@/services/authService'

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const next: Record<string, string> = {}
    if (password.length < 8) next.password = 'Use at least 8 characters'
    if (password !== confirmPassword) next.confirmPassword = 'Passwords do not match'
    setErrors(next)
    setFormError('')
    if (Object.keys(next).length) return
    setLoading(true)
    try {
      const result = await authService.resetPassword(token, password)
      setSuccess(result.message)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Unable to reset password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout>
      <h2 className="text-2xl font-bold text-ink">Reset Password</h2>
      <p className="mt-1 text-sm text-muted">Choose a new password for your account.</p>
      {!token ? (
        <p className="mt-8 rounded-lg bg-danger/10 px-3 py-2 text-sm font-medium text-danger">
          This reset link is invalid. Please request a new one.
        </p>
      ) : success ? (
        <p className="mt-8 rounded-lg bg-success/10 px-3 py-2 text-sm font-medium text-success">{success}</p>
      ) : (
        <form className="mt-8 space-y-4" onSubmit={onSubmit}>
          {formError ? <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm font-medium text-danger">{formError}</p> : null}
          <PasswordInput label="New Password" name="password" value={password} onChange={setPassword} error={errors.password} autoComplete="new-password" />
          <PasswordInput label="Confirm Password" name="confirmPassword" value={confirmPassword} onChange={setConfirmPassword} error={errors.confirmPassword} autoComplete="new-password" />
          <Button type="submit" className="w-full" loading={loading}>
            Reset Password
          </Button>
        </form>
      )}
      <p className="mt-6 text-center text-sm">
        <Link to="/login" className="font-semibold text-primary">
          Back to Login
        </Link>
      </p>
    </AuthLayout>
  )
}

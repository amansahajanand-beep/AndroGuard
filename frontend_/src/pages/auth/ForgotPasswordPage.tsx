import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { authService } from '@/services/authService'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (!email.trim()) {
      setError('Enter your email address.')
      return
    }
    setLoading(true)
    try {
      const result = await authService.forgotPassword(email)
      setSuccess(result.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send reset link')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout>
      <h2 className="text-2xl font-bold text-ink">Forgot Password</h2>
      <p className="mt-1 text-sm text-muted">Enter your email address and we'll send you instructions to reset your password.</p>
      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        {error ? <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm font-medium text-danger">{error}</p> : null}
        {success ? <p className="rounded-lg bg-success/10 px-3 py-2 text-sm font-medium text-success">{success}</p> : null}
        <Input label="Email Address" name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" />
        <Button type="submit" className="w-full" loading={loading}>
          Send Reset Link
        </Button>
      </form>
      <p className="mt-6 text-center text-sm">
        <Link to="/login" className="font-semibold text-primary">
          Back to Login
        </Link>
      </p>
    </AuthLayout>
  )
}

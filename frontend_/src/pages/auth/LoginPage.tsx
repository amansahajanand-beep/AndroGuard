import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { useAuth } from '@/context/AuthContext'

export function LoginPage() {
  const { login, loginWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('alex@northstar.dev')
  const [password, setPassword] = useState('PlayGuard123')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (!email || !password) {
      setError('Enter your email and password.')
      return
    }
    setLoading(true)
    try {
      await login(email, password, remember)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout>
      <h2 className="text-2xl font-bold text-ink">Welcome Back</h2>
      <p className="mt-1 text-sm text-muted">Sign in to your account to continue</p>
      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        {error ? <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm font-medium text-danger">{error}</p> : null}
        <Input label="Email Address" name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" />
        <PasswordInput label="Password" name="password" value={password} onChange={setPassword} autoComplete="current-password" />
        <div className="flex items-center justify-between text-sm">
          <label className="flex items-center gap-2 text-muted">
            <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} className="h-4 w-4 accent-primary" />
            Remember me
          </label>
          <Link to="/forgot-password" className="font-semibold text-primary">
            Forgot password?
          </Link>
        </div>
        <Button type="submit" className="w-full" loading={loading}>
          Login
        </Button>
      </form>
      <div className="my-6 flex items-center gap-3 text-xs font-semibold uppercase tracking-wider text-muted">
        <span className="h-px flex-1 bg-line dark:bg-night-border" />
        OR
        <span className="h-px flex-1 bg-line dark:bg-night-border" />
      </div>
      <Button
        variant="outline"
        className="w-full"
        onClick={async () => {
          await loginWithGoogle()
          navigate('/dashboard')
        }}
      >
        Continue with Google
      </Button>
      <p className="mt-6 text-center text-sm text-muted">
        Don't have an account?{' '}
        <Link to="/signup" className="font-semibold text-primary">
          Sign Up
        </Link>
      </p>
    </AuthLayout>
  )
}

import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { useAuth } from '@/context/AuthContext'

export function SignupPage() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  const [fullName, setFullName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const next: Record<string, string> = {}
    if (!fullName.trim()) next.fullName = 'Full name is required'
    if (!companyName.trim()) next.companyName = 'Company name is required'
    if (!email.trim()) next.email = 'Email is required'
    if (password.length < 8) next.password = 'Use at least 8 characters'
    if (password !== confirmPassword) next.confirmPassword = 'Passwords do not match'
    setErrors(next)
    setFormError('')
    if (Object.keys(next).length) return
    setLoading(true)
    try {
      await signup({ fullName, companyName, email, password })
      navigate('/dashboard')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Unable to create account')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout>
      <h2 className="text-2xl font-bold text-ink">Create Your Account</h2>
      <p className="mt-1 text-sm text-muted">Get started with your account</p>
      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        {formError ? <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm font-medium text-danger">{formError}</p> : null}
        <Input label="Full Name" name="fullName" value={fullName} onChange={(event) => setFullName(event.target.value)} error={errors.fullName} placeholder="Alex Rivera" />
        <Input label="Company Name" name="companyName" value={companyName} onChange={(event) => setCompanyName(event.target.value)} error={errors.companyName} placeholder="Northstar Apps" />
        <Input label="Email Address" name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} error={errors.email} placeholder="you@company.com" />
        <PasswordInput label="Password" name="password" value={password} onChange={setPassword} error={errors.password} autoComplete="new-password" />
        <PasswordInput label="Confirm Password" name="confirmPassword" value={confirmPassword} onChange={setConfirmPassword} error={errors.confirmPassword} autoComplete="new-password" />
        <Button type="submit" className="w-full" loading={loading}>
          Create Account
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already have an account?{' '}
        <Link to="/login" className="font-semibold text-primary">
          Login
        </Link>
      </p>
    </AuthLayout>
  )
}

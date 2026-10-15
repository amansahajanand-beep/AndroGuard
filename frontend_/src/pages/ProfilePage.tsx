import { useState, type FormEvent } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { useAuth } from '@/context/AuthContext'
import { authService } from '@/services/authService'

export function ProfilePage() {
  const { user, refreshUser } = useAuth()
  const [fullName, setFullName] = useState(user?.fullName ?? '')
  const [companyName, setCompanyName] = useState(user?.companyName ?? '')
  const [profileMessage, setProfileMessage] = useState('')
  const [profileError, setProfileError] = useState('')
  const [savingProfile, setSavingProfile] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordMessage, setPasswordMessage] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)

  async function onSaveProfile(event: FormEvent) {
    event.preventDefault()
    setProfileError('')
    setProfileMessage('')
    if (!fullName.trim() || !companyName.trim()) {
      setProfileError('Full name and company name are required.')
      return
    }
    setSavingProfile(true)
    try {
      const next = await authService.updateProfile({ fullName, companyName })
      refreshUser(next)
      setProfileMessage('Profile updated.')
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : 'Unable to update profile')
    } finally {
      setSavingProfile(false)
    }
  }

  async function onChangePassword(event: FormEvent) {
    event.preventDefault()
    setPasswordError('')
    setPasswordMessage('')
    if (newPassword.length < 8) {
      setPasswordError('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match.')
      return
    }
    setSavingPassword(true)
    try {
      await authService.changePassword({ currentPassword, newPassword })
      setPasswordMessage('Password updated.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : 'Unable to change password')
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <div>
      <PageHeader title="Profile" subtitle="Manage your account information and password." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <div className="mb-5 flex items-center gap-3">
            <span className="grid h-14 w-14 place-items-center rounded-full bg-brand text-lg font-bold text-primary-ink">
              {user?.avatarInitials}
            </span>
            <div>
              <h2 className="text-[15px] font-semibold text-ink">Account Information</h2>
              <p className="text-xs text-muted">{user?.email}</p>
            </div>
          </div>
          <form className="space-y-4" onSubmit={onSaveProfile}>
            {profileError ? <p className="text-sm font-medium text-danger">{profileError}</p> : null}
            {profileMessage ? <p className="text-sm font-medium text-success">{profileMessage}</p> : null}
            <Input label="Full Name" value={fullName} onChange={(event) => setFullName(event.target.value)} />
            <Input label="Company Name" value={companyName} onChange={(event) => setCompanyName(event.target.value)} />
            <Input label="Email" value={user?.email ?? ''} disabled />
            <Button type="submit" loading={savingProfile}>
              Update Profile
            </Button>
          </form>
        </Card>
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Change Password</h2>
          <form className="space-y-4" onSubmit={onChangePassword}>
            {passwordError ? <p className="text-sm font-medium text-danger">{passwordError}</p> : null}
            {passwordMessage ? <p className="text-sm font-medium text-success">{passwordMessage}</p> : null}
            <PasswordInput label="Current Password" name="currentPassword" value={currentPassword} onChange={setCurrentPassword} />
            <PasswordInput label="New Password" name="newPassword" value={newPassword} onChange={setNewPassword} />
            <PasswordInput label="Confirm Password" name="confirmPassword" value={confirmPassword} onChange={setConfirmPassword} />
            <Button type="submit" loading={savingPassword}>
              Change Password
            </Button>
          </form>
        </Card>
      </div>
    </div>
  )
}

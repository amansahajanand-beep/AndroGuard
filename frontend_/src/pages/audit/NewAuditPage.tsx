import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { StaticAuditProgress } from '@/components/audit/StaticAuditProgress'
import { ApkUploader, PrivacyPolicyUploader } from '@/components/audit/FileUploaders'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'
import { apiJson } from '@/lib/api'
import { auditService } from '@/services/auditService'

export function NewAuditPage() {
  const navigate = useNavigate()
  const [appName, setAppName] = useState('')
  const [appDescription, setAppDescription] = useState('')
  const [playStoreLink, setPlayStoreLink] = useState('')
  const [apk, setApk] = useState<File | null>(null)
  const [policy, setPolicy] = useState<File | null>(null)
  const [privacyPolicyLink, setPrivacyPolicyLink] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [loading, setLoading] = useState(false)
  const [explore, setExplore] = useState(true)
  // null = not known yet; the server decides whether emulator exploration is available.
  const [explorationAvailable, setExplorationAvailable] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    apiJson<{ exploration?: { enabled?: boolean } }>('/api/v1/health')
      .then((health) => {
        if (cancelled) return
        const enabled = health.exploration?.enabled !== false
        setExplorationAvailable(enabled)
        if (!enabled) setExplore(false)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const next: Record<string, string> = {}
    if (!appName.trim()) next.appName = 'App name is required'
    if (!appDescription.trim()) next.appDescription = 'App description is required'
    if (!apk) next.apk = 'Upload an APK file'
    else if (!apk.name.toLowerCase().endsWith('.apk')) next.apk = 'Only APK files are accepted'
    const policyUrl = privacyPolicyLink.trim()
    if (policy && policyUrl) next.policy = 'Provide either a privacy policy file or a URL, not both'
    else if (policyUrl && !/^https?:\/\//.test(policyUrl)) next.privacyPolicyLink = 'Enter a valid URL'
    else if (!policy && !policyUrl) next.policy = 'Upload a privacy policy file or provide a URL'
    if (playStoreLink && !/^https?:\/\//.test(playStoreLink)) next.playStoreLink = 'Enter a valid URL'
    setErrors(next)
    if (Object.keys(next).length) return
    setLoading(true)
    setFormError('')
    try {
      const audit = await auditService.start({
        appName,
        appDescription,
        playStoreLink: playStoreLink || undefined,
        apk: apk!,
        privacyPolicy: policy && !privacyPolicyLink.trim() ? policy : undefined,
        privacyPolicyUrl: !policy && privacyPolicyLink.trim() ? privacyPolicyLink.trim() : undefined,
        explore,
      })
      navigate(`/audit/${audit.id}/processing`)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Unable to start audit')
    } finally {
      setLoading(false)
    }
  }

  // Static runs answer in one request, so show the staged progress here; explore runs poll on the processing page.
  if (loading && !explore) return <StaticAuditProgress appName={appName} />

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <PageHeader
        title="Start New Audit"
        subtitle="Provide your app details and files to begin the compliance audit."
      />
      {formError ? <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm font-medium text-danger">{formError}</p> : null}
      <Card className="p-5">
        <h2 className="text-[15px] font-semibold text-ink">App Information</h2>
        <div className="mt-4 grid gap-4">
          <Input label="App Name *" name="appName" value={appName} onChange={(event) => setAppName(event.target.value)} error={errors.appName} placeholder="Gallery App" />
          <Textarea label="App Description / Purpose *" name="appDescription" value={appDescription} onChange={(event) => setAppDescription(event.target.value)} error={errors.appDescription} placeholder="Describe what the app does and who it is for." />
        </div>
      </Card>
      <Card className="p-5">
        <h2 className="text-[15px] font-semibold text-ink">Upload Files</h2>
        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,0.38fr)_minmax(0,0.62fr)] lg:gap-0">
          <div className="h-full lg:pr-5">
            <ApkUploader file={apk} onChange={setApk} error={errors.apk} />
          </div>
          <div className="lg:border-l lg:border-line lg:pl-5 dark:lg:border-night-border">
            <PrivacyPolicyUploader
              file={policy}
              onChange={(nextFile) => {
                setPolicy(nextFile)
                if (nextFile) setPrivacyPolicyLink('')
              }}
              error={errors.policy}
              url={privacyPolicyLink}
              onUrlChange={(nextUrl) => {
                setPrivacyPolicyLink(nextUrl)
                if (nextUrl.trim()) setPolicy(null)
              }}
              urlError={errors.privacyPolicyLink}
            />
          </div>
        </div>
        <div className="mt-4">
          <Input label="Play Store Link (optional)" name="playStoreLink" value={playStoreLink} onChange={(event) => setPlayStoreLink(event.target.value)} error={errors.playStoreLink} placeholder="Provide Play Store link only when your application is published." />
        </div>
      </Card>
      <Card className="p-5">
        <label className="flex cursor-pointer items-start gap-3" htmlFor="explore">
          <input
            id="explore"
            type="checkbox"
            checked={explore && explorationAvailable !== false}
            disabled={explorationAvailable === false}
            onChange={(event) => setExplore(event.target.checked)}
            className="mt-1 h-4 w-4 rounded border-line text-primary focus:ring-primary/30"
          />
          <span>
            <span className="pg-label mb-0">Run emulator exploration</span>
            <span className="mt-1 block text-xs text-muted">
              {explorationAvailable === false
                ? 'Turned off on the server, so audits run as a quick static analysis only.'
                : 'Opens the app on an Android emulator, uses it like a person would, and records where ads appear on each screen. Takes several minutes. Turn off for a quick static analysis only.'}
            </span>
          </span>
        </label>
      </Card>
      <div className="flex justify-end">
        <Button type="submit" className="w-full sm:w-auto" loading={loading}>
          Start Audit
        </Button>
      </div>
    </form>
  )
}

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AuditStepper } from '@/components/audit/AuditStepper'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { CircularProgress } from '@/components/ui/CircularProgress'
import { ErrorState } from '@/components/ui/EmptyState'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Skeleton } from '@/components/ui/Skeleton'
import { Button } from '@/components/ui/Button'
import { apiRequest } from '@/lib/api'
import { auditService } from '@/services/auditService'
import { interventionService, type InterventionDecision } from '@/services/interventionService'
import type { Audit } from '@/types'

/** The screenshot route needs the bearer token, which an <img src> cannot send, so fetch it as a blob. */
function AuthImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    apiRequest(path)
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => {
        if (!blob || cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path])

  return src ? <img src={src} alt={alt} className={className} /> : null
}

export function ProcessingPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [audit, setAudit] = useState<Audit | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  async function respond(decision: InterventionDecision) {
    if (!audit?.intervention) return
    setBusy(true)
    setActionError('')
    try {
      await interventionService.resolve(audit.id, audit.intervention.id, decision)
      setAudit(await auditService.getById(id))
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to send your response')
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    setBusy(true)
    try {
      await auditService.cancel(id)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to cancel audit')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    async function tick() {
      try {
        const next = await auditService.getById(id)
        if (cancelled) return
        setAudit(next)
        if (next.status === 'COMPLETED') {
          navigate(`/audit/${id}/completed`, { replace: true })
        } else if (next.status === 'FAILED') {
          window.clearInterval(handle)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Unable to load audit')
      }
    }
    const handle = window.setInterval(tick, 2500)
    tick()
    return () => {
      cancelled = true
      window.clearInterval(handle)
    }
  }, [id, navigate])

  if (error) {
    return <ErrorState title="Audit failed" message={error} onRetry={() => window.location.reload()} />
  }

  if (!audit) {
    return <Skeleton className="h-80" />
  }

  if (audit.status === 'FAILED') {
    return <ErrorState title="Audit failed" message={audit.errorMessage ?? 'The audit was stopped before it finished.'} />
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit in Progress"
        subtitle={`Audit ID: ${audit.displayId}`}
        actions={<Badge tone="info">Processing</Badge>}
      />
      <ProgressBar value={audit.progress} />
      {audit.intervention ? (
        <Card className="space-y-4 border-warning/50 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Badge tone="warning">{audit.intervention.typeLabel}</Badge>
              <h2 className="mt-2 text-[15px] font-semibold text-ink">{audit.intervention.title}</h2>
              <p className="mt-1 text-sm text-muted">{audit.intervention.message}</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-[200px_1fr]">
            {audit.intervention.screenshotUrl ? (
              <AuthImage path={audit.intervention.screenshotUrl} alt="Emulator screen awaiting action" className="w-full max-w-[200px] rounded-lg border border-line" />
            ) : null}
            <div className="space-y-2 text-sm text-ink">
              <p className="font-medium">{audit.intervention.suggestedAction}</p>
              {audit.intervention.steps.length ? (
                <ol className="list-decimal space-y-1 pl-5 text-muted">
                  {audit.intervention.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              ) : null}
            </div>
          </div>
          {actionError ? <p className="text-sm font-medium text-danger">{actionError}</p> : null}
          <div className="flex flex-wrap gap-3">
            <Button loading={busy} onClick={() => respond('continue')}>I did it - Continue</Button>
            <Button variant="outline" disabled={busy} onClick={() => respond('skip')}>Skip</Button>
            <Button variant="outline" disabled={busy} onClick={() => respond('stop')}>Stop exploration</Button>
          </div>
        </Card>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Audit stages</h2>
          <AuditStepper stages={audit.stages} />
        </Card>
        <Card className="flex flex-col items-center justify-center p-8 text-center">
          <CircularProgress value={audit.progress} label="In progress" />
          <p className="mt-4 max-w-xs text-sm text-muted">
            AndroGuard is reviewing {audit.appName} against Google Play requirements. This page will update automatically.
          </p>
          <Link to="/dashboard" className="mt-5 text-sm font-semibold text-primary">
            Back to Dashboard
          </Link>
          <button type="button" disabled={busy} onClick={cancel} className="mt-3 text-sm font-semibold text-danger disabled:opacity-50">
            Cancel audit
          </button>
        </Card>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ErrorState } from '@/components/ui/EmptyState'
import { RecommendationBadge, RiskBadge } from '@/components/ui/StatusBadge'
import { Skeleton } from '@/components/ui/Skeleton'
import { recommendationTone } from '@/lib/status'
import { auditService } from '@/services/auditService'
import type { Audit } from '@/types'

export function CompletedPage() {
  const { id = '' } = useParams()
  const [audit, setAudit] = useState<Audit | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    auditService
      .getById(id)
      .then(setAudit)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to load audit'))
  }, [id])

  if (error) return <ErrorState title="Audit unavailable" message={error} />
  if (!audit) return <Skeleton className="h-64" />

  return (
    <div className="space-y-6">
      <PageHeader title="Audit Completed" subtitle={`Audit ID: ${audit.displayId}`} actions={<Badge tone="success">Completed</Badge>} />
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">App Name</p>
          <p className="mt-2 text-lg font-bold text-ink">{audit.appName}</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Readiness Score</p>
          <p className="mt-2 text-lg font-bold text-ink">{audit.readinessScore}%</p>
          <Badge className="mt-2" tone={recommendationTone(audit.recommendation)}>{`${audit.readinessScore}%`}</Badge>
        </Card>
        <Card className="p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Overall Risk</p>
          <div className="mt-2">
            <RiskBadge risk={audit.overallRisk} />
          </div>
        </Card>
      </div>
      <Card className="p-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Final Recommendation</p>
        <div className="mt-3">
          <RecommendationBadge value={audit.recommendation} />
        </div>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Link to={`/audits/${audit.id}/report`}>
            <Button className="w-full sm:w-auto">View Audit Report</Button>
          </Link>
          <Link to="/dashboard">
            <Button variant="outline" className="w-full sm:w-auto">
              Back to Dashboard
            </Button>
          </Link>
        </div>
      </Card>
    </div>
  )
}

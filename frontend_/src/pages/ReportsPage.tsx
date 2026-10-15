import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorState } from '@/components/ui/EmptyState'
import { RecommendationBadge, RiskBadge } from '@/components/ui/StatusBadge'
import { Skeleton } from '@/components/ui/Skeleton'
import { formatDate } from '@/lib/utils'
import { reportService } from '@/services/reportService'
import type { AuditReport } from '@/types'

export function ReportsPage() {
  const [reports, setReports] = useState<AuditReport[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    reportService
      .listCompleted()
      .then(setReports)
      .catch(() => setError('Unable to load reports'))
  }, [])

  if (error) return <ErrorState title="Unable to load reports" message={error} />
  if (!reports) return <Skeleton className="h-64" />
  if (!reports.length) {
    return (
      <EmptyState
        title="No reports yet"
        message="Completed audits will appear here with their readiness, risk, and recommendation."
        actionLabel="Start New Audit"
        onAction={() => {
          window.location.href = '/audit/new'
        }}
      />
    )
  }

  return (
    <div>
      <PageHeader title="Reports" subtitle="Completed compliance reports ready for review." />
      <div className="grid gap-4 md:grid-cols-2">
        {reports.map((report) => (
          <Card key={report.auditId} className="p-5">
            <p className="text-xs text-muted">{formatDate(report.auditDate)}</p>
            <h2 className="mt-1 text-lg font-semibold text-ink">{report.appName}</h2>
            <p className="font-mono text-xs text-muted">{report.packageName}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <RiskBadge risk={report.overallRisk} />
              <RecommendationBadge value={report.recommendation} />
            </div>
            <p className="mt-4 text-sm font-semibold text-ink">{report.readinessScore}% readiness</p>
            <Link to={`/audits/${report.auditId}/report`} className="mt-4 inline-block text-sm font-semibold text-primary">
              View Report
            </Link>
          </Card>
        ))}
      </div>
    </div>
  )
}

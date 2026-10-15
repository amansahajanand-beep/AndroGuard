import { useEffect, useState } from 'react'
import { KpiCard } from '@/components/dashboard/KpiCard'
import { CompliancePosture } from '@/components/dashboard/CompliancePosture'
import { Insights } from '@/components/dashboard/Insights'
import { ComplianceByArea } from '@/components/dashboard/ComplianceByArea'
import { RecentAudits } from '@/components/dashboard/RecentAudits'
import { ErrorState } from '@/components/ui/EmptyState'
import { Skeleton } from '@/components/ui/Skeleton'
import { greetingForHour } from '@/lib/utils'
import { dashboardService } from '@/services/dashboardService'
import type { DashboardData } from '@/types'

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  function load() {
    setLoading(true)
    setError('')
    dashboardService
      .getOverview()
      .then(setData)
      .catch(() => setError('Unable to load dashboard'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  if (loading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-12 w-80" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-28" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !data) {
    return <ErrorState title="Unable to load dashboard" message={error || 'Try again in a moment.'} onRetry={load} />
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">
          {greetingForHour()}, {data.userName}!
        </h1>
        <p className="mt-1 text-sm text-muted">Here's an overview of your compliance audits and activity.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {data.kpis.map((metric) => (
          <KpiCard key={metric.id} metric={metric} />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <CompliancePosture value={data.averageReadiness} recommendation={data.postureRecommendation} />
        <Insights items={data.insights} />
        <ComplianceByArea areas={data.complianceByArea} />
      </div>
      <RecentAudits audits={data.recentAudits} />
    </div>
  )
}

import { Card, CardHeader } from '@/components/ui/Card'
import { ComplianceBadge } from '@/components/ui/StatusBadge'
import { ProgressBar } from '@/components/ui/ProgressBar'
import type { ComplianceArea } from '@/types'

function areaTone(status: ComplianceArea['status']): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'COMPLIANT') return 'success'
  if (status === 'REVIEW_REQUIRED') return 'warning'
  if (status === 'NON_COMPLIANT') return 'danger'
  return 'info'
}

export function ComplianceByArea({ areas }: { areas: ComplianceArea[] }) {
  return (
    <Card>
      <CardHeader title="Compliance by Area" />
      <div className="space-y-4 px-5 py-5">
        {areas.map((area) => (
          <div key={area.id}>
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <span className="text-sm font-medium text-ink">{area.name}</span>
              <ComplianceBadge status={area.status} />
            </div>
            <ProgressBar value={area.score} tone={areaTone(area.status)} />
          </div>
        ))}
      </div>
    </Card>
  )
}

import { Card, CardHeader } from '@/components/ui/Card'
import { ProgressBar } from '@/components/ui/ProgressBar'
import type { ComplianceInsight } from '@/types'

const tones: Record<ComplianceInsight['status'], 'success' | 'warning' | 'danger' | 'info'> = {
  COMPLIANT: 'success',
  REVIEW_REQUIRED: 'warning',
  NON_COMPLIANT: 'danger',
  NOT_VERIFIABLE: 'info',
}

export function Insights({ items }: { items: ComplianceInsight[] }) {
  return (
    <Card>
      <CardHeader title="Insights" subtitle="Compliance distribution" />
      <div className="space-y-4 px-5 py-5">
        {items.map((item) => (
          <div key={item.status}>
            <div className="mb-1.5 flex items-center justify-between text-sm">
              <span className="font-medium text-ink">{item.label}</span>
              <span className="text-xs font-semibold text-muted">{item.percent}%</span>
            </div>
            <ProgressBar value={item.percent} tone={tones[item.status]} />
          </div>
        ))}
      </div>
    </Card>
  )
}

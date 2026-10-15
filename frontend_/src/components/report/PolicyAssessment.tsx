import { Card } from '@/components/ui/Card'
import { ComplianceBadge } from '@/components/ui/StatusBadge'
import type { PolicyAssessmentItem } from '@/types'

export function PolicyAssessment({ items }: { items: PolicyAssessmentItem[] }) {
  return (
    <div className="space-y-4">
      {items.map((item) => (
        <Card key={item.id} className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h3 className="text-sm font-semibold text-ink">{item.policyName}</h3>
            <ComplianceBadge status={item.assessment} />
          </div>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-muted">Requirement</dt>
              <dd className="mt-1 text-sm text-ink">{item.requirement}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence</dt>
              <dd className="mt-1 text-sm text-ink">{item.evidence}</dd>
            </div>
          </dl>
        </Card>
      ))}
    </div>
  )
}

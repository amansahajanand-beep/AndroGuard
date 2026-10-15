import { Card, CardHeader } from '@/components/ui/Card'
import { ComplianceBadge } from '@/components/ui/StatusBadge'
import type { ComplianceArea } from '@/types'

export function ComplianceMatrix({ areas }: { areas: ComplianceArea[] }) {
  return (
    <Card>
      <CardHeader title="Compliance Status by Area" />
      <ul className="divide-y divide-line dark:divide-night-border">
        {areas.map((area) => (
          <li key={area.id} className="flex items-start justify-between gap-3 px-5 py-3">
            <div>
              <p className="text-sm font-medium text-ink">{area.name}</p>
              {area.summary ? <p className="mt-1 text-xs text-muted">{area.summary}</p> : null}
            </div>
            <ComplianceBadge status={area.status} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

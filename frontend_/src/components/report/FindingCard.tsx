import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { ComplianceBadge, RiskBadge } from '@/components/ui/StatusBadge'
import { cn } from '@/lib/utils'
import type { RiskFinding } from '@/types'

export function FindingCard({ finding }: { finding: RiskFinding }) {
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <button type="button" className="flex w-full items-start justify-between gap-4 px-5 py-4 text-left" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <div>
          <p className="text-sm font-semibold text-ink">{finding.finding}</p>
          <p className="mt-1 text-xs text-muted">{finding.category} · {finding.policyRequirement}</p>
        </div>
        <div className="flex items-center gap-2">
          <RiskBadge risk={finding.riskLevel} />
          <ChevronDown size={16} className={cn('text-muted transition', open && 'rotate-180')} />
        </div>
      </button>
      {open ? (
        <div className="space-y-3 border-t border-line px-5 py-4 text-sm dark:border-night-border">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence</p>
            <p className="mt-1 text-ink">{finding.evidence}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Policy Requirement</p>
            <p className="mt-1 text-ink">{finding.policyRequirement}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Recommended Action</p>
            <p className="mt-1 text-ink">{finding.recommendedAction}</p>
          </div>
          <ComplianceBadge status={finding.status} />
        </div>
      ) : null}
    </Card>
  )
}

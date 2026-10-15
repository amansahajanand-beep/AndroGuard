import type { ComplianceStatus, AuditStatus, RiskLevel, SubmissionRecommendation } from '@/types'
import { Badge } from '@/components/ui/Badge'
import { auditStatusLabel, complianceLabel, recommendationLabel, recommendationTone, riskLabel } from '@/lib/status'

export function StatusBadge({ status }: { status: AuditStatus }) {
  const tone =
    status === 'COMPLETED' ? 'success' : status === 'FAILED' ? 'danger' : status === 'PENDING' ? 'warning' : 'info'
  return <Badge tone={tone}>{auditStatusLabel(status)}</Badge>
}

export function ComplianceBadge({ status }: { status: ComplianceStatus }) {
  const tone =
    status === 'COMPLIANT'
      ? 'success'
      : status === 'REVIEW_REQUIRED'
        ? 'warning'
        : status === 'NON_COMPLIANT'
          ? 'danger'
          : 'info'
  return <Badge tone={tone}>{complianceLabel(status)}</Badge>
}

export function RiskBadge({ risk }: { risk: RiskLevel }) {
  const tone = risk === 'CRITICAL' || risk === 'HIGH' ? 'danger' : risk === 'MEDIUM' ? 'warning' : 'success'
  return <Badge tone={tone}>{riskLabel(risk)}</Badge>
}

export function RecommendationBadge({ value }: { value: SubmissionRecommendation }) {
  return <Badge tone={recommendationTone(value)}>{recommendationLabel(value)}</Badge>
}

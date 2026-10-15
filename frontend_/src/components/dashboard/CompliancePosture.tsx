import { Card, CardHeader } from '@/components/ui/Card'
import { CircularProgress } from '@/components/ui/CircularProgress'
import { recommendationTone } from '@/lib/status'
import type { SubmissionRecommendation } from '@/types'

export function CompliancePosture({ value, recommendation }: { value: number; recommendation: SubmissionRecommendation }) {
  return (
    <Card>
      <CardHeader title="Compliance Posture" subtitle="Average readiness across completed audits" />
      <div className="flex justify-center px-5 py-6">
        <CircularProgress value={value} label="Average Readiness" tone={recommendationTone(recommendation)} />
      </div>
    </Card>
  )
}

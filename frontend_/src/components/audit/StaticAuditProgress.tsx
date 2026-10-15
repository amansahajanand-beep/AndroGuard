import { useEffect, useState } from 'react'
import { AuditStepper } from '@/components/audit/AuditStepper'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { CircularProgress } from '@/components/ui/CircularProgress'
import { ProgressBar } from '@/components/ui/ProgressBar'
import type { AuditStage } from '@/types'

/**
 * Stages of the single-request (/analyze) audit. The server answers once at the
 * end, so the stage shown here is an estimate based on elapsed time; the last
 * stage stays active until the response arrives.
 */
const STAGES = [
  { id: 'upload', label: 'Uploading APK', seconds: 4 },
  { id: 'manifest', label: 'Reading Manifest & Permissions', seconds: 6 },
  { id: 'code', label: 'Scanning Code & SDKs', seconds: 14 },
  { id: 'assets', label: 'Extracting App Assets', seconds: 6 },
  { id: 'report', label: 'Generating Audit Report', seconds: Infinity },
]

function stateAt(elapsed: number) {
  let remaining = elapsed
  let current = 0
  for (let i = 0; i < STAGES.length - 1; i += 1) {
    if (remaining < STAGES[i].seconds) break
    remaining -= STAGES[i].seconds
    current = i + 1
  }
  const stages: AuditStage[] = STAGES.map((stage, index) => ({
    id: stage.id,
    label: stage.label,
    status: index < current ? 'COMPLETED' : index === current ? 'CURRENT' : 'PENDING',
  }))
  // Eases toward 92% so the bar keeps moving but never claims to be finished early.
  const progress = Math.round(92 * (1 - Math.exp(-elapsed / 22)))
  return { stages, progress }
}

export function StaticAuditProgress({ appName }: { appName: string }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const handle = window.setInterval(() => setElapsed((Date.now() - started) / 1000), 500)
    return () => window.clearInterval(handle)
  }, [])

  const { stages, progress } = stateAt(elapsed)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit in Progress"
        subtitle="Static analysis of your APK is running. Keep this page open."
        actions={<Badge tone="info">Processing</Badge>}
      />
      <ProgressBar value={progress} />
      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Audit stages</h2>
          <AuditStepper stages={stages} />
        </Card>
        <Card className="flex flex-col items-center justify-center p-8 text-center">
          <CircularProgress value={progress} label="In progress" />
          <p className="mt-4 max-w-xs text-sm text-muted">
            AndroGuard is reviewing {appName || 'your app'} against Google Play requirements. You will be taken to the
            report as soon as it is ready.
          </p>
        </Card>
      </div>
    </div>
  )
}

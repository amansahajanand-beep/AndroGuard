import { Link } from 'react-router-dom'
import { Card, CardHeader } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { RiskBadge, StatusBadge } from '@/components/ui/StatusBadge'
import { formatDate } from '@/lib/utils'
import { recommendationTone } from '@/lib/status'
import type { Audit } from '@/types'

export function RecentAudits({ audits }: { audits: Audit[] }) {
  return (
    <Card>
      <CardHeader title="Recent Audits" subtitle="Latest compliance runs" />
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-muted">
            <tr className="border-b border-line dark:border-night-border">
              <th className="px-5 py-3 font-semibold">Date</th>
              <th className="px-5 py-3 font-semibold">App Name</th>
              <th className="px-5 py-3 font-semibold">APK</th>
              <th className="px-5 py-3 font-semibold">Readiness</th>
              <th className="px-5 py-3 font-semibold">Risk</th>
              <th className="px-5 py-3 font-semibold">Status</th>
              <th className="px-5 py-3 font-semibold">Action</th>
            </tr>
          </thead>
          <tbody>
            {audits.map((audit) => (
              <tr key={audit.id} className="border-b border-line last:border-0 dark:border-night-border">
                <td className="whitespace-nowrap px-5 py-3 text-muted">{formatDate(audit.createdAt)}</td>
                <td className="px-5 py-3 font-medium text-ink">{audit.appName}</td>
                <td className="px-5 py-3 font-mono text-xs text-muted">{audit.apkName}</td>
                <td className="px-5 py-3">
                  {audit.status === 'COMPLETED' ? (
                    <Badge tone={recommendationTone(audit.recommendation)}>{`${audit.readinessScore}%`}</Badge>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="px-5 py-3">{audit.status === 'COMPLETED' ? <RiskBadge risk={audit.overallRisk} /> : '—'}</td>
                <td className="px-5 py-3">
                  <StatusBadge status={audit.status} />
                </td>
                <td className="px-5 py-3">
                  {audit.status === 'COMPLETED' ? (
                    <Link to={`/audits/${audit.id}/report`} className="font-semibold text-primary">
                      View Report
                    </Link>
                  ) : (
                    <Link to={`/audit/${audit.id}/processing`} className="font-semibold text-primary">
                      View Progress
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

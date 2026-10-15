import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState, ErrorState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import { Badge } from '@/components/ui/Badge'
import { RiskBadge, StatusBadge } from '@/components/ui/StatusBadge'
import { Skeleton } from '@/components/ui/Skeleton'
import { formatDate } from '@/lib/utils'
import { recommendationTone } from '@/lib/status'
import { auditService } from '@/services/auditService'
import type { Audit, AuditFilters, PaginatedAudits } from '@/types'

const emptyFilters: AuditFilters = {
  dateFrom: '',
  dateTo: '',
  appName: '',
  risk: '',
  readiness: '',
  status: '',
}

export function AuditLogsPage() {
  const navigate = useNavigate()
  const [draft, setDraft] = useState<AuditFilters>(emptyFilters)
  const [filters, setFilters] = useState<AuditFilters>(emptyFilters)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<PaginatedAudits | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    auditService
      .list(filters, page)
      .then(setData)
      .catch(() => setError('Unable to load audits'))
      .finally(() => setLoading(false))
  }, [page, filters])

  return (
    <div className="space-y-6">
      <PageHeader title="Audit Logs" subtitle="View the history of all application audits." />
      <Card className="p-5">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <Input label="Date from" type="date" value={draft.dateFrom} onChange={(event) => setDraft({ ...draft, dateFrom: event.target.value })} />
          <Input label="Date to" type="date" value={draft.dateTo} onChange={(event) => setDraft({ ...draft, dateTo: event.target.value })} />
          <Input label="App Name" value={draft.appName} onChange={(event) => setDraft({ ...draft, appName: event.target.value })} placeholder="Search app" />
          <Select
            label="Risk"
            value={draft.risk}
            onChange={(event) => setDraft({ ...draft, risk: event.target.value as AuditFilters['risk'] })}
            options={[
              { label: 'All', value: '' },
              { label: 'Critical', value: 'CRITICAL' },
              { label: 'High', value: 'HIGH' },
              { label: 'Medium', value: 'MEDIUM' },
              { label: 'Low', value: 'LOW' },
            ]}
          />
          <Select
            label="Status"
            value={draft.status}
            onChange={(event) => setDraft({ ...draft, status: event.target.value as AuditFilters['status'] })}
            options={[
              { label: 'All', value: '' },
              { label: 'Processing', value: 'PROCESSING' },
              { label: 'Completed', value: 'COMPLETED' },
              { label: 'Failed', value: 'FAILED' },
            ]}
          />
          <Select
            label="Readiness"
            value={draft.readiness ?? ''}
            onChange={(event) => setDraft({ ...draft, readiness: event.target.value })}
            options={[
              { label: 'All', value: '' },
              { label: '90%+', value: '90+' },
              { label: '70–89%', value: '70-89' },
              { label: 'Below 70%', value: 'below-70' },
            ]}
          />
        </div>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <Button
            onClick={() => {
              setPage(1)
              setFilters(draft)
            }}
          >
            Apply Filters
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              setDraft(emptyFilters)
              setFilters(emptyFilters)
              setPage(1)
            }}
          >
            Clear
          </Button>
        </div>
      </Card>
      {loading ? (
        <Skeleton className="h-64" />
      ) : error ? (
        <ErrorState title="Unable to load audits" message={error} onRetry={() => setFilters({ ...filters })} />
      ) : !data?.items.length ? (
        <EmptyState
          title="No audits yet"
          message="No audits have been run yet. Start your first APK compliance audit."
          actionLabel="Start New Audit"
          onAction={() => navigate('/audit/new')}
        />
      ) : (
        <>
          <Card className="hidden overflow-x-auto md:block">
            <table className="min-w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-muted">
                <tr className="border-b border-line dark:border-night-border">
                  <th className="px-5 py-3">Date</th>
                  <th className="px-5 py-3">APK File</th>
                  <th className="px-5 py-3">App Name</th>
                  <th className="px-5 py-3">Readiness Score</th>
                  <th className="px-5 py-3">Overall Risk</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((audit) => (
                  <AuditRow key={audit.id} audit={audit} />
                ))}
              </tbody>
            </table>
          </Card>
          <div className="space-y-3 md:hidden">
            {data.items.map((audit) => (
              <Card key={audit.id} className="p-4">
                <p className="font-semibold text-ink">{audit.appName}</p>
                <p className="text-xs text-muted">{formatDate(audit.createdAt)} · {audit.apkName}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <StatusBadge status={audit.status} />
                  {audit.status === 'COMPLETED' ? <RiskBadge risk={audit.overallRisk} /> : null}
                </div>
                <AuditAction audit={audit} />
              </Card>
            ))}
          </div>
          <div className="flex items-center justify-between text-sm">
            <p className="text-muted">
              Page {data.page} of {data.totalPages}
            </p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={data.page <= 1} onClick={() => setPage((value) => value - 1)}>
                Previous
              </Button>
              <Button variant="outline" size="sm" disabled={data.page >= data.totalPages} onClick={() => setPage((value) => value + 1)}>
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AuditRow({ audit }: { audit: Audit }) {
  return (
    <tr className="border-b border-line last:border-0 dark:border-night-border">
      <td className="whitespace-nowrap px-5 py-3 text-muted">{formatDate(audit.createdAt)}</td>
      <td className="px-5 py-3 text-muted">{audit.apkName}</td>
      <td className="px-5 py-3 font-medium text-ink">{audit.appName}</td>
      <td className="px-5 py-3">
        {audit.status === 'COMPLETED' ? <Badge tone={recommendationTone(audit.recommendation)}>{`${audit.readinessScore}%`}</Badge> : '—'}
      </td>
      <td className="px-5 py-3">{audit.status === 'COMPLETED' ? <RiskBadge risk={audit.overallRisk} /> : '—'}</td>
      <td className="px-5 py-3">
        <StatusBadge status={audit.status} />
      </td>
      <td className="px-5 py-3">
        <AuditAction audit={audit} />
      </td>
    </tr>
  )
}

function AuditAction({ audit }: { audit: Audit }) {
  if (audit.status === 'COMPLETED') {
    return (
      <Link to={`/audits/${audit.id}/report`} className="text-sm font-semibold text-primary">
        View Report
      </Link>
    )
  }
  return (
    <Link to={`/audit/${audit.id}/processing`} className="text-sm font-semibold text-primary">
      View Progress
    </Link>
  )
}

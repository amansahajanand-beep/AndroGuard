import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AiReviewCard } from '@/components/report/AiReviewCard'
import { PolicyAnalysisCard } from '@/components/report/PolicyAnalysisCard'
import { AdPlacementReport } from '@/components/report/AdPlacementReport'
import { ComplianceMatrix } from '@/components/report/ComplianceMatrix'
import { DetailedFindings } from '@/components/report/DetailedFindings'
import { FindingCard } from '@/components/report/FindingCard'
import { PolicyAssessment } from '@/components/report/PolicyAssessment'
import { RiskSummary } from '@/components/report/RiskSummary'
import { Card, CardHeader } from '@/components/ui/Card'
import { CircularProgress } from '@/components/ui/CircularProgress'
import { ErrorState } from '@/components/ui/EmptyState'
import { RecommendationBadge, RiskBadge } from '@/components/ui/StatusBadge'
import { Skeleton } from '@/components/ui/Skeleton'
import { formatDate } from '@/lib/utils'
import { recommendationLabel, recommendationTone } from '@/lib/status'
import { reportService } from '@/services/reportService'
import type { AuditReport } from '@/types'

const sections = [
  { id: 'summary', label: 'Executive Summary' },
  { id: 'readiness', label: 'Submission Readiness' },
  { id: 'risk', label: 'Findings Summary' },
  { id: 'policy', label: 'Policy Assessment' },
  { id: 'areas', label: 'Compliance by Area' },
  { id: 'ads', label: 'Ad Placements' },
  { id: 'top', label: 'Top Findings' },
  { id: 'detailed', label: 'Detailed Findings' },
  { id: 'missing', label: 'Missing Information' },
  { id: 'actions', label: 'Recommended Actions' },
  { id: 'final', label: 'Final Recommendation' },
  { id: 'limits', label: 'Audit Limitations' },
]

export function AuditReportPage() {
  const { id = '' } = useParams()
  const [report, setReport] = useState<AuditReport | null>(null)
  const [error, setError] = useState('')
  const [active, setActive] = useState(sections[0].id)

  useEffect(() => {
    reportService
      .getByAuditId(id)
      .then(setReport)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Report unavailable'))
  }, [id])

  if (error) {
    return <ErrorState title="Report unavailable" message={error} />
  }
  if (!report) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-96" />
      </div>
    )
  }

  return (
    <div className="lg:grid lg:grid-cols-[220px_1fr] lg:gap-6">
      <aside className="mb-6 lg:mb-0">
        <nav className="sticky top-24 space-y-1 rounded-xl border border-line bg-white p-3 dark:border-night-border dark:bg-night-card">
          {sections.map((section) => (
            <a
              key={section.id}
              href={`#${section.id}`}
              onClick={() => setActive(section.id)}
              className={`block rounded-lg px-3 py-2 text-[13px] font-medium ${active === section.id ? 'bg-brand text-primary-ink' : 'text-muted hover:bg-subtle'}`}
            >
              {section.label}
            </a>
          ))}
        </nav>
      </aside>
      <div className="space-y-6">
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Audit Report</p>
              <h1 className="mt-1 text-2xl font-bold text-ink">{report.appName}</h1>
              <p className="mt-1 font-mono text-xs text-muted">
                {report.packageName} · v{report.version} · {formatDate(report.auditDate)} · Target SDK {report.targetSdk}
              </p>
            </div>
            <Link to="/audits" className="text-sm font-semibold text-primary">
              Back to logs
            </Link>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <SummaryTile label="Readiness Score" value={`${report.readinessScore}%`} tone={recommendationTone(report.recommendation)} />
            <div className="rounded-xl border border-line p-4 dark:border-night-border">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Overall Risk</p>
              <div className="mt-3">
                <RiskBadge risk={report.overallRisk} />
              </div>
            </div>
            <div className="rounded-xl border border-line p-4 dark:border-night-border">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Final Recommendation</p>
              <div className="mt-3">
                <RecommendationBadge value={report.recommendation} />
              </div>
            </div>
          </div>
        </Card>

        <section id="summary">
          <Card>
            <CardHeader title="Executive Summary" />
            <p className="px-5 py-4 text-sm leading-6 text-ink">{report.executiveSummary}</p>
          </Card>
        </section>

        {report.aiReview ? (
          <section id="ai">
            <AiReviewCard review={report.aiReview} />
          </section>
        ) : null}

        {report.policyAnalysis ? (
          <section id="policy-check">
            <PolicyAnalysisCard analysis={report.policyAnalysis} />
          </section>
        ) : null}

        <section id="readiness" className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card className="flex items-center justify-center p-6">
            <CircularProgress
              value={report.submissionReadiness.percent}
              label="Readiness"
              tone={recommendationTone(report.submissionReadiness.status)}
            />
          </Card>
          <Card className="p-5">
            <h2 className="text-[15px] font-semibold text-ink">Submission Readiness</h2>
            <div className="mt-3">
              <RecommendationBadge value={report.submissionReadiness.status} />
            </div>
            <p className="mt-4 text-sm leading-6 text-muted">{report.submissionReadiness.summary}</p>
          </Card>
        </section>

        <section id="risk">
          <h2 className="mb-3 text-[15px] font-semibold text-ink">Risk Finding Summary</h2>
          <RiskSummary counts={report.riskCounts} />
        </section>

        <section id="policy">
          <h2 className="mb-3 text-[15px] font-semibold text-ink">Google Play Policy Assessment</h2>
          <div className="grid gap-4 xl:grid-cols-[1.4fr_0.8fr]">
            <PolicyAssessment items={report.policyAssessments} />
            <ComplianceMatrix areas={report.complianceByArea} />
          </div>
        </section>

        <section id="areas" className="sr-only">
          Compliance by area
        </section>

        <section id="ads">
          <h2 className="mb-3 text-[15px] font-semibold text-ink">Ad Placements by Screen</h2>
          <AdPlacementReport analysis={report.adAnalysis} />
        </section>

        <section id="top" className="space-y-3">
          <h2 className="text-[15px] font-semibold text-ink">Top Findings</h2>
          {report.topFindings.map((item) => (
            <FindingCard key={item.id} finding={item} />
          ))}
        </section>

        <section id="detailed">
          <h2 className="mb-3 text-[15px] font-semibold text-ink">Detailed Findings</h2>
          <DetailedFindings findings={report.detailedFindings} />
        </section>

        <section id="missing">
          <Card>
            <CardHeader title="Missing Information" />
            <div className="px-5 py-4">
              {report.missingInformation.length ? (
                <ul className="list-disc space-y-2 pl-5 text-sm text-ink">
                  {report.missingInformation.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted">No missing information was returned for this audit.</p>
              )}
            </div>
          </Card>
        </section>

        <section id="actions">
          <Card>
            <CardHeader title="Recommended Actions" />
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-xs uppercase text-muted">
                  <tr className="border-b border-line dark:border-night-border">
                    <th className="px-5 py-3">Priority</th>
                    <th className="px-5 py-3">Issue</th>
                    <th className="px-5 py-3">Recommended Action</th>
                    <th className="px-5 py-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {report.recommendedActions.map((item) => (
                    <tr key={item.id} className="border-b border-line last:border-0 dark:border-night-border">
                      <td className="px-5 py-3 font-semibold">{item.priority}</td>
                      <td className="px-5 py-3">{item.issue}</td>
                      <td className="px-5 py-3 text-muted">{item.recommendedAction}</td>
                      <td className="px-5 py-3 text-muted">{item.status.replace('_', ' ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </section>

        <section id="final">
          <Card className="border-2 border-primary/20 p-6 text-center">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Final Submission Recommendation</p>
            <p className="mt-3 text-2xl font-bold text-ink">{recommendationLabel(report.recommendation)}</p>
            <div className="mt-4 flex justify-center">
              <RecommendationBadge value={report.recommendation} />
            </div>
          </Card>
        </section>

        <section id="limits">
          <Card>
            <CardHeader title="Audit Limitations" />
            <ul className="list-disc space-y-2 px-5 py-4 pl-10 text-sm text-muted">
              {report.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </Card>
        </section>
      </div>
    </div>
  )
}

function SummaryTile({ label, value, tone }: { label: string; value: string; tone: 'success' | 'warning' | 'danger' }) {
  const classes = {
    success: 'bg-success/10 text-success',
    warning: 'bg-warning/10 text-warning',
    danger: 'bg-danger/10 text-danger',
  }
  return (
    <div className={`rounded-xl p-4 ${classes[tone]}`}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-2 text-2xl font-bold">{value}</p>
    </div>
  )
}

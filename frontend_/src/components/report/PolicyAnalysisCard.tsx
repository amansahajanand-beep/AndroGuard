import { Badge } from '@/components/ui/Badge'
import { Card, CardHeader } from '@/components/ui/Card'
import { AiBadge, EvidenceList } from '@/components/report/AiReviewCard'
import type { PolicyAnalysis, PolicyIssue } from '@/types'

const SEVERITY_TONE = { high: 'danger', medium: 'warning', low: 'info' } as const

const TYPE_LABEL: Record<PolicyIssue['type'], string> = {
  undisclosed_data_use: 'Not disclosed in the policy',
  contradiction: 'Policy contradicts the app',
  vague_or_missing: 'Vague or missing',
}

const UNAVAILABLE_TITLE: Record<string, string> = {
  no_policy: 'No privacy policy to compare',
  unavailable: 'The privacy policy could not be read',
}

/** What the privacy policy claims versus what the app does. Quotes are exact; evidence comes from the audit data. */
export function PolicyAnalysisCard({ analysis }: { analysis?: PolicyAnalysis }) {
  if (!analysis) return null

  if (analysis.status !== 'analyzed') {
    return (
      <Card>
        <CardHeader title="Privacy Policy Check" />
        <div className="px-5 py-4">
          <p className="text-sm font-semibold text-ink dark:text-white">
            {UNAVAILABLE_TITLE[analysis.status] ?? 'Not available'}
          </p>
          <p className="mt-1 text-sm text-muted">{analysis.reason}</p>
        </div>
      </Card>
    )
  }

  const facts = new Map(analysis.evidence.map((item) => [item.id, item.text]))
  const claimsById = new Map(analysis.claims.map((claim) => [claim.id, claim]))

  return (
    <Card>
      <CardHeader
        title="Privacy Policy Check"
        subtitle="Compares what the policy says with what the app does. Quotes are copied exactly from the policy and every app behaviour cites audit data."
        action={<AiBadge />}
      />
      <div className="space-y-5 px-5 py-4">
        {analysis.summary ? <p className="text-sm leading-6 text-ink dark:text-slate-200">{analysis.summary}</p> : null}

        {analysis.issues.length ? (
          <ul className="space-y-3">
            {analysis.issues.map((issue) => (
              <li key={issue.title} className="rounded-lg border border-line p-4 dark:border-night-border">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={SEVERITY_TONE[issue.severity]}>{issue.severity}</Badge>
                  <h3 className="text-sm font-semibold text-ink dark:text-white">{issue.title}</h3>
                  <span className="text-xs text-muted">{TYPE_LABEL[issue.type]}</span>
                </div>
                {issue.explanation ? <p className="mt-2 text-sm leading-6 text-muted">{issue.explanation}</p> : null}
                {issue.claimIds.map((id) => {
                  const claim = claimsById.get(id)
                  return claim ? (
                    <blockquote key={id} className="mt-2 border-l-2 border-primary/40 pl-3 text-xs italic text-muted">
                      “{claim.quote}”
                    </blockquote>
                  ) : null
                })}
                {issue.recommendedFix ? (
                  <p className="mt-2 text-sm leading-6 text-ink dark:text-slate-200">
                    <span className="font-semibold">Suggested fix: </span>
                    {issue.recommendedFix}
                  </p>
                ) : null}
                <EvidenceList ids={issue.evidenceIds} facts={facts} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No mismatches were found between the policy and the data the app uses.</p>
        )}

        {analysis.claims.length ? (
          <details className="text-sm">
            <summary className="cursor-pointer font-semibold text-ink dark:text-white">
              What the policy says ({analysis.claims.length})
            </summary>
            <ul className="mt-3 space-y-2">
              {analysis.claims.map((claim) => (
                <li key={claim.id}>
                  <Badge tone="neutral">{claim.topic.replace('_', ' ')}</Badge>
                  <span className="ml-2 text-muted">{claim.statement}</span>
                  <blockquote className="mt-1 border-l-2 border-line pl-3 text-xs italic text-muted dark:border-night-border">
                    “{claim.quote}”
                  </blockquote>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        <p className="text-xs text-muted">
          Read {analysis.charsRead.toLocaleString()} characters of the policy
          {analysis.source ? ` (${analysis.source === 'url' ? 'from the link' : 'from the uploaded file'})` : ''}
          {analysis.truncated ? '; the policy was longer, so only the beginning was compared' : ''}.
          {analysis.unsupportedDropped ? ` ${analysis.unsupportedDropped} unsupported statement(s) were removed.` : ''}
        </p>
      </div>
    </Card>
  )
}

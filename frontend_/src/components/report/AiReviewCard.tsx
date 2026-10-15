import { Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Card, CardHeader } from '@/components/ui/Card'
import type { AiReview } from '@/types'

const SEVERITY_TONE = {
  critical: 'danger',
  high: 'danger',
  medium: 'warning',
  low: 'info',
} as const

export function AiBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 px-2.5 py-1 text-xs font-semibold text-primary">
      <Sparkles size={12} aria-hidden="true" />
      AI-generated
    </span>
  )
}

/** Evidence the AI cited. Each id maps to a fact found in the audit, so every statement can be checked. */
export function EvidenceList({ ids, facts }: { ids: string[]; facts: Map<string, string> }) {
  if (!ids.length) return null
  return (
    <ul className="mt-3 space-y-1.5" aria-label="Evidence">
      {ids.map((id) => (
        <li key={id} className="flex flex-wrap items-baseline gap-x-2 text-xs">
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-muted dark:bg-white/10">{id}</code>
          <span className="text-muted">{facts.get(id) ?? 'Fact recorded in the audit data.'}</span>
        </li>
      ))}
    </ul>
  )
}

/** AI-written explanation of the audit. Kept apart from the rule-based verdicts and labelled as AI output. */
export function AiReviewCard({ review }: { review?: AiReview }) {
  if (!review) return null
  const facts = new Map(review.evidence.map((item) => [item.id, item.text]))
  return (
    <Card>
      <CardHeader
        title="AI Review"
        subtitle="Written by an AI model from this audit's data. Each finding cites the facts it relies on; findings without valid citations are removed."
        action={<AiBadge />}
      />
      <div className="space-y-5 px-5 py-4">
        <p className="text-sm leading-6 text-ink dark:text-slate-200">{review.summary}</p>

        {review.findings.length ? (
          <ul className="space-y-3">
            {review.findings.map((item) => (
              <li key={item.title} className="rounded-lg border border-line p-4 dark:border-night-border">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={SEVERITY_TONE[item.severity]}>{item.severity}</Badge>
                  <h3 className="text-sm font-semibold text-ink dark:text-white">{item.title}</h3>
                </div>
                {item.explanation ? <p className="mt-2 text-sm leading-6 text-muted">{item.explanation}</p> : null}
                {item.recommendedFix ? (
                  <p className="mt-2 text-sm leading-6 text-ink dark:text-slate-200">
                    <span className="font-semibold">Suggested fix: </span>
                    {item.recommendedFix}
                  </p>
                ) : null}
                <EvidenceList ids={item.evidenceIds} facts={facts} />
              </li>
            ))}
          </ul>
        ) : null}

        {review.adNotes ? (
          <p className="text-sm leading-6 text-muted">
            <span className="font-semibold text-ink dark:text-slate-200">Ads: </span>
            {review.adNotes}
          </p>
        ) : null}
        <p className="text-xs text-muted">
          {review.disclaimer}
          {review.unsupportedDropped ? ` ${review.unsupportedDropped} unsupported statement(s) were removed.` : ''}
        </p>
      </div>
    </Card>
  )
}

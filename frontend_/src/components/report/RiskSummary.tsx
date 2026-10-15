import { Card } from '@/components/ui/Card'
import type { RiskCounts } from '@/types'

const items = [
  { key: 'critical', label: 'Critical', className: 'text-danger bg-danger/10' },
  { key: 'high', label: 'High', className: 'text-high bg-high/10' },
  { key: 'medium', label: 'Medium', className: 'text-warning bg-warning/10' },
  { key: 'low', label: 'Low', className: 'text-low bg-low/10' },
] as const

export function RiskSummary({ counts }: { counts: RiskCounts }) {
  return (
    <div className="grid gap-3 sm:grid-cols-4">
      {items.map((item) => (
        <Card key={item.key} className={`p-4 ${item.className}`}>
          <p className="text-xs font-semibold uppercase tracking-wide">{item.label}</p>
          <p className="mt-2 text-2xl font-bold">{counts[item.key]}</p>
        </Card>
      ))}
    </div>
  )
}

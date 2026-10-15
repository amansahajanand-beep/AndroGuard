import { useState } from 'react'
import { FindingCard } from '@/components/report/FindingCard'
import { cn } from '@/lib/utils'
import type { FindingCategory, RiskFinding } from '@/types'

const categories: Array<FindingCategory | 'All'> = [
  'All',
  'Permissions',
  'API',
  'SDK',
  'Privacy',
  'Play Store',
  'Advertising',
  'User Data',
  'Data Safety',
  'Other',
]

export function DetailedFindings({ findings }: { findings: RiskFinding[] }) {
  const [active, setActive] = useState<FindingCategory | 'All'>('All')
  const visible = active === 'All' ? findings : findings.filter((item) => item.category === active)
  return (
    <div>
      <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
        {categories.map((category) => (
          <button
            key={category}
            type="button"
            onClick={() => setActive(category)}
            className={cn(
              'whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-semibold',
              active === category ? 'bg-brand text-primary-ink' : 'bg-white text-muted ring-1 ring-line dark:bg-night-raised dark:ring-night-border',
            )}
          >
            {category}
          </button>
        ))}
      </div>
      <div className="space-y-3">
        {visible.length ? visible.map((item) => <FindingCard key={item.id} finding={item} />) : <p className="text-sm text-muted">No findings in this category.</p>}
      </div>
    </div>
  )
}

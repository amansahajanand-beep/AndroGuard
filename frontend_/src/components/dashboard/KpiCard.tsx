import { AlertTriangle, CalendarDays, Clock, Package, ShieldCheck, Target } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { cn } from '@/lib/utils'
import type { KpiMetric } from '@/types'

const icons = {
  apk: Package,
  clock: Clock,
  shield: ShieldCheck,
  calendar: CalendarDays,
  score: Target,
  alert: AlertTriangle,
}

export function KpiCard({ metric }: { metric: KpiMetric }) {
  const Icon = icons[metric.icon]
  const up = metric.trend.direction === 'up'
  return (
    <Card className="flex items-center justify-between p-4">
      <div>
        <p className="text-xs font-medium text-muted">{metric.label}</p>
        <p className="mt-2 font-mono text-2xl font-bold tabular-nums text-ink">{metric.value}</p>
        <p className={cn('mt-2 text-xs font-semibold', metric.trend.direction === 'down' ? 'text-danger' : 'text-success')}>
          {metric.trend.value} {metric.trend.label}
        </p>
      </div>
      <span className={cn('grid h-11 w-11 place-items-center rounded-full', up ? 'bg-primary/10 text-primary' : 'bg-danger/10 text-danger')}>
        <Icon size={18} />
      </span>
    </Card>
  )
}

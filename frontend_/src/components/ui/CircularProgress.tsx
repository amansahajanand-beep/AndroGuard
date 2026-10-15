import { cn } from '@/lib/utils'

export function CircularProgress({
  value,
  size = 168,
  stroke = 12,
  label,
  caption,
  tone = 'info',
}: {
  value: number
  size?: number
  stroke?: number
  label?: string
  caption?: string
  tone?: 'info' | 'success' | 'warning' | 'danger'
}) {
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (Math.max(0, Math.min(100, value)) / 100) * circumference
  const colors = {
    info: 'rgb(var(--info))',
    success: 'rgb(var(--success))',
    warning: 'rgb(var(--warning))',
    danger: 'rgb(var(--danger))',
  }
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={radius} stroke="currentColor" strokeWidth={stroke} className="text-subtle" fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={colors[tone]}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn('font-mono text-3xl font-bold tabular-nums text-ink')}>{Math.round(value)}%</span>
        {label ? <span className="mt-1 text-xs font-medium text-muted">{label}</span> : null}
        {caption ? <span className="text-[11px] text-muted">{caption}</span> : null}
      </div>
    </div>
  )
}

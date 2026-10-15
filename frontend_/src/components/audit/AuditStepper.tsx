import { Check, Circle, LoaderCircle, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { AuditStage } from '@/types'

export function AuditStepper({ stages }: { stages: AuditStage[] }) {
  return (
    <ol className="space-y-0">
      {stages.map((stage, index) => {
        const done = stage.status === 'COMPLETED'
        const current = stage.status === 'CURRENT'
        const failed = stage.status === 'FAILED'
        return (
          <li key={stage.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  'grid h-8 w-8 place-items-center rounded-full border',
                  done && 'border-success bg-success text-onfill',
                  current && 'border-primary bg-primary text-onfill',
                  failed && 'border-danger bg-danger text-onfill',
                  !done && !current && !failed && 'border-line bg-white text-muted dark:border-night-border',
                )}
                aria-hidden="true"
              >
                {done ? <Check size={14} /> : failed ? <X size={14} /> : current ? <LoaderCircle size={14} className="animate-spin" /> : <Circle size={10} />}
              </span>
              {index < stages.length - 1 ? <span className="min-h-[28px] w-px flex-1 bg-line dark:bg-night-border" /> : null}
            </div>
            <div className="pb-5 pt-1">
              <p className={cn('text-sm font-semibold', current ? 'text-primary' : done ? 'text-ink' : 'text-muted')}>{stage.label}</p>
              <p className="text-xs text-muted">{done ? 'Completed' : current ? 'In progress' : failed ? 'Failed' : 'Pending'}</p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

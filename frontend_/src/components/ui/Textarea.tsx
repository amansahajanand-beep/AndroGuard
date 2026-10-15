import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, error, className, id, ...props },
  ref,
) {
  const inputId = id ?? props.name
  return (
    <label className="block" htmlFor={inputId}>
      {label ? <span className="pg-label">{label}</span> : null}
      <textarea
        id={inputId}
        ref={ref}
        className={cn(
          'min-h-[120px] w-full rounded-lg border border-line bg-white px-3.5 py-3 text-sm text-ink placeholder:text-muted/70 transition focus:border-primary focus:shadow-glow-sm focus:outline-none dark:border-night-border dark:bg-night-raised dark:text-slate-100',
          error && 'border-danger',
          className,
        )}
        aria-invalid={Boolean(error)}
        {...props}
      />
      {error ? <span className="mt-1.5 block text-xs font-medium text-danger">{error}</span> : null}
    </label>
  )
})

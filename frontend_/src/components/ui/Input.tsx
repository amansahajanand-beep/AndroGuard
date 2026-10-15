import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  hint?: string
  error?: string
  rightSlot?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, rightSlot, className, id, ...props },
  ref,
) {
  const inputId = id ?? props.name
  return (
    <label className="block" htmlFor={inputId}>
      {label ? <span className="pg-label">{label}</span> : null}
      <span className="relative block">
        <input
          id={inputId}
          ref={ref}
          className={cn('pg-input', rightSlot ? 'pr-11' : undefined, error && 'border-danger focus:border-danger focus:ring-danger/15', className)}
          aria-invalid={Boolean(error)}
          {...props}
        />
        {rightSlot ? <span className="absolute inset-y-0 right-0 flex items-center pr-3">{rightSlot}</span> : null}
      </span>
      {error ? <span className="mt-1.5 block text-xs font-medium text-danger">{error}</span> : null}
      {hint && !error ? <span className="mt-1.5 block text-xs text-muted">{hint}</span> : null}
    </label>
  )
})

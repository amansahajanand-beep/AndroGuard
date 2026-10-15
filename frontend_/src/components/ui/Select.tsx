import type { SelectHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  options: Array<{ label: string; value: string }>
}

export function Select({ label, options, className, id, ...props }: SelectProps) {
  const inputId = id ?? props.name
  return (
    <label className="block" htmlFor={inputId}>
      {label ? <span className="pg-label">{label}</span> : null}
      <select id={inputId} className={cn('pg-input appearance-none pr-8', className)} {...props}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

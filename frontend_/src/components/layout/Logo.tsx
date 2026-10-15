import { cn } from '@/lib/utils'

export function Logo({ compact = false, light = false }: { compact?: boolean; light?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <svg viewBox="0 0 40 40" className="h-10 w-10 shrink-0 drop-shadow-[0_0_8px_rgba(61,220,132,0.35)]" role="img" aria-label="AndroGuard">
        <path d="M20 3.2 33.2 9.1v10.9c0 8.4-5.6 16.1-13.2 18.3C12.4 34.1 6.8 26.4 6.8 20V9.1L20 3.2Z" fill="#3DDC84" />
        <path d="M14.2 20 18.3 24.1 26 15.8" stroke="#04210F" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </svg>
      {compact ? null : (
        <span className="leading-tight">
          <span className={cn('block text-[15px] font-bold', light ? 'text-[#E6EDF3]' : 'text-ink')}>AndroGuard</span>
          <span className={cn('block font-mono text-[10px] uppercase tracking-wider', light ? 'text-[#8696A8]' : 'text-muted')}>Compliance Auditor</span>
        </span>
      )}
    </div>
  )
}

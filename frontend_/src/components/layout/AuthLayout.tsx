import { Fragment, type ReactNode } from 'react'
import { AndroGuardIllustration } from '@/components/layout/AndroGuardIllustration'
import { GooglePlayBadge } from '@/components/layout/GooglePlayBadge'

const trustItems = [
  {
    label: 'Secure',
    icon: (
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
        <path
          d="M8 1.6 13.2 3.6v4.2c0 3.2-2.2 6-5.2 6.9-3-0.9-5.2-3.7-5.2-6.9V3.6L8 1.6Z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
        <path d="M5.7 8.1 7.2 9.6 10.4 6.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: 'Compliant',
    icon: (
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
        <rect x="2.4" y="2.4" width="11.2" height="11.2" rx="2.2" stroke="currentColor" strokeWidth="1.3" />
        <path d="M5.3 8.2 7.1 10 10.8 6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: 'Trusted',
    icon: (
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
        <path
          d="M8 13.4s-5.2-3.1-5.2-6.4c0-1.7 1.3-3 2.9-3 1 0 1.8.5 2.3 1.3.5-.8 1.3-1.3 2.3-1.3 1.6 0 2.9 1.3 2.9 3 0 3.3-5.2 6.4-5.2 6.4Z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
        <path d="M5.4 7.6h5.2M6.2 9.2h3.6" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      </svg>
    ),
  },
]

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="relative hidden overflow-hidden border-r border-[#223041] bg-[#0B0F14] px-12 py-10 text-white lg:flex lg:flex-col xl:px-16">
        <div className="bg-dots-always pointer-events-none absolute inset-0" />
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_46%,rgba(61,220,132,0.10)_0%,rgba(11,15,20,0)_60%)]" />

        <div className="relative">
          <div className="flex items-center gap-3">
            <svg viewBox="0 0 40 40" className="h-11 w-11 shrink-0" aria-hidden="true">
              <path
                d="M20 3.2 33.2 9.1v10.9c0 8.4-5.6 16.1-13.2 18.3C12.4 34.1 6.8 26.4 6.8 20V9.1L20 3.2Z"
                fill="#3DDC84"
              />
              <path
                d="M14.2 20 18.3 24.1 26 15.8"
                stroke="#04210F"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </svg>
            <span className="leading-tight">
              <span className="block text-[22px] font-bold tracking-tight text-white">AndroGuard</span>
              <span className="block text-[13px] font-normal text-[#8696A8]">Google Play Compliance Auditor</span>
            </span>
          </div>

          <h1 className="mt-10 max-w-xl text-[42px] font-bold leading-[1.15] tracking-tight text-white">
            Verify. Secure. <span className="text-[#3DDC84]">Publish.</span>
          </h1>
          <p className="mt-4 max-w-lg text-[16px] leading-relaxed text-white/90">
            Scan your Android app against Google Play policies and get a detailed compliance report.
          </p>
        </div>

        <div className="relative flex min-h-0 flex-1 items-center justify-center py-6">
          <AndroGuardIllustration />
        </div>

        <div className="relative space-y-7">
          <GooglePlayBadge />
          <div className="flex items-center justify-center gap-5 text-[13px] font-medium text-[#8696A8]">
            {trustItems.map((item, index) => (
              <Fragment key={item.label}>
                {index > 0 ? <span className="h-1 w-1 rounded-full bg-[#8696A8]" aria-hidden="true" /> : null}
                <span className="inline-flex items-center gap-1.5">
                  {item.icon}
                  {item.label}
                </span>
              </Fragment>
            ))}
          </div>
        </div>
      </section>
      <section className="flex items-center justify-center bg-dots bg-white px-4 py-10 dark:bg-night-card">
        <div className="w-full max-w-[420px]">{children}</div>
      </section>
    </div>
  )
}

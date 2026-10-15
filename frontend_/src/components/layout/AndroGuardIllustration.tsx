import { useId } from 'react'

export function AndroGuardIllustration() {
  const uid = useId().replace(/:/g, '')
  const id = (name: string) => `${uid}-${name}`

  return (
    <div className="relative mx-auto w-full max-w-[640px]" aria-hidden="true">
      <div className="pointer-events-none absolute left-1/2 top-[50%] h-[70%] w-[70%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#12A15B]/40 blur-[100px]" />
      <svg
        width="560"
        height="400"
        viewBox="0 0 560 400"
        className="relative h-auto w-full overflow-visible"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id={id('phoneGlow')} x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id={id('softGlow')} x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="10" />
          </filter>
          <filter id={id('nodeGlow')} x="-120%" y="-120%" width="340%" height="340%">
            <feGaussianBlur stdDeviation="2.4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <linearGradient id={id('phoneBody')} x1="221" y1="74" x2="339" y2="304">
            <stop offset="0" stopColor="#111821" />
            <stop offset="1" stopColor="#0B0F14" />
          </linearGradient>
          <linearGradient id={id('screen')} x1="232" y1="92" x2="328" y2="278">
            <stop offset="0" stopColor="#223041" />
            <stop offset="1" stopColor="#111821" />
          </linearGradient>
          <linearGradient id={id('shield')} x1="286" y1="158" x2="392" y2="286" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#2FBF71" />
            <stop offset="0.45" stopColor="#2FBF71" />
            <stop offset="1" stopColor="#12A15B" />
          </linearGradient>
          <linearGradient id={id('shieldInner')} x1="300" y1="176" x2="372" y2="268" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#0E7A45" />
            <stop offset="1" stopColor="#0B5F37" />
          </linearGradient>
          <linearGradient id={id('android')} x1="260" y1="132" x2="260" y2="210">
            <stop offset="0" stopColor="#86EF6A" />
            <stop offset="1" stopColor="#3DDC84" />
          </linearGradient>
        </defs>

        <ellipse cx="280" cy="198" rx="168" ry="150" fill="#12A15B" opacity="0.18" filter={`url(#${id('softGlow')})`} />

        <ellipse
          cx="280"
          cy="190"
          rx="198"
          ry="128"
          stroke="#22D3EE"
          strokeOpacity="0.36"
          strokeWidth="1.15"
        />
        <ellipse
          cx="280"
          cy="190"
          rx="174"
          ry="112"
          stroke="#8FE9B4"
          strokeOpacity="0.3"
          strokeWidth="1.05"
        />
        <ellipse
          cx="280"
          cy="190"
          rx="128"
          ry="50"
          transform="rotate(-24 280 190)"
          stroke="#2FBF71"
          strokeOpacity="0.26"
          strokeWidth="1"
        />
        <ellipse
          cx="280"
          cy="190"
          rx="128"
          ry="50"
          transform="rotate(24 280 190)"
          stroke="#2FBF71"
          strokeOpacity="0.26"
          strokeWidth="1"
        />

        <circle cx="132" cy="168" r="3.1" fill="#8FE9B4" filter={`url(#${id('nodeGlow')})`} />
        <circle cx="148" cy="252" r="2.2" fill="#22D3EE" />
        <circle cx="232" cy="62" r="2.4" fill="#C5F3D9" filter={`url(#${id('nodeGlow')})`} />
        <circle cx="408" cy="86" r="2.6" fill="#E3FAEE" />
        <circle cx="428" cy="198" r="4.6" fill="#2FBF71" filter={`url(#${id('nodeGlow')})`} />
        <circle cx="372" cy="318" r="2.1" fill="#8FE9B4" />
        <circle cx="196" cy="330" r="1.8" fill="#22D3EE" />

        <path
          d="M392 118 C392 108 400 100 410 100 C415 90 425 84 438 84 C454 84 466 94 468 108 C478 108 486 116 486 126 C486 138 476 146 464 146 H408 C398 146 392 138 392 118Z"
          fill="none"
          stroke="#E3FAEE"
          strokeOpacity="0.9"
          strokeWidth="1.5"
        />

        <path
          d="M118 248 C118 234 130 224 144 224 C150 210 164 202 180 202 C200 202 216 214 220 232 C232 232 242 242 242 254 C242 268 230 278 216 278 H138 C126 278 118 268 118 248Z"
          fill="#2B3B4F"
        />

        <g transform="translate(280 190) scale(1.12) translate(-280 -190)">
          <g filter={`url(#${id('phoneGlow')})`}>
            <rect x="221" y="74" width="118" height="232" rx="26" fill={`url(#${id('phoneBody')})`} stroke="#22D3EE" strokeWidth="2.2" />
          </g>
          <rect x="225" y="78" width="110" height="224" rx="23" stroke="#A5F3FC" strokeOpacity="0.35" strokeWidth="1" />
          <rect x="233" y="94" width="94" height="192" rx="16" fill={`url(#${id('screen')})`} />
          <rect x="258" y="80" width="44" height="7" rx="3.5" fill="#0B0F14" />

          <g>
            <path d="M262 138 L256 128" stroke="#4ADE80" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M298 138 L304 128" stroke="#4ADE80" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M257 158 C257 142 266 136 280 136 C294 136 303 142 303 158 Z" fill={`url(#${id('android')})`} />
            <circle cx="270" cy="148" r="2.3" fill="#064E3B" />
            <circle cx="290" cy="148" r="2.3" fill="#064E3B" />
            <rect x="257" y="162" width="46" height="38" rx="8" fill={`url(#${id('android')})`} />
            <rect x="246" y="168" width="9" height="24" rx="4.5" fill="#3DDC84" />
            <rect x="305" y="168" width="9" height="24" rx="4.5" fill="#3DDC84" />
            <rect x="266" y="202" width="9" height="20" rx="4.5" fill="#3DDC84" />
            <rect x="285" y="202" width="9" height="20" rx="4.5" fill="#3DDC84" />
          </g>

          <path
            d="M338 158 L390 178 V222 C390 256 370 280 338 296 C306 280 286 256 286 222 V178Z"
            fill="#2FBF71"
            opacity="0.22"
            filter={`url(#${id('softGlow')})`}
          />
          <path
            d="M338 158 L390 178 V222 C390 256 370 280 338 296 C306 280 286 256 286 222 V178Z"
            fill={`url(#${id('shield')})`}
            stroke="#C5F3D9"
            strokeWidth="3.2"
          />
          <path
            d="M338 172 L376 186 V220 C376 246 360 266 338 278 C316 266 300 246 300 220 V186Z"
            fill={`url(#${id('shieldInner')})`}
          />
          <path
            d="M316 222 L330 236 L360 202"
            stroke="white"
            strokeWidth="7.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      </svg>
    </div>
  )
}

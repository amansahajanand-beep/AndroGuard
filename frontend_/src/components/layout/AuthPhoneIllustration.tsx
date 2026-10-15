import { useId } from 'react'

export function AuthPhoneIllustration() {
  const uid = useId().replace(/:/g, '')
  const id = (name: string) => `${uid}-${name}`

  return (
    <div className="relative mx-auto w-full max-w-[640px]" aria-hidden="true">
      <div className="pointer-events-none absolute left-1/2 top-[48%] h-[78%] w-[78%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#0E7A45]/35 blur-[90px]" />
      <svg
        width="560"
        height="390"
        viewBox="0 0 560 390"
        className="relative h-auto w-full overflow-visible"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <filter id={id('blueGlow')} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id={id('softGlow')} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="12" />
          </filter>
          <filter id={id('neonGlow')} x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <linearGradient id={id('phoneBody')} x1="220" y1="70" x2="340" y2="310">
            <stop offset="0" stopColor="#0B0F14" />
            <stop offset="0.5" stopColor="#0B0F14" />
            <stop offset="1" stopColor="#0B0F14" />
          </linearGradient>
          <linearGradient id={id('screen')} x1="240" y1="90" x2="320" y2="280">
            <stop offset="0" stopColor="#17212C" />
            <stop offset="1" stopColor="#0B0F14" />
          </linearGradient>
          <linearGradient id={id('shield')} x1="280" y1="145" x2="390" y2="280" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#2FBF71" />
            <stop offset="0.45" stopColor="#12A15B" />
            <stop offset="1" stopColor="#0E7A45" />
          </linearGradient>
          <linearGradient id={id('shieldEdge')} x1="282" y1="148" x2="385" y2="275" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#C5F3D9" />
            <stop offset="0.4" stopColor="#22D3EE" />
            <stop offset="1" stopColor="#2FBF71" />
          </linearGradient>
          <linearGradient id={id('androidGreen')} x1="260" y1="140" x2="260" y2="220">
            <stop offset="0" stopColor="#7CF5A6" />
            <stop offset="1" stopColor="#3DDC84" />
          </linearGradient>
          <linearGradient id={id('cloudFill')} x1="90" y1="160" x2="180" y2="230">
            <stop offset="0" stopColor="#223041" />
            <stop offset="1" stopColor="#17212C" />
          </linearGradient>
        </defs>

        <ellipse cx="280" cy="190" rx="160" ry="118" fill="#12A15B" opacity="0.16" filter={`url(#${id('softGlow')})`} />

        <ellipse cx="280" cy="190" rx="175" ry="112" stroke="#2FBF71" strokeOpacity="0.38" strokeWidth="1.2" />
        <ellipse cx="280" cy="190" rx="145" ry="86" stroke="#2FBF71" strokeOpacity="0.32" strokeWidth="1" />
        <ellipse
          cx="280"
          cy="190"
          rx="160"
          ry="73"
          transform="rotate(-30 280 190)"
          stroke="#2FBF71"
          strokeOpacity="0.3"
          strokeWidth="1"
        />
        <path d="M419 85 C438 94 450 109 457 126" stroke="#8FE9B4" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M105 246 C101 263 108 278 121 287" stroke="#8FE9B4" strokeWidth="1.4" strokeLinecap="round" />

        <circle cx="155" cy="95" r="2.2" fill="#8FE9B4" filter={`url(#${id('blueGlow')})`} />
        <circle cx="375" cy="110" r="2.4" fill="#E3FAEE" />
        <circle cx="420" cy="190" r="5" fill="#2FBF71" filter={`url(#${id('blueGlow')})`} />
        <circle cx="190" cy="240" r="2.2" fill="#8FE9B4" />
        <circle cx="470" cy="255" r="2" fill="#8FE9B4" />
        <circle cx="420" cy="300" r="1.8" fill="#2FBF71" />
        <circle cx="115" cy="275" r="1.8" fill="#2FBF71" />

        <path d="M91 126H98V133H91V126Z" fill="#2FBF71" />
        <path d="M451 102H457V109H451V102Z" fill="#2FBF71" />
        <path d="M467 254H471V258H467V254Z" fill="#2FBF71" />

        <g>
          <path
            d="M92 204 C92 193 101 184 113 184 C118 174 128 168 140 168 C155 168 167 177 170 190 C179 190 186 197 186 206 C186 216 178 223 168 223 H109 C99 223 92 216 92 204Z"
            fill="#223041"
            opacity="0.2"
            filter={`url(#${id('softGlow')})`}
          />
          <path
            d="M92 204 C92 193 101 184 113 184 C118 174 128 168 140 168 C155 168 167 177 170 190 C179 190 186 197 186 206 C186 216 178 223 168 223 H109 C99 223 92 216 92 204Z"
            fill={`url(#${id('cloudFill')})`}
            stroke="#2FBF71"
            strokeWidth="1.2"
          />
          <path d="M103 204H176" stroke="#2B3B4F" strokeOpacity="0.45" strokeWidth="1" />
        </g>

        <g>
          <path
            d="M382 145 C382 136 390 129 399 129 C403 120 412 115 422 115 C435 115 444 124 446 136 C454 136 460 142 460 150 C460 159 453 165 444 165 H397 C389 165 382 158 382 145Z"
            fill="none"
            stroke="#C5F3D9"
            strokeOpacity="0.85"
            strokeWidth="1.4"
          />
        </g>

        <ellipse cx="282" cy="325" rx="75" ry="12" fill="#0B0F14" opacity="0.9" />

        <g>
          <rect
            x="220"
            y="72"
            width="120"
            height="235"
            rx="22"
            fill={`url(#${id('phoneBody')})`}
            stroke="#2FBF71"
            strokeWidth="1.8"
            filter={`url(#${id('neonGlow')})`}
          />
          <rect x="223" y="75" width="114" height="229" rx="19" stroke="#8FE9B4" strokeOpacity="0.55" strokeWidth="1" />
          <rect
            x="230"
            y="91"
            width="100"
            height="191"
            rx="14"
            fill={`url(#${id('screen')})`}
            stroke="#223041"
            strokeWidth="1"
          />
          <rect x="236" y="98" width="88" height="177" rx="11" fill="#111821" />
          <rect x="262" y="78" width="36" height="5" rx="2.5" fill="#0B0F14" />
          <circle cx="245" cy="115" r="3" fill="#2FBF71" />
          <path d="M266 289H294" stroke="#8696A8" strokeWidth="3" strokeLinecap="round" />
        </g>

        <g>
          <path d="M260 140L254 131" stroke="#3DDC84" strokeWidth="2" strokeLinecap="round" />
          <path d="M294 140L300 131" stroke="#3DDC84" strokeWidth="2" strokeLinecap="round" />
          <path d="M256 160 C256 144 264 138 277 138 C290 138 298 144 298 160 Z" fill={`url(#${id('androidGreen')})`} />
          <circle cx="267" cy="150" r="2.2" fill="#06251A" />
          <circle cx="287" cy="150" r="2.2" fill="#06251A" />
          <rect x="256" y="164" width="42" height="40" rx="6" fill={`url(#${id('androidGreen')})`} />
          <rect x="246" y="168" width="8" height="28" rx="4" fill="#3DDC84" />
          <rect x="300" y="168" width="8" height="28" rx="4" fill="#3DDC84" />
          <rect x="264" y="206" width="8" height="16" rx="4" fill="#3DDC84" />
          <rect x="282" y="206" width="8" height="16" rx="4" fill="#3DDC84" />
        </g>

        <path
          d="M337 145 L391 165 V211 C391 248 369 274 337 290 C305 274 283 248 283 211 V165Z"
          fill="#2FBF71"
          opacity="0.22"
          filter={`url(#${id('softGlow')})`}
        />
        <path
          d="M337 145 L391 165 V211 C391 248 369 274 337 290 C305 274 283 248 283 211 V165Z"
          fill={`url(#${id('shield')})`}
          stroke={`url(#${id('shieldEdge')})`}
          strokeWidth="3.5"
        />
        <path
          d="M337 157 L378 172 V210 C378 237 362 258 337 272 C312 258 296 237 296 210 V172Z"
          fill="#0E7A45"
          opacity="0.35"
        />
        <path
          d="M313 211 L329 227 L361 190"
          stroke="white"
          strokeWidth="8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M285 166 L337 146" stroke="#E3FAEE" strokeOpacity="0.75" strokeWidth="1.6" />
        <ellipse
          cx="337"
          cy="215"
          rx="78"
          ry="48"
          transform="rotate(-18 337 215)"
          stroke="#8FE9B4"
          strokeOpacity="0.4"
          strokeWidth="1.2"
        />
      </svg>
    </div>
  )
}

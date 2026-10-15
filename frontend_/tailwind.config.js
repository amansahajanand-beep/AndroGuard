/** @type {import('tailwindcss').Config} */
// Colours that change with the theme are CSS variables (RGB channels) defined in src/index.css.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: v('primary'),
          hover: v('primary-hover'),
          soft: v('primary-soft'),
          ink: '#04210F',
        },
        // Bright Android green for filled surfaces (buttons, active states); pair with text-primary-ink.
        brand: {
          DEFAULT: '#3DDC84',
          hover: '#5FE79B',
        },
        accent: '#22D3EE',
        sidebar: {
          DEFAULT: '#0D131A',
          hover: '#141D27',
          active: '#3DDC84',
        },
        canvas: v('canvas'),
        ink: v('ink'),
        muted: v('muted'),
        line: v('line'),
        subtle: v('subtle'),
        onfill: v('onfill'),
        success: v('success'),
        warning: v('warning'),
        danger: v('danger'),
        info: v('info'),
        critical: v('danger'),
        high: v('high'),
        medium: v('warning'),
        low: v('info'),
        night: {
          DEFAULT: '#0B0F14',
          card: '#111821',
          raised: '#17212C',
          border: '#223041',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: [
          '"JetBrains Mono"',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          '"Liberation Mono"',
          'monospace',
        ],
      },
      borderRadius: {
        lg: '7px',
        xl: '10px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 26, 23, 0.04), 0 6px 18px rgba(15, 26, 23, 0.04)',
        soft: '0 10px 30px rgba(0, 0, 0, 0.18)',
        glow: '0 0 0 1px rgba(61, 220, 132, 0.35), 0 0 18px rgba(61, 220, 132, 0.18)',
        'glow-sm': '0 0 0 1px rgba(61, 220, 132, 0.55), 0 0 10px rgba(61, 220, 132, 0.25)',
      },
      maxWidth: {
        app: '1280px',
      },
    },
  },
  plugins: [],
}

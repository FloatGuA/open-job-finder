import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '-apple-system',
          'SF Pro Display',
          'SF Pro Text',
          'Helvetica Neue',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
        // Telemetry data font (numbers / tool names / timestamps / codes)
        mono: ['IBM Plex Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        brand: {
          DEFAULT: '#0071e3',
          hover: '#0077ed',
          bright: '#2997ff',
          dim: 'rgba(0,113,227,0.15)',
        },
        bg: {
          page: '#000000',
          card: '#1c1c1e',
          card2: '#2c2c2e',
          input: '#1c1c1e',
          hover: '#3a3a3c',
          active: '#48484a',
        },
        text: {
          1: '#ffffff',
          2: '#adadb8',
          3: '#84848c', // tertiary — weakest READABLE text (>=4.5:1 on bg-card); see docs/frontend.md
        },
        // Apple dark-mode system signal colors — status/telemetry only
        signal: {
          blue: '#0a84ff', // W1
          bright: '#2997ff',
          green: '#30d158', // success
          amber: '#ff9f0a', // queued / warn
          purple: '#bf5af2', // W2
          red: '#ff453a', // error
          teal: '#40c8e0',
        },
        // DECORATION ONLY (hairlines/dividers/disabled) — NEVER for text
        deco: '#48484a',
        border: {
          subtle: 'rgba(255,255,255,0.08)',
          default: 'rgba(255,255,255,0.12)',
        },
      },
      boxShadow: {
        card: 'rgba(0,0,0,0.22) 3px 5px 30px 0px',
        'card-sm': 'rgba(0,0,0,0.18) 0px 2px 12px 0px',
        dialog: 'rgba(0,0,0,0.48) 0px 8px 40px 0px',
      },
      letterSpacing: {
        'apple-tight': '-0.374px',
        'apple-caption': '-0.224px',
        'apple-micro': '-0.12px',
      },
    },
  },
  plugins: [],
}

export default config

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      boxShadow: {
        'violet-glow-lg': '0 0 24px 4px rgba(139, 92, 246, 0.5)',
      },
      animation: {
        'ring-pulse-1': 'ping 1.2s cubic-bezier(0,0,0.2,1) infinite',
        'ring-pulse-2': 'ping 1.8s cubic-bezier(0,0,0.2,1) infinite',
      },
      colors: {
        brand: {
          50:  '#eef2ff',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
        display: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
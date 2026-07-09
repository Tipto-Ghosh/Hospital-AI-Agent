/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        'hospital-blue': '#1A56DB',
        'hospital-navy': '#1E3A5F',
        'hospital-green': '#057A55',
        'hospital-red': '#C81E1E',
        'hospital-amber': '#C27803',
        'surface-white': '#FFFFFF',
        'surface-gray': '#F9FAFB',
        'border-gray': '#E5E7EB',
        'text-primary': '#111827',
        'text-secondary': '#6B7280',
      },
      keyframes: {
        'typing-dot': {
          '0%, 100%': { transform: 'scale(0.7)', opacity: '0.4' },
          '50%': { transform: 'scale(1)', opacity: '1' },
        },
        'cursor-blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'pulse-status': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
      },
      animation: {
        'typing-dot-1': 'typing-dot 1.2s ease-in-out 0s infinite',
        'typing-dot-2': 'typing-dot 1.2s ease-in-out 0.2s infinite',
        'typing-dot-3': 'typing-dot 1.2s ease-in-out 0.4s infinite',
        'cursor-blink': 'cursor-blink 1s step-end infinite',
        'pulse-status': 'pulse-status 1.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#060C18',
        surface: '#0D1526',
        border:  '#1A2740',
        teal:    { DEFAULT: '#167D6F', light: '#3BD6AC' },
        green:   '#22c55e',
        red:     '#ef4444',
        muted:   '#6B7FA3',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#041017',
        panel: '#0b1720',
        panelAlt: '#10222d',
        line: 'rgba(148, 163, 184, 0.16)',
        accent: '#39d0c2',
        glow: '#91f5ed',
        alarm: '#ff7a59',
        warning: '#f8c857',
        success: '#53d49c',
      },
      boxShadow: {
        halo: '0 18px 60px rgba(4, 16, 23, 0.48)',
        panel: '0 24px 80px rgba(3, 10, 14, 0.35)',
      },
      fontFamily: {
        sans: ['"Manrope Variable"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      backgroundImage: {
        mesh:
          'radial-gradient(circle at top left, rgba(57, 208, 194, 0.12), transparent 32%), radial-gradient(circle at top right, rgba(248, 200, 87, 0.12), transparent 24%), linear-gradient(180deg, rgba(4,16,23,1) 0%, rgba(7,20,27,1) 42%, rgba(4,16,23,1) 100%)',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '0.45' },
          '50%': { opacity: '1' },
        },
        scan: {
          '0%': { transform: 'translateY(-120%)' },
          '100%': { transform: 'translateY(420%)' },
        },
        flash: {
          '0%, 100%': { opacity: '0.18' },
          '50%': { opacity: '0.42' },
        },
      },
      animation: {
        float: 'float 5s ease-in-out infinite',
        'pulse-soft': 'pulseSoft 2.8s ease-in-out infinite',
        scan: 'scan 6s linear infinite',
        flash: 'flash 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}

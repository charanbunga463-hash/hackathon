import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        elevated: "rgb(var(--elevated) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        ok: "rgb(var(--ok) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        info: "rgb(var(--info) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
        /* --- marketing scenes ------------------------------------------- */
        sheen: {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        "grid-pan": {
          from: { backgroundPosition: "0 0" },
          to: { backgroundPosition: "0 44px" },
        },
        drift: {
          "0%, 100%": { transform: "translate3d(0,0,0) scale(1)" },
          "33%": { transform: "translate3d(3%, -4%, 0) scale(1.08)" },
          "66%": { transform: "translate3d(-3%, 3%, 0) scale(0.95)" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-10px)" },
        },
        scan: {
          from: { transform: "translateY(-100%)" },
          to: { transform: "translateY(900%)" },
        },
        "trace-dash": {
          to: { strokeDashoffset: "-220" },
        },
      },
      animation: {
        "fade-up": "fade-up 180ms ease-out",
        "pulse-soft": "pulse-soft 1.6s ease-in-out infinite",
        sheen: "sheen 6s ease-in-out infinite",
        "grid-pan": "grid-pan 18s linear infinite",
        drift: "drift 22s ease-in-out infinite",
        float: "float 7s ease-in-out infinite",
        scan: "scan 4.5s linear infinite",
        "trace-dash": "trace-dash 3s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;

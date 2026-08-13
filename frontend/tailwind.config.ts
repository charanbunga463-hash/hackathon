import type { Config } from "tailwindcss";

/**
 * "Daylight" — the one and only theme.
 *
 * There is no dark mode in this product. `darkMode` is pinned to a class that
 * is never applied, so a stray `dark:` utility is inert rather than being a
 * second design nobody maintains. Every colour resolves from a CSS custom
 * property declared once in globals.css.
 *
 * Each semantic colour comes in four weights, and they are not interchangeable:
 *
 *   DEFAULT — the saturated hue. Fills, bars, dots, icons on light backgrounds.
 *   soft    — a pale wash for a tinted surface behind text.
 *   line    — the border that pairs with `soft`.
 *   ink     — the dark, readable version. This is the one text uses on `soft`.
 *
 * Amber at 500 is unreadable as body text on white; amber "ink" is not. Keeping
 * them as separate tokens means contrast is a naming decision, not a judgement
 * call made again on every component.
 */
const config: Config = {
  darkMode: ["class", '[data-never="dark"]'],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        /* --- ground ------------------------------------------------------ */
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        elevated: "rgb(var(--elevated) / <alpha-value>)",
        sunken: "rgb(var(--sunken) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        "line-strong": "rgb(var(--line-strong) / <alpha-value>)",

        /* --- text -------------------------------------------------------- */
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",

        /* --- brand ------------------------------------------------------- */
        brand: {
          DEFAULT: "rgb(var(--brand) / <alpha-value>)",
          strong: "rgb(var(--brand-strong) / <alpha-value>)",
          soft: "rgb(var(--brand-soft) / <alpha-value>)",
          line: "rgb(var(--brand-line) / <alpha-value>)",
          ink: "rgb(var(--brand-ink) / <alpha-value>)",
        },
        /* Kept so any straggling `accent` utility still resolves to the brand. */
        accent: "rgb(var(--brand) / <alpha-value>)",

        /* --- status ------------------------------------------------------ */
        ok: {
          DEFAULT: "rgb(var(--ok) / <alpha-value>)",
          soft: "rgb(var(--ok-soft) / <alpha-value>)",
          line: "rgb(var(--ok-line) / <alpha-value>)",
          ink: "rgb(var(--ok-ink) / <alpha-value>)",
        },
        warn: {
          DEFAULT: "rgb(var(--warn) / <alpha-value>)",
          soft: "rgb(var(--warn-soft) / <alpha-value>)",
          line: "rgb(var(--warn-line) / <alpha-value>)",
          ink: "rgb(var(--warn-ink) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--danger) / <alpha-value>)",
          soft: "rgb(var(--danger-soft) / <alpha-value>)",
          line: "rgb(var(--danger-line) / <alpha-value>)",
          ink: "rgb(var(--danger-ink) / <alpha-value>)",
        },
        info: {
          DEFAULT: "rgb(var(--info) / <alpha-value>)",
          soft: "rgb(var(--info-soft) / <alpha-value>)",
          line: "rgb(var(--info-line) / <alpha-value>)",
          ink: "rgb(var(--info-ink) / <alpha-value>)",
        },
        grape: {
          DEFAULT: "rgb(var(--grape) / <alpha-value>)",
          soft: "rgb(var(--grape-soft) / <alpha-value>)",
          line: "rgb(var(--grape-line) / <alpha-value>)",
          ink: "rgb(var(--grape-ink) / <alpha-value>)",
        },
      },

      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },

      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },

      borderRadius: {
        card: "0.875rem",
      },

      /* Controls sit on a 38px rhythm — taller than Tailwind's 36px `h-9`,
         shorter than the 40px `h-10` that makes a toolbar feel chunky. */
      spacing: {
        "9.5": "2.375rem",
        "4.5": "1.125rem",
      },

      /**
       * Light-theme depth is made of many small, tinted shadows rather than one
       * black one. Pure black shadows turn a bright page grey; a blue-tinted
       * shadow reads as daylight falling on paper.
       */
      boxShadow: {
        subtle: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.04)",
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 8px 24px -12px rgb(30 41 59 / 0.16)",
        raised: "0 2px 4px -1px rgb(15 23 42 / 0.05), 0 16px 36px -16px rgb(30 41 59 / 0.24)",
        pop: "0 4px 8px -2px rgb(15 23 42 / 0.06), 0 28px 60px -24px rgb(30 41 59 / 0.34)",
        /* Named `glow`, not `brand`: a `shadow-brand` utility would collide
           with the `brand` colour's own shadow-colour utility. */
        glow: "0 8px 20px -8px rgb(var(--brand) / 0.45)",
        "glow-lg": "0 14px 34px -10px rgb(var(--brand) / 0.55)",
      },

      backgroundImage: {
        "brand-gradient":
          "linear-gradient(135deg, rgb(var(--brand-strong)), rgb(var(--brand)) 45%, rgb(var(--grape)) 100%)",
        "sky-gradient":
          "linear-gradient(135deg, rgb(var(--info)), rgb(var(--brand)) 100%)",
        "mint-gradient":
          "linear-gradient(135deg, rgb(var(--ok)), rgb(var(--info)) 100%)",
      },

      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.97)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        drift: {
          "0%, 100%": { transform: "translate3d(0,0,0) scale(1)" },
          "33%": { transform: "translate3d(3%, -4%, 0) scale(1.07)" },
          "66%": { transform: "translate3d(-3%, 3%, 0) scale(0.96)" },
        },
        sheen: {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        shimmer: {
          from: { transform: "translateX(-100%)" },
          to: { transform: "translateX(100%)" },
        },
        "sweep-down": {
          from: { transform: "translateY(-110%)" },
          to: { transform: "translateY(900%)" },
        },
        "dash-flow": {
          to: { strokeDashoffset: "-240" },
        },
      },

      animation: {
        "fade-up": "fade-up 260ms cubic-bezier(0.16, 1, 0.3, 1)",
        "fade-in": "fade-in 220ms ease-out",
        "scale-in": "scale-in 180ms cubic-bezier(0.16, 1, 0.3, 1)",
        "pulse-soft": "pulse-soft 1.8s ease-in-out infinite",
        float: "float 6s ease-in-out infinite",
        drift: "drift 24s ease-in-out infinite",
        sheen: "sheen 7s ease-in-out infinite",
        shimmer: "shimmer 1.8s ease-in-out infinite",
        "sweep-down": "sweep-down 4.5s linear infinite",
        "dash-flow": "dash-flow 3.4s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;

import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        card: "hsl(var(--card) / <alpha-value>)",
        muted: "hsl(var(--muted) / <alpha-value>)",
        "muted-foreground": "hsl(var(--muted-foreground) / <alpha-value>)",
        border: "hsl(var(--border) / <alpha-value>)",
        primary: "hsl(var(--primary) / <alpha-value>)",
        accent: "hsl(var(--accent) / <alpha-value>)",
        "on-brand": "hsl(var(--on-brand) / <alpha-value>)",
        good: "hsl(var(--good) / <alpha-value>)",
        warn: "hsl(var(--warn) / <alpha-value>)",
        bad: "hsl(var(--bad) / <alpha-value>)",
      },
      borderRadius: { xl: "0.9rem", "2xl": "1.2rem" },
      boxShadow: { glow: "0 8px 22px -10px hsl(146 60% 30% / 0.6)" },
      keyframes: { fadeUp: { "0%": { opacity: "0", transform: "translateY(6px)" }, "100%": { opacity: "1", transform: "none" } } },
      animation: { "fade-up": "fadeUp .35s ease-out both" },
    },
  },
  plugins: [],
};

export default config;

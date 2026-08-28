import type { Config } from "tailwindcss";

/**
 * Colour is load-bearing in this console, so the palette is constrained on
 * purpose:
 *
 *  - navy/slate carries all neutral structure;
 *  - amber means "uncertainty" and nothing else (intervals, abstentions,
 *    stale data, post-cutoff evidence);
 *  - red is reserved for the ALERT status and hard failures. It is never
 *    used for emphasis, because a console where everything important is red
 *    teaches analysts to ignore red;
 *  - probability is encoded with `cividis`, a perceptually-uniform ramp that
 *    stays monotonic under deuteranopia, protanopia and tritanopia. Every
 *    place it is used also states the number, because colour is never the
 *    only channel.
 */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#f2f5f9", 100: "#e3e9f2", 200: "#c7d3e5", 300: "#9db1cf",
          400: "#6c88b4", 500: "#4a679a", 600: "#385080", 700: "#2d4068",
          800: "#1e2c49", 900: "#141e33", 950: "#0b1220",
        },
        uncertainty: {
          50: "#fff8eb", 100: "#fdeec7", 200: "#fbd88a", 300: "#f8bd4d",
          400: "#f6a524", 500: "#e0830c", 600: "#c26207", 700: "#a1450a",
          800: "#83360f", 900: "#6c2d10",
        },
        alert: {
          100: "#fee2e2", 300: "#fca5a5", 500: "#dc2626", 600: "#b91c1c",
          700: "#991b1b", 900: "#5f1414",
        },
        cividis: {
          0: "#00224e", 1: "#123570", 2: "#3b496c", 3: "#575d6d", 4: "#707173",
          5: "#8a8678", 6: "#a59c74", 7: "#c3b369", 8: "#e1cc55", 9: "#fee838",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: { "2xs": ["0.6875rem", { lineHeight: "1rem" }] },
    },
  },
  plugins: [],
} satisfies Config;

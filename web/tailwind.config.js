/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#06080B",
          900: "#0A0D12",
          850: "#0E1218",
          800: "#12171F",
          750: "#171D27",
          700: "#1F2733",
          600: "#2B3544",
          500: "#465265",
          400: "#6A7688",
          300: "#96A1B3",
          200: "#C3CBD7",
          100: "#E7EBF1",
        },
        tg: {
          300: "#FBB27A",
          400: "#F89A50",
          500: "#F58025",
          600: "#D9691A",
          700: "#9C4A12",
        },
        fraud: { DEFAULT: "#EF5A50", soft: "#3A1716", line: "#7A2A25" },
        legit: { DEFAULT: "#3CC585", soft: "#0F2A1E", line: "#1E6644" },
        unsure: { DEFAULT: "#EDB341", soft: "#33260C", line: "#7A5A18" },
        agent: {
          lead: "#F58025",
          transaction: "#5EA8FF",
          identity: "#A48BFA",
          network: "#2FD3BE",
          precedent: "#F277B5",
          compliance: "#C3CCD8",
        },
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono Variable"', '"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 12px 32px -18px rgba(0,0,0,0.8)",
        glow: "0 0 0 1px rgba(245,128,37,0.35), 0 0 24px -4px rgba(245,128,37,0.45)",
      },
      keyframes: {
        pulsering: {
          "0%": { transform: "scale(0.9)", opacity: "0.9" },
          "100%": { transform: "scale(2.2)", opacity: "0" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        pulsering: "pulsering 1.6s cubic-bezier(0.2,0.6,0.3,1) infinite",
        shimmer: "shimmer 2.4s linear infinite",
      },
    },
  },
  plugins: [],
};

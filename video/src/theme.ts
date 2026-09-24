// The Command Center's own design tokens (web/tailwind.config.js), so the film and the product look like one thing.
export const C = {
  bg: "#06080B",
  ink950: "#06080B",
  ink900: "#0A0D12",
  ink850: "#0E1218",
  ink800: "#12171F",
  ink750: "#171D27",
  ink700: "#1F2733",
  ink600: "#2B3544",
  ink500: "#465265",
  ink400: "#6A7688",
  ink300: "#96A1B3",
  ink200: "#C3CBD7",
  ink100: "#E7EBF1",
  tg: "#F58025",
  tg300: "#FBB27A",
  tg400: "#F89A50",
  tg600: "#D9691A",
  fraud: "#EF5A50",
  fraudSoft: "#3A1716",
  legit: "#3CC585",
  legitSoft: "#0F2A1E",
  unsure: "#EDB341",
  agent: {
    lead: "#F58025",
    transaction: "#5EA8FF",
    identity: "#A48BFA",
    network: "#2FD3BE",
    precedent: "#F277B5",
    compliance: "#C3CCD8",
  },
} as const;

export const FONT = { sans: "Inter", mono: "JetBrains Mono" } as const;
export const FPS = 30;
export const W = 1920;
export const H = 1080;

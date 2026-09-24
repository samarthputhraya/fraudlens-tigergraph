import React from "react";
import { C, FONT } from "../theme";

// Typographic building blocks for the motion-graphics scenes.

/** Text that rises into place from behind an invisible baseline mask. `p` 0..1. */
export const MaskRise: React.FC<{ p: number; children: React.ReactNode; style?: React.CSSProperties; pad?: string }> = ({
  p,
  children,
  style,
  pad = "0.14em",
}) => (
  <span style={{ display: "inline-block", overflow: "hidden", padding: `${pad} 0.06em`, margin: `-${pad} -0.06em`, verticalAlign: "top", ...style }}>
    <span
      style={{
        display: "inline-block",
        translate: `0px ${((1 - p) * 108).toFixed(2)}%`,
        opacity: Math.min(1, p * 1.6),
      }}
    >
      {children}
    </span>
  </span>
);

/** Small mono caps label, the product's "kicker" style. */
export const Kicker: React.FC<{ children: React.ReactNode; color?: string; size?: number; track?: number; style?: React.CSSProperties }> = ({
  children,
  color = C.ink300,
  size = 16,
  track = 0.2,
  style,
}) => (
  <div
    style={{
      fontFamily: FONT.mono,
      fontSize: size,
      fontWeight: 500,
      letterSpacing: `${track}em`,
      textTransform: "uppercase",
      color,
      whiteSpace: "nowrap",
      ...style,
    }}
  >
    {children}
  </div>
);

export const mono = (size: number, color: string = C.ink300, weight = 400): React.CSSProperties => ({
  fontFamily: FONT.mono,
  fontSize: size,
  fontWeight: weight,
  color,
  whiteSpace: "nowrap",
  fontVariantLigatures: "none",
});

export const sans = (size: number, weight = 500, color: string = C.ink100, track = -0.01): React.CSSProperties => ({
  fontFamily: FONT.sans,
  fontSize: size,
  fontWeight: weight,
  color,
  letterSpacing: `${track}em`,
  whiteSpace: "nowrap",
});

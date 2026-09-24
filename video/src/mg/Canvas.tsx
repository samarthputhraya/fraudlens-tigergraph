import React from "react";
import { AbsoluteFill } from "remotion";

// The Command Center's "canvas-grid" look: near-black, a faint 22px dot grid, a soft orange glow in the middle,
// plus a gentle vignette and an almost invisible grain that keeps the dark gradients from banding once encoded.
// The grid is static on purpose, so consecutive motion-graphics scenes crossfade into one continuous canvas.

const GRAIN_SVG =
  "<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'>" +
  "<filter id='n' x='0' y='0'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/>" +
  "<feColorMatrix type='saturate' values='0'/></filter><rect width='240' height='240' filter='url(#n)'/></svg>";
const GRAIN = `url("data:image/svg+xml;utf8,${encodeURIComponent(GRAIN_SVG)}")`;

export const Canvas: React.FC<{
  children?: React.ReactNode;
  /** Multiplier on the orange centre glow (1 = the UI's 7%). */
  glow?: number;
  /** Where the glow sits, in % of the frame. */
  glowAt?: [number, number];
}> = ({ children, glow = 1, glowAt = [50, 50] }) => (
  <AbsoluteFill style={{ backgroundColor: "#07090D", overflow: "hidden" }}>
    <AbsoluteFill
      style={{
        backgroundImage: "radial-gradient(circle at 1px 1px, rgba(150, 161, 179, 0.12) 1px, transparent 0)",
        backgroundSize: "22px 22px",
        // put a dot exactly on the frame centre (960, 540)
        backgroundPosition: "13px 11px",
      }}
    />
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse 60% 55% at ${glowAt[0]}% ${glowAt[1]}%, rgba(245, 128, 37, ${(0.07 * glow).toFixed(4)}), transparent 70%)`,
      }}
    />
    <AbsoluteFill style={{ background: "radial-gradient(ellipse 80% 75% at 50% 50%, transparent 58%, rgba(2, 3, 5, 0.55) 100%)" }} />
    {children}
    <AbsoluteFill style={{ backgroundImage: GRAIN, backgroundSize: "240px 240px", opacity: 0.028, pointerEvents: "none" }} />
  </AbsoluteFill>
);

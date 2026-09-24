import { evolvePath } from "@remotion/paths";
import React from "react";

// The FraudLens mark (same geometry as LensMark.tsx, viewBox 32x32) with every stroke and dot independently animatable:
// the ring draws as one pen stroke that starts where the handle meets it, then the handle extends, the graph inside
// draws its edges and its three nodes pop.

export const MARK = {
  ringC: { x: 13.5, y: 13.5 },
  ringR: 9.5,
  ringW: 2.4,
  handle: { x1: 20.6, y1: 20.6, x2: 28, y2: 28, w: 3.2 },
  dotLeft: { x: 9.5, y: 16.5, r: 1.9 },
  dotRight: { x: 17.5, y: 15.5, r: 1.9 },
  dotTop: { x: 13.5, y: 9.5, r: 2.3 },
  orange: "#F58025",
  ink: "#E7EBF1",
} as const;

// start at the handle junction (45deg), sweep anticlockwise on screen, close back on itself
const RING_D = "M 20.2175 20.2175 A 9.5 9.5 0 0 0 6.7825 6.7825 A 9.5 9.5 0 0 0 20.2175 20.2175";
const HANDLE_D = "M 20.6 20.6 L 28 28";
const TRI_D = "M 13.5 9.5 L 9.5 16.5 L 17.5 15.5 Z";

/** Convert a point in mark units to pixels for a mark of `size` px whose box starts at (left, top). */
export const markToPx = (size: number, left: number, top: number, p: { x: number; y: number }) => ({
  x: left + (p.x * size) / 32,
  y: top + (p.y * size) / 32,
});

export const LensMarkAnimated: React.FC<{
  size: number;
  ring?: number;
  handle?: number;
  tri?: number;
  /** scale of the [left, right, top] dots, 0..1+ */
  dots?: [number, number, number];
  /** 0..1 soft orange bloom behind the mark */
  glow?: number;
  style?: React.CSSProperties;
}> = ({ size, ring = 1, handle = 1, tri = 1, dots = [1, 1, 1], glow = 0, style }) => {
  const r = evolvePath(Math.max(0.0001, Math.min(1, ring)), RING_D);
  const h = evolvePath(Math.max(0.0001, Math.min(1, handle)), HANDLE_D);
  const t = evolvePath(Math.max(0.0001, Math.min(1, tri)), TRI_D);
  const [dl, dr, dt] = dots;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      style={{
        display: "block",
        overflow: "visible",
        filter: glow > 0 ? `drop-shadow(0 0 ${(size * 0.09).toFixed(1)}px rgba(245, 128, 37, ${(0.38 * glow).toFixed(3)}))` : undefined,
        ...style,
      }}
    >
      {ring > 0 ? (
        <path d={RING_D} fill="none" stroke={MARK.orange} strokeWidth={MARK.ringW} strokeLinecap="butt" strokeDasharray={r.strokeDasharray} strokeDashoffset={r.strokeDashoffset} />
      ) : null}
      {handle > 0 ? (
        <path d={HANDLE_D} fill="none" stroke={MARK.orange} strokeWidth={MARK.handle.w} strokeLinecap="round" strokeDasharray={h.strokeDasharray} strokeDashoffset={h.strokeDashoffset} />
      ) : null}
      {tri > 0 ? (
        <path d={TRI_D} fill="none" stroke={MARK.ink} strokeOpacity={0.55} strokeWidth={1.2} strokeLinejoin="round" strokeDasharray={t.strokeDasharray} strokeDashoffset={t.strokeDashoffset} />
      ) : null}
      {dl > 0 ? <circle cx={MARK.dotLeft.x} cy={MARK.dotLeft.y} r={MARK.dotLeft.r * dl} fill={MARK.ink} /> : null}
      {dr > 0 ? <circle cx={MARK.dotRight.x} cy={MARK.dotRight.y} r={MARK.dotRight.r * dr} fill={MARK.ink} /> : null}
      {dt > 0 ? <circle cx={MARK.dotTop.x} cy={MARK.dotTop.y} r={MARK.dotTop.r * dt} fill={MARK.orange} /> : null}
    </svg>
  );
};

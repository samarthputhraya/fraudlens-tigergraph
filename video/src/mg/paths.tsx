import { evolvePath, getLength, getPointAtLength } from "@remotion/paths";
import React, { useMemo } from "react";
import { rgba } from "./anim";

// SVG drawing primitives: strokes that draw on, and light packets that travel along a path.

const lengthCache = new Map<string, number>();
export const pathLength = (d: string) => {
  let v = lengthCache.get(d);
  if (v === undefined) {
    v = getLength(d);
    if (lengthCache.size > 4000) lengthCache.clear();
    lengthCache.set(d, v);
  }
  return v;
};

export const pointAt = (d: string, t: number) => {
  const len = pathLength(d);
  return getPointAtLength(d, Math.max(0, Math.min(len, len * t))) ?? { x: 0, y: 0 };
};

/** Cubic "S" connector between two points with horizontal tangents at both ends. */
export const hCurve = (x1: number, y1: number, x2: number, y2: number, bend = 0.5) => {
  const dx = (x2 - x1) * bend;
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
};

/** Gentle arc between two points, bowed sideways by `bow` px. */
export const arc = (x1: number, y1: number, x2: number, y2: number, bow = 0) => {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const cx = mx + (-dy / len) * bow;
  const cy = my + (dx / len) * bow;
  return `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
};

/** A stroke that draws itself on as `progress` goes 0 -> 1, optionally with a glowing head riding the tip. */
export const DrawPath: React.FC<{
  d: string;
  progress: number;
  stroke: string;
  width?: number;
  opacity?: number;
  head?: string | null;
  headR?: number;
  cap?: "round" | "butt";
  dash?: string;
}> = ({ d, progress, stroke, width = 1.5, opacity = 1, head = null, headR = 3, cap = "round", dash }) => {
  const p = Math.max(0, Math.min(1, progress));
  const evolved = useMemo(() => evolvePath(p, d), [p, d]);
  if (p <= 0 || opacity <= 0) return null;
  const tip = head && p < 1 ? pointAt(d, p) : null;
  const headFade = head ? Math.min(1, p * 6) * Math.min(1, (1 - p) * 8) : 0;
  return (
    <g opacity={opacity}>
      {dash ? (
        // dashed strokes cannot use the dash trick for drawing; reveal them with a mask instead
        <>
          <defs>
            <mask id={`m-${hash(d)}`} maskUnits="userSpaceOnUse">
              <path d={d} fill="none" stroke="#fff" strokeWidth={width + 6} strokeDasharray={evolved.strokeDasharray} strokeDashoffset={evolved.strokeDashoffset} strokeLinecap="butt" />
            </mask>
          </defs>
          <path d={d} fill="none" stroke={stroke} strokeWidth={width} strokeDasharray={dash} strokeLinecap={cap} mask={`url(#m-${hash(d)})`} />
        </>
      ) : (
        <path d={d} fill="none" stroke={stroke} strokeWidth={width} strokeLinecap={cap} strokeDasharray={evolved.strokeDasharray} strokeDashoffset={evolved.strokeDashoffset} />
      )}
      {tip && head ? (
        <>
          <circle cx={tip.x} cy={tip.y} r={headR * 3.2} fill={head} opacity={0.18 * headFade} />
          <circle cx={tip.x} cy={tip.y} r={headR} fill={head} opacity={headFade} />
        </>
      ) : null}
    </g>
  );
};

/** A packet of light at position `t` (0..1) along `d`, with a short fading tail behind it. */
export const Packet: React.FC<{ d: string; t: number; color: string; r?: number; tail?: number; opacity?: number }> = ({
  d,
  t,
  color,
  r = 3,
  tail = 46,
  opacity = 1,
}) => {
  if (t <= 0 || t >= 1 || opacity <= 0) return null;
  const len = pathLength(d);
  const head = len * t;
  const fade = Math.min(1, t * 8, (1 - t) * 8) * opacity;
  const p = pointAt(d, t);
  const seg = (l: number, a: number, w: number) => {
    const start = Math.max(0, head - l);
    return (
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={w}
        strokeLinecap="round"
        strokeDasharray={`${Math.max(0.01, head - start)} ${len + 10}`}
        strokeDashoffset={-start}
        opacity={a * fade}
      />
    );
  };
  return (
    <g>
      {seg(tail, 0.14, r * 1.1)}
      {seg(tail * 0.55, 0.22, r * 1.2)}
      {seg(tail * 0.25, 0.35, r * 1.3)}
      <circle cx={p.x} cy={p.y} r={r * 3.4} fill={rgbaOr(color, 0.16 * fade)} />
      <circle cx={p.x} cy={p.y} r={r} fill={color} opacity={fade} />
    </g>
  );
};

const rgbaOr = (c: string, a: number) => (c.startsWith("#") ? rgba(c, a) : c);

const hash = (s: string) => {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
};

/**
 * Periodic packet position: returns t in 0..1 while a packet is on the path, or -1 between packets.
 * A packet leaves every `period` frames starting at `start` and takes `travel` frames.
 */
export const cycle = (frame: number, start: number, period: number, travel: number, offset = 0) => {
  const f = frame - start - offset;
  if (f < 0) return -1;
  const m = f % period;
  return m < travel ? m / travel : -1;
};

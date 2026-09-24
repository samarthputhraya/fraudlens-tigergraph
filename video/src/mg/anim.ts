import type { CSSProperties } from "react";
import { Easing, interpolate, interpolateColors } from "remotion";

// Motion vocabulary shared by the motion-graphics scenes: one ease family, no bounce.

/** Expo-like ease-out: fast start, long soft landing. The default for every entrance. */
export const EASE = Easing.bezier(0.22, 1, 0.36, 1);
/** Symmetric ease for moves between two resting positions. */
export const EASE_IO = Easing.bezier(0.65, 0, 0.35, 1);
/** Ease-in for exits. */
export const EASE_IN = Easing.bezier(0.55, 0, 0.8, 0.35);

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 0 -> 1 progress of a tween that starts at `start` and lasts `dur` frames (clamped). */
export const tween = (frame: number, start: number, dur: number, easing: (t: number) => number = EASE): number =>
  interpolate(frame, [start, start + Math.max(1, dur)], [0, 1], { ...CLAMP, easing });

/** Rises to 1 over `inDur`, holds, then falls back to 0 over `outDur` ending at `end`. */
export const window01 = (frame: number, start: number, inDur: number, end: number, outDur: number): number =>
  Math.min(tween(frame, start, inDur), 1 - tween(frame, end - outDur, outDur, EASE_IN));

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

export const mix = (a: string, b: string, t: number) => interpolateColors(clamp01(t), [0, 1], [a, b]);

/** "#RRGGBB" + alpha -> rgba(). */
export const rgba = (hex: string, a: number) => {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${Math.max(0, Math.min(1, a))})`;
};

/** Entrance style: fade + small rise (+ optional blur), for `p` in 0..1. */
export const rise = (p: number, dy = 16, blur = 0): CSSProperties => ({
  opacity: p,
  translate: `0px ${((1 - p) * dy).toFixed(2)}px`,
  filter: blur > 0 && p < 1 ? `blur(${((1 - p) * blur).toFixed(2)}px)` : undefined,
});

/** Slow, continuous breathing value in [0, 1] (deterministic, frame-driven). */
export const breathe = (frame: number, period = 90, phase = 0) => 0.5 - 0.5 * Math.cos(((frame + phase) / period) * Math.PI * 2);

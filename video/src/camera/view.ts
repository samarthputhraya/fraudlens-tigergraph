import { Easing, interpolate } from "remotion";
import type { Box, Shot } from "./types";

/** The visible part of the capture: top-left corner and width in capture pixels (height follows from 16:9). */
export type View = { x: number; y: number; w: number };

export const ASPECT = 16 / 9;
const ease = Easing.bezier(0.45, 0, 0.2, 1); // a camera operator's ease: quick to leave, slow to settle

/** Frame a box: pad it, grow it to 16:9, respect the zoom cap, keep it inside the capture. */
export function viewFor(target: Box | "full", capW: number, capH: number, pad = 1.22, maxZoom = 2.4, dy = 0): View {
  if (target === "full") return { x: 0, y: 0, w: capW };
  let w = target.w * pad;
  let h = target.h * pad;
  if (w / h > ASPECT) h = w / ASPECT;
  else w = h * ASPECT;
  w = Math.min(capW, Math.max(capW / maxZoom, w));
  h = w / ASPECT;
  const cx = target.x + target.w / 2;
  const cy = target.y + target.h / 2 + dy;
  return {
    x: Math.min(capW - w, Math.max(0, cx - w / 2)),
    y: Math.min(capH - h, Math.max(0, cy - h / 2)),
    w,
  };
}

/**
 * Where the camera is at `frame`: the previous shot's framing, moving to the current shot's framing over `dur`
 * frames. Zoom is interpolated in log space and the centre linearly, which reads as one continuous camera move
 * (a straight lerp of the corners makes zoom-outs look like they accelerate). A slow drift keeps holds alive.
 */
export function cameraAt(frame: number, shots: Shot[], capW: number, capH: number): { view: View; shot: Shot; progress: number } {
  const sorted = [...shots].sort((a, b) => a.frame - b.frame);
  let i = 0;
  while (i + 1 < sorted.length && sorted[i + 1].frame <= frame) i++;
  const cur = sorted[i];
  const prev = i > 0 ? sorted[i - 1] : cur;
  const vFor = (s: Shot) => viewFor(s.target, capW, capH, s.pad, s.maxZoom, s.dy);
  const from = held(vFor(prev), prev, cur.frame, capW, capH, i > 0 ? sorted[i - 1] : undefined);
  const to = vFor(cur);
  const dur = cur.dur ?? 26;
  const p = frame < cur.frame ? 0 : ease(Math.min(1, (frame - cur.frame) / dur));
  const cx = interpolate(p, [0, 1], [from.x + from.w / 2, to.x + to.w / 2]);
  const cy = interpolate(p, [0, 1], [from.y + from.w / ASPECT / 2, to.y + to.w / ASPECT / 2]);
  let w = Math.exp(interpolate(p, [0, 1], [Math.log(from.w), Math.log(to.w)]));
  // drift: after arriving, push in slowly for the rest of the hold
  const next = sorted[i + 1];
  const holdEnd = next ? next.frame : cur.frame + dur + 300;
  const drift = cur.drift ?? 0.018;
  if (frame > cur.frame + dur && cur.target !== "full") {
    const q = Math.min(1, (frame - cur.frame - dur) / Math.max(1, holdEnd - cur.frame - dur));
    w *= 1 - drift * Easing.inOut(Easing.sin)(q);
  }
  const h = w / ASPECT;
  const view = { x: Math.min(capW - w, Math.max(0, cx - w / 2)), y: Math.min(capH - h, Math.max(0, cy - h / 2)), w };
  return { view, shot: cur, progress: p };
}

/** The view a shot has drifted to by the time the next one starts (so the next move begins where we really are). */
function held(v: View, s: Shot, until: number, capW: number, capH: number, _prev?: Shot): View {
  const dur = s.dur ?? 26;
  if (s.target === "full" || until <= s.frame + dur) return v;
  const w = v.w * (1 - (s.drift ?? 0.018));
  const cx = v.x + v.w / 2;
  const cy = v.y + v.w / ASPECT / 2;
  const h = w / ASPECT;
  return { x: Math.min(capW - w, Math.max(0, cx - w / 2)), y: Math.min(capH - h, Math.max(0, cy - h / 2)), w };
}

/** Map a capture-pixel point to film pixels under a view. */
export function toScreen(p: { x: number; y: number }, view: View, filmW: number) {
  const s = filmW / view.w;
  return { x: (p.x - view.x) * s, y: (p.y - view.y) * s, scale: s };
}

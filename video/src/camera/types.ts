// Shapes shared by the capture log (capture/record.mjs -> public/capture/<take>/events.json) and the camera.

/** A rectangle in capture pixels (2560x1440 frames). */
export type Box = { x: number; y: number; w: number; h: number };

export type CapEvent = {
  t: number; // seconds since the capture started
  type: "mark" | "focus" | "click" | "move" | "state" | "error";
  id: string;
  box?: Box | null;
  x?: number;
  y?: number;
  from?: { x: number; y: number };
  to?: { x: number; y: number };
  note?: string;
  text?: string;
};

export type Capture = {
  meta: { take: string; width: number; height: number; fps: number; seconds: number; dsf: number };
  events: CapEvent[];
};

/** Film time (frames, relative to the scene) pinned to capture time (seconds). */
export type Anchor = { film: number; cap: number };

/**
 * One camera move: at `frame` (scene-relative) start travelling to `target` over `dur` frames.
 * `pad` is breathing room around the box (1.25 = 25%), `maxZoom` caps the magnification against the full frame.
 */
export type Shot = {
  frame: number;
  target: Box | "full";
  pad?: number;
  maxZoom?: number;
  dur?: number;
  /** Nudge the framed centre (capture px) — e.g. to keep a box clear of the captions. */
  dy?: number;
  /** Slow push-in during the hold, as a fraction of the view (0.015 = 1.5%). */
  drift?: number;
  /** Dim everything outside the target box during this shot. */
  spotlight?: boolean;
};

export type Callout = {
  frame: number;
  dur: number;
  /** Anchor point in capture pixels. */
  at: { x: number; y: number };
  text: string;
  sub?: string;
  side?: "left" | "right" | "top" | "bottom";
  tone?: "accent" | "fraud" | "legit" | "neutral";
};

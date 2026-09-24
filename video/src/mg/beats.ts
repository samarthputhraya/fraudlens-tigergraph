// Narration-driven timing. A scene receives `beats` (frame offsets where each narration line starts) and reads its
// length from useVideoConfig(). Cues are authored as "frames into line i" against the scene's default timing and
// re-mapped onto whatever beats/duration the master timeline passes in, so the picture stays locked to the voice.

export type BeatProps = { beats: number[] };

export type SceneTiming = { beats: number[]; duration: number };

export type Timeline = {
  /** Start frame of narration line i. */
  start: (i: number) => number;
  /** Absolute frame for `f` frames into line i (f authored against the default timing). */
  at: (i: number, f: number) => number;
  /** Frames available in line i (to the next beat, or to the end of the scene). */
  span: (i: number) => number;
  /** Scene length. */
  duration: number;
};

export function makeTimeline(beats: number[] | undefined, duration: number, def: SceneTiming): Timeline {
  const n = def.beats.length;
  const b = (i: number) => {
    const v = beats?.[i];
    return typeof v === "number" && Number.isFinite(v) ? v : def.beats[i] ?? 0;
  };
  const span = (i: number) => Math.max(1, (i + 1 < n ? b(i + 1) : duration) - b(i));
  const defSpan = (i: number) => Math.max(1, (i + 1 < n ? def.beats[i + 1] : def.duration) - def.beats[i]);
  const scale = (i: number) => {
    const k = span(i) / defSpan(i);
    // Inner lines: the span is narration + a short gap, so it tracks the clip length. The last line's span includes the
    // scene tail, which changes independently of the voice: only ever compress it, never stretch it.
    return i + 1 < n ? Math.min(1.35, Math.max(0.6, k)) : Math.min(1, Math.max(0.6, k));
  };
  return {
    start: b,
    at: (i, f) => b(i) + f * scale(i),
    span,
    duration,
  };
}

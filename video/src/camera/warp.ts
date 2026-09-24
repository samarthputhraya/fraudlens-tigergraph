import type { Anchor, Capture, CapEvent } from "./types";

/**
 * Piecewise-linear time warp between film frames and capture seconds.
 *
 * Anchors pin a moment of the recording (an event in the capture log) to a frame of the film — so the moment the
 * agent calls `device_neighbors` lands exactly where the narrator says "who else used this phone". Between two
 * anchors the recording plays at a constant speed; each span becomes one video segment with its own playbackRate.
 */
export type Segment = { filmFrom: number; filmTo: number; capFrom: number; capTo: number; rate: number; skipped: number };

/** Faster than this and a screen recording turns into a blur; we cut the waiting instead (the camera move hides it). */
export const MAX_RATE = 3.2;

export function makeWarp(anchors: Anchor[], fps: number) {
  // keep anchors monotonic in both film and capture time (a probe that fired out of order is dropped)
  const a0 = [...anchors].sort((p, q) => p.film - q.film);
  const a: Anchor[] = [];
  for (const x of a0) if (!a.length || (x.cap > a[a.length - 1].cap && x.film > a[a.length - 1].film + 1)) a.push(x);
  if (a.length < 2) throw new Error("time warp needs two anchors");
  const segments: Segment[] = [];
  for (let i = 0; i < a.length - 1; i++) {
    const filmFrom = Math.round(a[i].film);
    const filmTo = Math.round(a[i + 1].film);
    if (filmTo <= filmFrom) continue;
    let capFrom = a[i].cap;
    const capTo = a[i + 1].cap;
    let rate = ((capTo - capFrom) * fps) / (filmTo - filmFrom);
    let skipped = 0;
    if (rate > MAX_RATE) {
      // play the last part of the wait at MAX_RATE, so the anchored moment still lands on its frame
      const keep = ((filmTo - filmFrom) * MAX_RATE) / fps;
      skipped = capTo - capFrom - keep;
      capFrom = capTo - keep;
      rate = MAX_RATE;
    }
    segments.push({ filmFrom, filmTo, capFrom, capTo, rate: Math.max(0.05, rate), skipped });
  }
  const capAt = (frame: number): number => {
    const s = segments.find((x) => frame < x.filmTo) ?? segments[segments.length - 1];
    return s.capFrom + ((frame - s.filmFrom) * s.rate) / fps;
  };
  const filmAt = (cap: number): number => {
    const s = segments.find((x) => cap < x.capTo) ?? segments[segments.length - 1];
    return s.filmFrom + (Math.max(0, cap - s.capFrom) * fps) / s.rate; // a moment inside a cut wait lands on the cut
  };
  return { segments, capAt, filmAt, length: segments[segments.length - 1].filmTo };
}

export type Warp = ReturnType<typeof makeWarp>;

/** The first event with this id (and type), or throws — a missing moment should fail loudly in the studio. */
export function evt(cap: Capture, id: string, type?: CapEvent["type"]): CapEvent {
  const e = cap.events.find((x) => x.id === id && (!type || x.type === type));
  if (!e) throw new Error(`capture ${cap.meta.take} has no event "${id}"${type ? ` (${type})` : ""}`);
  return e;
}

export function evtOr(cap: Capture, id: string, type?: CapEvent["type"]): CapEvent | null {
  return cap.events.find((x) => x.id === id && (!type || x.type === type)) ?? null;
}

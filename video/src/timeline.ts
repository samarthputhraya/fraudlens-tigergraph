import manifest from "../public/voice/manifest.json";
import spec from "./timeline-spec.json";
import { FPS } from "./theme";

/**
 * The film's clock is the narration. Each scene lists its narration lines; a line's length is the real duration of
 * its synthesized clip (video/public/voice/manifest.json), and the gaps/lead-ins give the picture room to breathe.
 */
export type SceneId =
  | "cold_open"
  | "architecture"
  | "investigate"
  | "proof"
  | "uncertain"
  | "metrics"
  | "governance"
  | "autonomy"
  | "outro";

type SceneSpec = { id: SceneId; lines: string[]; lead: number; gaps: number[] | number; tail: number };

/** Scene order, narration lines, lead-ins, gaps and tails live in timeline-spec.json (shared with finish.mjs). */
export const SCENES: SceneSpec[] = spec.scenes as SceneSpec[];

/** Overlap between consecutive scenes (a crossfade); scene starts step back by this much. */
export const XFADE: number = spec.xfade;

export type PlacedLine = { id: string; text: string; file: string; from: number; dur: number; local: number };
export type PlacedScene = { id: SceneId; from: number; dur: number; lines: PlacedLine[]; beats: number[] };

const byId = Object.fromEntries((manifest as { lines: { id: string; text: string; file: string; seconds: number }[] }).lines.map((l) => [l.id, l]));

export function placeScenes(): { scenes: PlacedScene[]; total: number } {
  const scenes: PlacedScene[] = [];
  let t = 0;
  for (const spec of SCENES) {
    const lines: PlacedLine[] = [];
    let local = spec.lead;
    spec.lines.forEach((id, i) => {
      const l = byId[id];
      if (!l) throw new Error(`no narration clip for ${id} — run video/voice/make_voice.py`);
      const dur = Math.ceil(l.seconds * FPS);
      lines.push({ id, text: l.text, file: l.file, from: t + local, dur, local });
      local += dur;
      if (i < spec.lines.length - 1) local += Array.isArray(spec.gaps) ? spec.gaps[i] ?? 16 : spec.gaps;
    });
    const dur = local + spec.tail;
    scenes.push({ id: spec.id, from: t, dur, lines, beats: lines.map((l) => l.local) });
    t += dur - XFADE;
  }
  return { scenes, total: t + XFADE };
}

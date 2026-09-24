import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "../theme";

export type CaptionLine = { id: string; text: string; from: number; dur: number };

/** Split a narration line into caption chunks of at most ~2 lines, breaking at sentence/clause boundaries. */
export function chunk(text: string, max = 84): string[] {
  const sentences = text.match(/[^.!?;:]+[.!?;:]?/g)?.map((s) => s.trim()).filter(Boolean) ?? [text];
  const out: string[] = [];
  for (const s of sentences) {
    if (s.length <= max) {
      if (out.length && (out[out.length - 1] + " " + s).length <= max && !/[.!?]$/.test(out[out.length - 1])) out[out.length - 1] += " " + s;
      else out.push(s);
      continue;
    }
    // long sentence: break at commas near the middle
    const parts = s.split(/(?<=,)\s+/);
    let cur = "";
    for (const p of parts) {
      if ((cur + " " + p).trim().length > max && cur) {
        out.push(cur.trim());
        cur = p;
      } else cur = (cur + " " + p).trim();
    }
    if (cur) out.push(cur.trim());
  }
  return out;
}

/**
 * Lower-third captions timed to the narration: each line's chunks share the clip's duration in proportion to their
 * length (speech rate is roughly constant within a clip), with a short fade between chunks.
 */
export const Captions: React.FC<{ lines: CaptionLine[] }> = ({ lines }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const line = lines.find((l) => frame >= l.from && frame < l.from + l.dur + 6);
  if (!line) return null;
  const parts = chunk(line.text);
  const total = parts.reduce((a, p) => a + p.length, 0);
  let t = line.from;
  let cur = parts[0];
  let start = line.from;
  let end = line.from + line.dur;
  for (const p of parts) {
    const d = (line.dur * p.length) / total;
    if (frame >= t && frame < t + d) {
      cur = p;
      start = t;
      end = t + d;
    }
    t += d;
  }
  if (frame >= line.from + line.dur) {
    cur = parts[parts.length - 1];
    start = line.from + line.dur - (line.dur * cur.length) / total;
    end = line.from + line.dur;
  }
  const o = interpolate(frame, [start, start + 5, end - 3, end + 5], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width, height, pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: 230,
          background: "linear-gradient(to top, rgba(4,6,9,0.86) 0%, rgba(4,6,9,0.55) 55%, rgba(4,6,9,0) 100%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: "50%",
          bottom: 62,
          transform: "translateX(-50%)",
          width: 1480,
          textAlign: "center",
          fontFamily: FONT.sans,
          fontWeight: 500,
          fontSize: 40,
          lineHeight: 1.3,
          letterSpacing: "-0.005em",
          color: C.ink100,
          opacity: o,
          textShadow: "0 2px 12px rgba(0,0,0,0.6)",
          textWrap: "balance" as React.CSSProperties["textWrap"],
        }}
      >
        {cur}
      </div>
    </div>
  );
};

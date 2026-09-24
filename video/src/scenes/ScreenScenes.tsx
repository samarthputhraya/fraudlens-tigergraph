import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Screen } from "../camera/Screen";
import type { Anchor, Box, Callout, Capture, Shot } from "../camera/types";
import { evtOr, makeWarp, type Warp } from "../camera/warp";
import type { PlacedScene } from "../timeline";
import { C, FONT, FPS } from "../theme";

/**
 * The directing of each screen scene: which recorded moment lands on which word, where the camera looks, and what
 * the callouts say. Every box comes from the recorder's log of the real DOM, so the zoom lands exactly on the
 * element (no guessing from mouse clicks) and holds for as long as the narration is about it.
 */
type Dir = { warp: Warp; shots: Shot[]; callouts: Callout[] };

const L = (sc: PlacedScene, id: string) => {
  const l = sc.lines.find((x) => x.id === id);
  if (!l) throw new Error(`scene ${sc.id} has no line ${id}`);
  return { start: l.local, dur: l.dur, end: l.local + l.dur };
};
const t = (cap: Capture, id: string, type?: "mark" | "focus" | "click") => evtOr(cap, id, type)?.t ?? null;
/** The logged on-screen box of an element, clipped to the frame; null when most of it was scrolled out of view. */
const box = (cap: Capture, id: string): Box | null => {
  const e = cap.events.filter((x) => x.id === id && x.type === "focus" && x.box).pop();
  const b = e?.box ?? null;
  if (!b) return null;
  const x0 = Math.max(0, b.x), y0 = Math.max(0, b.y);
  const x1 = Math.min(cap.meta.width, b.x + b.w), y1 = Math.min(cap.meta.height, b.y + b.h);
  if (x1 <= x0 || y1 <= y0 || (x1 - x0) * (y1 - y0) < 0.5 * b.w * b.h) return null;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
};
/** The top part of a tall panel (a camera framing a 1,200-px column would have to pull all the way out). */
const topOf = (b: Box | null, h = 720): Box | null => (b ? { ...b, h: Math.min(b.h, h) } : null);
const union = (...bs: (Box | null)[]): Box | null => {
  const xs = bs.filter(Boolean) as Box[];
  if (!xs.length) return null;
  const x = Math.min(...xs.map((b) => b.x));
  const y = Math.min(...xs.map((b) => b.y));
  return { x, y, w: Math.max(...xs.map((b) => b.x + b.w)) - x, h: Math.max(...xs.map((b) => b.y + b.h)) - y };
};
const center = (b: Box | null, fx = 0.5, fy = 0.5) => (b ? { x: b.x + b.w * fx, y: b.y + b.h * fy } : { x: 1280, y: 720 });
function anchors(list: (Anchor | null | false)[]): Anchor[] {
  return list.filter((a): a is Anchor => !!a && Number.isFinite(a.cap) && Number.isFinite(a.film));
}
const A = (film: number, cap: number | null): Anchor | null => (cap == null ? null : { film, cap });
function shots(list: (Shot | null | false)[]): Shot[] {
  return list.filter((s): s is Shot => !!s && (s.target === "full" || !!s.target));
}
const S = (frame: number, target: Box | "full" | null, o: Partial<Shot> = {}): Shot | null => (target ? { frame, target, ...o } : null);

// ---- 1. queue -> live investigation -> decision -------------------------------------------------------------
export function directInvestigate(cap: Capture, sc: PlacedScene): Dir {
  const l1 = L(sc, "live1"), l2 = L(sc, "live2"), l3 = L(sc, "live3"), l4 = L(sc, "live4"), d1 = L(sc, "dec1"), d2 = L(sc, "dec2");
  const click = t(cap, "queue.investigate014", "click");
  const tools = t(cap, "live.tool.device_neighbors");
  const ring = t(cap, "live.ring.cards");
  const memory = t(cap, "live.tool.similar_cases");
  const complete = t(cap, "live.complete");
  const top = t(cap, "live.decide.top");
  const nbaT = t(cap, "live.decide.nba");
  const warp = makeWarp(
    anchors([
      A(0, (t(cap, "queue.ready") ?? 0) + 0.2),
      A(l1.end - 10, click),
      A(l2.start + 24, tools),
      A(l2.start + Math.round(l2.dur * 0.5), ring),
      A(l3.start + 18, memory),
      A(l4.end - 6, complete),
      A(d1.start + 8, top != null ? top + 1.2 : null),
      A(d2.start + 6, nbaT != null ? nbaT + 1.4 : null),
      A(sc.dur, t(cap, "live.end")),
    ]),
    FPS,
  );
  const f = (s: number | null, fb: number) => (s == null ? fb : Math.round(warp.filmAt(s)));
  const row = box(cap, "queue.row014");
  const timeline = box(cap, "live.timeline.tool.device_neighbors") ?? box(cap, "live.timeline.final");
  const graph = box(cap, "live.graph") ?? box(cap, "live.graph.final");
  const gauge = union(box(cap, "live.gauge.final"), box(cap, "live.waterfall"));
  const stop = box(cap, "live.stoprule");
  const nba = topOf(box(cap, "live.nba.final"), 760);
  const ringF = f(ring, l2.start + Math.round(l2.dur * 0.5));
  return {
    warp,
    shots: shots([
      S(0, "full", { dur: 1 }),
      S(l1.start - 8, row, { pad: 1.28, maxZoom: 1.9, dur: 30, spotlight: true }),
      S(f(click, l1.end) + 4, "full", { dur: 24 }),
      S(l2.start + 10, timeline, { pad: 1.12, maxZoom: 2.0, dur: 28 }),
      S(ringF - 8, graph, { pad: 1.06, maxZoom: 2.0, dur: 30 }),
      S(l3.start, timeline, { pad: 1.12, maxZoom: 2.0, dur: 28 }),
      S(l4.start - 4, graph, { pad: 1.02, maxZoom: 2.0, dur: 26, drift: 0.03 }),
      S(d1.start - 10, gauge, { pad: 1.08, maxZoom: 2.1, dur: 28 }),
      S(d1.start + Math.round(d1.dur * 0.55), stop, { pad: 2.6, maxZoom: 2.6, dur: 24 }),
      S(d2.start - 6, nba, { pad: 1.06, maxZoom: 2.0, dur: 28 }),
    ]),
    callouts: [
      graph ? { frame: ringF + 6, dur: l2.end - ringF, at: center(graph, 0.62, 0.3), text: "19 other cardholders · 8 days", sub: "same device profile · New on every account · anonymous proxy", side: "right" as const, tone: "fraud" as const } : null,
      timeline ? { frame: l3.start + 30, dur: l3.dur - 36, at: center(timeline, 0.92, 0.55), text: "4 confirmed closed cases", sub: "same SM-G935F device · Aug–Sep", side: "right" as const, tone: "accent" as const } : null,
      graph ? { frame: l4.start + Math.round(l4.dur * 0.45), dur: Math.round(l4.dur * 0.55), at: center(graph, 0.5, 0.18), text: "Undocumented pattern", sub: "shared-device ring · R6 + R9", side: "top" as const, tone: "fraud" as const } : null,
      stop ? { frame: d1.start + Math.round(d1.dur * 0.62), dur: Math.round(d1.dur * 0.4), at: center(stop, 0.05, 0.5), text: "p 0.97 · stop rule met", sub: "policy section 6", side: "left" as const, tone: "legit" as const } : null,
    ].filter(Boolean) as Callout[],
  };
}

// ---- 2. case file: evidence, re-prove on Savanna, SAR --------------------------------------------------------
export function directProof(cap: Capture, sc: PlacedScene): Dir {
  const p1 = L(sc, "proof1"), p2 = L(sc, "proof2");
  const warp = makeWarp(
    anchors([
      A(0, (t(cap, "proof.open") ?? 0) + 0.4),
      A(p1.start + Math.round(p1.dur * 0.62), t(cap, "proof.reprove", "click")),
      A(p1.end + 4, (t(cap, "proof.reprove", "click") ?? 0) + 2.6),
      A(p2.start + 10, (t(cap, "proof.end") ?? 0) - 6.2),
      A(sc.dur, t(cap, "proof.end")),
    ]),
    FPS,
  );
  const row = box(cap, "proof.evidence.row");
  const result = box(cap, "proof.result");
  const narrative = box(cap, "proof.sar.narrative") ?? box(cap, "proof.sar");
  return {
    warp,
    shots: shots([
      S(0, box(cap, "proof.evidence") ?? "full", { pad: 1.05, maxZoom: 1.6, dur: 1 }),
      S(8, row, { pad: 1.25, maxZoom: 2.1, dur: 30, spotlight: true }),
      S(p1.start + Math.round(p1.dur * 0.7), union(row, result), { pad: 1.12, maxZoom: 2.2, dur: 26 }),
      S(p2.start - 4, narrative, { pad: 1.1, maxZoom: 1.9, dur: 30 }),
    ]),
    callouts: result
      ? [{ frame: p1.start + Math.round(p1.dur * 0.78), dur: Math.round(p1.dur * 0.3), at: center(result, 1, 0.3), text: "Re-run live on Savanna", sub: "via the official TigerGraph MCP", side: "right" as const, tone: "legit" as const }]
      : [],
  };
}

// ---- 3. an alert that is not fraud --------------------------------------------------------------------------
export function directUncertain(cap: Capture, sc: PlacedScene): Dir {
  const u1 = L(sc, "unc1"), u2 = L(sc, "unc2");
  const warp = makeWarp(anchors([A(0, (t(cap, "unc.open") ?? 0) + 0.3), A(sc.dur, t(cap, "unc.end"))]), FPS);
  return {
    warp,
    shots: shots([
      S(0, box(cap, "unc.summary") ?? "full", { pad: 1.1, maxZoom: 1.8, dur: 1 }),
      S(u2.start - 6, box(cap, "unc.model"), { pad: 1.2, maxZoom: 2.2, dur: 28, spotlight: true }),
      S(u2.start + Math.round(u2.dur * 0.5), topOf(box(cap, "unc.nba"), 900), { pad: 1.05, maxZoom: 1.8, dur: 28 }),
    ]),
    callouts: box(cap, "unc.model")
      ? [{ frame: u2.start + 10, dur: Math.round(u2.dur * 0.45), at: center(box(cap, "unc.model"), 0.8, 0.5), text: "Model: 0.5% fraud", sub: "bank score 0.90 · verify, don't block (R1)", side: "top" as const, tone: "legit" as const }]
      : [],
  };
}

// ---- 4. governance ------------------------------------------------------------------------------------------
export function directGovernance(cap: Capture, sc: PlacedScene): Dir {
  const g1 = L(sc, "gov1"), g2 = L(sc, "gov2");
  const denied = t(cap, "gov.approve.denied", "click");
  const ok = t(cap, "gov.approve.ok", "click");
  const warp = makeWarp(
    anchors([A(0, (t(cap, "gov.open") ?? 0) + 0.3), A(g1.start + Math.round(g1.dur * 0.45), denied), A(g1.end + 6, ok), A(sc.dur, t(cap, "gov.end"))]),
    FPS,
  );
  const card = box(cap, "gov.card");
  return {
    warp,
    shots: shots([
      S(0, card ?? "full", { pad: 1.1, maxZoom: 1.7, dur: 1 }),
      S(g1.start + Math.round(g1.dur * 0.3), box(cap, "gov.sar.row"), { pad: 1.25, maxZoom: 2.0, dur: 26 }),
      S(g2.start, card, { pad: 1.2, maxZoom: 1.7, dur: 26 }),
    ]),
    callouts: [],
  };
}

// ---- 5. the monitor ----------------------------------------------------------------------------------------
export function directAutonomy(cap: Capture, sc: PlacedScene): Dir {
  const warp = makeWarp(anchors([A(0, (t(cap, "auto.open") ?? 0) + 0.3), A(sc.dur, t(cap, "auto.end"))]), FPS);
  return {
    warp,
    shots: shots([S(0, "full", { dur: 1 }), S(24, box(cap, "auto.rings"), { pad: 1.08, maxZoom: 1.8, dur: 30 })]),
    callouts: [],
  };
}

/** A small, honest badge whenever the recording is sped up. */
const SpeedBadge: React.FC<{ warp: Warp }> = ({ warp }) => {
  const frame = useCurrentFrame();
  const seg = warp.segments.find((s) => frame >= s.filmFrom && frame < s.filmTo);
  const fast = seg && seg.rate > 1.4 ? seg.rate : 0;
  const o = interpolate(fast ? 1 : 0, [0, 1], [0, 1]);
  if (!fast) return null;
  return (
    <div style={{ position: "absolute", right: 40, top: 36, opacity: o, fontFamily: FONT.mono, fontSize: 20, color: C.ink300, background: "rgba(10,13,18,0.8)", border: `1px solid ${C.ink600}`, borderRadius: 999, padding: "6px 14px" }}>
      <svg width="22" height="14" viewBox="0 0 22 14" style={{ marginRight: 8, verticalAlign: "-1px" }}>
        <path d="M1 1 L9 7 L1 13 Z M11 1 L19 7 L11 13 Z" fill={C.ink300} />
      </svg>
      {fast.toFixed(1)}× speed{seg!.skipped > 1 ? " · wait trimmed" : ""}
    </div>
  );
};

export const ScreenScene: React.FC<{ capture: Capture; dir: Dir }> = ({ capture, dir }) => {
  const { durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const fade = interpolate(frame, [0, 10, durationInFrames - 10, durationInFrames], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <Screen capture={capture} warp={dir.warp} shots={dir.shots} callouts={dir.callouts} />
      <SpeedBadge warp={dir.warp} />
    </AbsoluteFill>
  );
};

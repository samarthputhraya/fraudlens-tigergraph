import { Video } from "@remotion/media";
import React from "react";
import { AbsoluteFill, Easing, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "../theme";
import type { Callout, Capture, Shot } from "./types";
import { cameraAt, toScreen, type View } from "./view";
import type { Warp } from "./warp";

type Props = {
  capture: Capture;
  warp: Warp;
  shots: Shot[];
  callouts?: Callout[];
  cursor?: boolean;
};

/**
 * The recorded Command Center, directed: time-warped segments of the capture, a camera that frames the exact
 * on-screen boxes logged by the recorder, a synthetic cursor replaying the recorded moves and clicks, an optional
 * spotlight, and callouts pinned to capture coordinates.
 */
export const Screen: React.FC<Props> = ({ capture, warp, shots, callouts = [], cursor = true }) => {
  const frame = useCurrentFrame();
  const { width, fps } = useVideoConfig();
  const capW = capture.meta.width;
  const capH = capture.meta.height;
  const { view, shot, progress } = cameraAt(frame, shots, capW, capH);
  const s = width / view.w;
  const src = staticFile(`capture/${capture.meta.take}/screen.mp4`);

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          width: capW,
          height: capH,
          transformOrigin: "0 0",
          transform: `scale(${s}) translate(${-view.x}px, ${-view.y}px)`,
        }}
      >
        {warp.segments.map((seg, i) => (
          <Sequence key={i} from={seg.filmFrom} durationInFrames={seg.filmTo - seg.filmFrom} layout="none">
            <Video
              src={src}
              muted
              trimBefore={Math.max(0, Math.round(seg.capFrom * fps))}
              playbackRate={seg.rate}
              style={{ position: "absolute", left: 0, top: 0, width: capW, height: capH }}
            />
          </Sequence>
        ))}
        {cursor && <Cursor capture={capture} warp={warp} scale={s} />}
      </div>
      {shot.spotlight && shot.target !== "full" && <Spotlight view={view} box={shot.target} progress={progress} />}
      {callouts.map((c, i) => (
        <CalloutPill key={i} c={c} view={view} />
      ))}
    </AbsoluteFill>
  );
};

// ---- cursor -------------------------------------------------------------------------------------------------
const MOVE_S = 0.5;
const Cursor: React.FC<{ capture: Capture; warp: Warp; scale: number }> = ({ capture, warp, scale }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const moves = capture.events.filter((e) => e.type === "move" && e.from && e.to);
  const clicks = capture.events.filter((e) => e.type === "click");
  if (!moves.length) return null;
  const fm = moves.map((m) => ({ ...m, f: warp.filmAt(m.t) }));
  let k = -1;
  for (let i = 0; i < fm.length; i++) if (fm[i].f - MOVE_S * fps <= frame) k = i;
  if (k < 0) return null;
  const m = fm[k];
  const start = m.f - MOVE_S * fps;
  const p = Easing.bezier(0.3, 0, 0.1, 1)(Math.min(1, Math.max(0, (frame - start) / (MOVE_S * fps))));
  const x = interpolate(p, [0, 1], [m.from!.x, m.to!.x]);
  const y = interpolate(p, [0, 1], [m.from!.y, m.to!.y]);
  // visible from a moment before the move until ~2 s after the last click of that move
  const lastClick = clicks.filter((c) => c.id === m.id).map((c) => warp.filmAt(c.t))[0] ?? m.f;
  const vis = interpolate(frame, [start - 8, start, lastClick + fps * 1.6, lastClick + fps * 2.1], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  if (vis <= 0.01) return null;
  const clickF = clicks.map((c) => warp.filmAt(c.t)).find((f) => frame >= f && frame < f + 18);
  const press = clickF != null ? interpolate(frame - clickF, [0, 4, 10], [1, 0.86, 1], { extrapolateRight: "clamp" }) : 1;
  const size = 34 / Math.max(0.9, Math.min(1.6, scale)); // keep the cursor a steady size on screen while zooming
  return (
    <div style={{ position: "absolute", left: x, top: y, opacity: vis, transform: `scale(${press})`, transformOrigin: "0 0" }}>
      {clickF != null && <Ripple age={frame - clickF} size={size} />}
      <svg width={size} height={size * 1.25} viewBox="0 0 24 30" style={{ filter: "drop-shadow(0 3px 6px rgba(0,0,0,0.55))" }}>
        <path d="M2 1.5 L2 23.5 L7.6 18.2 L11.3 27 L15.1 25.4 L11.5 16.8 L19.3 16.8 Z" fill="#F4F6F9" stroke="#0A0D12" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    </div>
  );
};

const Ripple: React.FC<{ age: number; size: number }> = ({ age, size }) => {
  const r = interpolate(age, [0, 16], [size * 0.25, size * 1.5], { extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const o = interpolate(age, [0, 16], [0.75, 0], { extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        left: -r,
        top: -r,
        width: r * 2,
        height: r * 2,
        borderRadius: "50%",
        border: `${Math.max(2, size * 0.08)}px solid ${C.tg}`,
        opacity: o,
      }}
    />
  );
};

// ---- spotlight ----------------------------------------------------------------------------------------------
const Spotlight: React.FC<{ view: View; box: { x: number; y: number; w: number; h: number }; progress: number }> = ({ view, box, progress }) => {
  const { width, height } = useVideoConfig();
  const a = toScreen({ x: box.x, y: box.y }, view, width);
  const b = toScreen({ x: box.x + box.w, y: box.y + box.h }, view, width);
  const pad = 10;
  const o = 0.5 * progress;
  return (
    <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
      <defs>
        <mask id="spot">
          <rect width={width} height={height} fill="white" />
          <rect x={a.x - pad} y={a.y - pad} width={b.x - a.x + pad * 2} height={b.y - a.y + pad * 2} rx={16} fill="black" />
        </mask>
      </defs>
      <rect width={width} height={height} fill="#03050A" opacity={o} mask="url(#spot)" />
      <rect x={a.x - pad} y={a.y - pad} width={b.x - a.x + pad * 2} height={b.y - a.y + pad * 2} rx={16} fill="none" stroke={C.tg} strokeOpacity={0.55 * progress} strokeWidth={2} />
    </svg>
  );
};

// ---- callouts -----------------------------------------------------------------------------------------------
const TONE = { accent: C.tg, fraud: C.fraud, legit: C.legit, neutral: C.ink300 } as const;
const CalloutPill: React.FC<{ c: Callout; view: View }> = ({ c, view }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  if (frame < c.frame - 2 || frame > c.frame + c.dur + 12) return null;
  const inP = spring({ frame: frame - c.frame, fps, config: { damping: 200 }, durationInFrames: 16 });
  const outP = interpolate(frame, [c.frame + c.dur, c.frame + c.dur + 12], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const p = toScreen(c.at, view, width);
  const side = c.side ?? "right";
  const off = 26;
  const tone = TONE[c.tone ?? "accent"];
  const pos: React.CSSProperties =
    side === "right"
      ? { left: p.x + off, top: p.y, transform: `translateY(-50%) translateX(${(1 - inP) * -12}px)` }
      : side === "left"
        ? { left: p.x - off, top: p.y, transform: `translate(-100%, -50%) translateX(${(1 - inP) * 12}px)` }
        : side === "top"
          ? { left: p.x, top: p.y - off, transform: `translate(-50%, -100%) translateY(${(1 - inP) * 12}px)` }
          : { left: p.x, top: p.y + off, transform: `translateX(-50%) translateY(${(1 - inP) * -12}px)` };
  return (
    <>
      <div style={{ position: "absolute", left: p.x - 7, top: p.y - 7, width: 14, height: 14, borderRadius: 7, background: tone, opacity: inP * outP, boxShadow: `0 0 0 6px ${tone}33` }} />
      <div
        style={{
          position: "absolute",
          ...pos,
          opacity: inP * outP,
          background: "rgba(10,13,18,0.92)",
          border: `1px solid ${tone}80`,
          borderRadius: 14,
          padding: "14px 20px",
          boxShadow: "0 18px 40px -12px rgba(0,0,0,0.7)",
          maxWidth: 560,
        }}
      >
        <div style={{ fontFamily: FONT.sans, fontWeight: 600, fontSize: 30, color: C.ink100, letterSpacing: "-0.01em", lineHeight: 1.2 }}>{c.text}</div>
        {c.sub && <div style={{ fontFamily: FONT.mono, fontSize: 19, color: C.ink300, marginTop: 6 }}>{c.sub}</div>}
      </div>
    </>
  );
};

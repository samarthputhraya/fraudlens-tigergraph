import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { LensMarkAnimated } from "../brand/LensMarkAnimated";
import { Canvas } from "../mg/Canvas";
import { EASE, EASE_IO, mix, rgba, rise, tween } from "../mg/anim";
import { BeatProps, makeTimeline } from "../mg/beats";
import { MaskRise, mono, sans } from "../mg/type";
import { C, FONT } from "../theme";

// Outro. "FraudLens. Agentic, calibrated, and provable. The model predicts. TigerGraph proves."
// The mark draws on, the wordmark rises, the three words land with the voice, the credits settle, and the last beat
// lights "TigerGraph proves." Everything is in place before the narration ends; the tail is a still hold (no fade).

export const OUTRO_DEFAULT = { beats: [20], duration: 471 };

const CUE = {
  mark: -16, // the mark starts drawing just before the voice
  wordmark: 8, // "FraudLens."
  words: [66, 112, 154], // "Agentic," "calibrated," "and provable."
  band: 188, // credits settle in the pause after "provable"
  tagline: 226, // "The model predicts."
  proves: 300, // "TigerGraph proves."
};

const MARK = 150;
const MARK_TOP = 222;
const WORD_TOP = 392;
const WORDS_TOP = 566;
const TAG_TOP = 630;
const PILLS_TOP = 808;
const URL_TOP = 872;
const FOOT_TOP = 926;

const TECH = ["TigerGraph Savanna", "Official MCP", "GSQL", "TigerVector", "Gemini on Vertex AI", "LangGraph"];
const WORDS = ["Agentic", "Calibrated", "Provable"];

export const Outro: React.FC<BeatProps> = ({ beats }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D, fps } = useVideoConfig();
  const T = makeTimeline(beats, D, OUTRO_DEFAULT);
  // everything must have landed ~2.3 s before the end, whatever the timing; the rest is a hold
  const holdAt = D - 70;
  const at = (f: number) => Math.min(T.at(0, f), holdAt - 24);
  const tw = (start: number, dur = 20, e = EASE) => tween(frame, start, dur, e);

  const m0 = Math.max(2, at(CUE.mark));
  const ring = tw(m0, 30, EASE_IO);
  const handle = tw(m0 + 24, 14, EASE);
  const tri = tw(m0 + 28, 18, EASE);
  const pop = (d: number) => spring({ frame: frame - (m0 + d), fps, config: { damping: 11, stiffness: 170, mass: 0.6 } });
  const dots: [number, number, number] = [pop(34), pop(38), pop(30)];
  const glow = tw(m0 + 30, 40);

  const wordP = tw(at(CUE.wordmark), 28);
  const wordsP = CUE.words.map((c) => tw(at(c), 20));
  const tag1 = tw(at(CUE.tagline), 24);
  const tag2 = tw(at(CUE.tagline) + 9, 24);
  const provesP = tw(at(CUE.proves), 22);
  const pillP = TECH.map((_, i) => tw(at(CUE.band) + i * 4, 22));
  const urlP = tw(at(CUE.band) + 18, 22);
  const footP = tw(at(CUE.band) + 26, 22);

  // slow push while things land, still during the hold
  const drift = interpolate(frame, [0, holdAt], [1, 1.018], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <Canvas glow={1.15 + 0.35 * glow} glowAt={[50, 44]}>
      <AbsoluteFill style={{ scale: `${drift}` }}>
        <div style={{ position: "absolute", left: 960 - MARK / 2, top: MARK_TOP }}>
          <LensMarkAnimated size={MARK} ring={ring} handle={handle} tri={tri} dots={dots} glow={glow} />
        </div>

        <div style={{ position: "absolute", left: 0, right: 0, top: WORD_TOP, display: "flex", justifyContent: "center" }}>
          <MaskRise p={wordP}>
            <span style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 124, letterSpacing: "-0.045em", lineHeight: "136px", color: C.ink100 }}>FraudLens</span>
          </MaskRise>
        </div>

        {/* AGENTIC · CALIBRATED · PROVABLE, each word with its line of the voice */}
        <div style={{ position: "absolute", left: 0, right: 0, top: WORDS_TOP, display: "flex", justifyContent: "center", alignItems: "center", gap: 26 }}>
          {WORDS.map((w, i) => (
            <React.Fragment key={w}>
              {i > 0 ? <div style={{ width: 5, height: 5, borderRadius: 5, background: C.tg, opacity: wordsP[i], scale: `${wordsP[i]}` }} /> : null}
              <div style={{ ...mono(22, C.ink200, 500), letterSpacing: "0.3em", marginRight: "-0.3em", textTransform: "uppercase", ...rise(wordsP[i], 12, 4) }}>{w}</div>
            </React.Fragment>
          ))}
        </div>

        <div style={{ position: "absolute", left: 0, right: 0, top: TAG_TOP, display: "flex", justifyContent: "center", gap: 12, ...sans(40, 500, C.ink100, -0.015) }}>
          <span style={rise(tag1, 14, 4)}>The model predicts.</span>
          <span
            style={{
              ...rise(tag2, 14, 4),
              color: mix(C.ink500, C.tg, provesP),
              textShadow: provesP > 0 ? `0 0 ${(28 * provesP).toFixed(1)}px ${rgba(C.tg, 0.35 * provesP)}` : undefined,
            }}
          >
            TigerGraph proves.
          </span>
        </div>

        {/* credits */}
        <div style={{ position: "absolute", left: 0, right: 0, top: PILLS_TOP, display: "flex", justifyContent: "center", gap: 12 }}>
          {TECH.map((t, i) => (
            <div
              key={t}
              style={{
                ...sans(17, 500, C.ink200, 0),
                padding: "8px 16px",
                borderRadius: 999,
                background: rgba(C.ink850, 0.85),
                border: `1px solid ${C.ink600}`,
                ...rise(pillP[i], 10),
              }}
            >
              {t}
            </div>
          ))}
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, top: URL_TOP, display: "flex", justifyContent: "center", ...rise(urlP, 8) }}>
          <span style={mono(19, C.ink400)}>
            github.com/samarthputhraya/<span style={{ color: C.ink100 }}>fraudlens-tigergraph</span>
          </span>
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, top: FOOT_TOP, display: "flex", justifyContent: "center", ...rise(footP, 6) }}>
          <span style={sans(15, 400, C.ink400, 0.02)}>Hacker House Goa 2026 · TigerGraph Agentic Fraud Investigation</span>
        </div>
      </AbsoluteFill>
    </Canvas>
  );
};

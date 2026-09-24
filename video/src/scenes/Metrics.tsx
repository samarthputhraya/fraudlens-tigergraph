import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Canvas } from "../mg/Canvas";
import { EASE, EASE_IN, EASE_IO, lerp, mix, rgba, rise, tween } from "../mg/anim";
import { BeatProps, makeTimeline } from "../mg/beats";
import { mono, sans } from "../mg/type";
import { C } from "../theme";

// Metrics. On October's high-score alerts (a month the model never saw), how often each score ranks a real fraud above
// a false alarm (ROC AUC): the bank's risk score 0.60, the FraudLens transaction model 0.93. Numbers from
// eval/model_report.json (auc_october_alerts_score_ge_0_5 = 0.9334, n = 5,335; auc_october_all = 0.9726).

export const METRICS_DEFAULT = { beats: [16], duration: 481 };

const CUE = {
  title: 0, // "On October's high-score alerts,"
  sub: 64, // "which the model never saw,"
  tracks: 110,
  bankLabel: 128, // "the bank's own score"
  bankGrow: [184, 282], // "...ranks a real fraud above a false alarm sixty"
  bankCaption: 286, // "...times in a hundred"
  oursLabel: 328,
  oursGrow: [344, 394], // "Ours does it ninety-three"
  oursCaption: 398,
  footnote: 150,
};

const X0 = 318;
const TRACK_W = 1100;
const BAR_H = 48;
const BANK_Y = 414;
const OURS_Y = 628;
const GROW = Easing.bezier(0.33, 0, 0.12, 1);

/** "≥" drawn to match Inter semibold (the bundled Inter subset has no U+2265). */
const Gte: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size * 0.62} height={size} viewBox="0 0 62 100" style={{ margin: `0 ${size * 0.2}px 0 ${size * 0.22}px`, display: "block" }}>
    <path d="M8 26 L54 45 L8 64" fill="none" stroke={C.ink100} strokeWidth={8.6} strokeLinecap="round" strokeLinejoin="round" />
    <path d="M8 78 H54" fill="none" stroke={C.ink100} strokeWidth={8.6} strokeLinecap="round" />
  </svg>
);

export const Metrics: React.FC<BeatProps> = ({ beats }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const T = makeTimeline(beats, D, METRICS_DEFAULT);
  const at = (f: number) => T.at(0, f);
  const tw = (start: number, dur = 20, e = EASE) => tween(frame, start, dur, e);

  const exitP = tween(frame, D - 14, 14, EASE_IN);
  const drift = interpolate(frame, [0, D], [1, 1.016]);

  const titleP = tw(at(CUE.title), 24);
  const subP = tw(at(CUE.sub), 22);
  const trackP = tw(at(CUE.tracks), 30, EASE_IO);
  const bankLabelP = tw(at(CUE.bankLabel), 20);
  const bankG = tween(frame, at(CUE.bankGrow[0]), at(CUE.bankGrow[1]) - at(CUE.bankGrow[0]), GROW);
  const bankCapP = tw(at(CUE.bankCaption), 22);
  const oursLabelP = tw(at(CUE.oursLabel), 20);
  const oursTrackP = tw(at(CUE.oursLabel), 26, EASE_IO);
  const oursG = tween(frame, at(CUE.oursGrow[0]), at(CUE.oursGrow[1]) - at(CUE.oursGrow[0]), GROW);
  const oursCapP = tw(at(CUE.oursCaption), 22);
  const landed = tw(at(CUE.oursGrow[1]) - 2, 8) * (1 - tw(at(CUE.oursGrow[1]) + 6, 40, EASE_IO));
  const bankRecede = tw(at(CUE.oursGrow[1]) + 4, 30, EASE_IO);
  const footP = tw(at(CUE.footnote), 30);

  const bankV = 0.6 * bankG;
  const oursV = 0.93 * oursG;

  const bar = (y: number, value: number, track: number, kind: "bank" | "ours", shown: number) => {
    const w = TRACK_W * value;
    const isOurs = kind === "ours";
    return (
      <>
        {track > 0.001 ? (
          <div
            style={{
              position: "absolute",
              left: X0,
              top: y,
              width: TRACK_W * track,
              height: BAR_H,
              borderRadius: 12,
              background: "linear-gradient(90deg, rgba(150, 161, 179, 0.075), rgba(150, 161, 179, 0.035))",
            }}
          />
        ) : null}
        {w > 1 ? (
          <div
            style={{
              position: "absolute",
              left: X0,
              top: y,
              width: Math.max(BAR_H * 0.5, w),
              height: BAR_H,
              borderRadius: 12,
              background: isOurs ? `linear-gradient(90deg, ${C.tg600} 0%, ${C.tg} 72%, ${C.tg400} 100%)` : `linear-gradient(90deg, ${C.ink600} 0%, ${C.ink400} 100%)`,
              boxShadow: isOurs
                ? `0 0 ${(38 + 30 * landed).toFixed(1)}px ${rgba(C.tg, 0.32 + 0.25 * landed)}, inset 0 1px 0 rgba(255,255,255,0.18)`
                : "inset 0 1px 0 rgba(255,255,255,0.08)",
              opacity: shown,
            }}
          >
            <div style={{ position: "absolute", right: 6, top: 8, bottom: 8, width: 2, borderRadius: 1, background: isOurs ? rgba("#FFE3CC", 0.9) : rgba(C.ink200, 0.55) }} />
          </div>
        ) : null}
        <div
          style={{
            position: "absolute",
            left: X0 + Math.max(w, 0) + 30,
            top: y + BAR_H / 2 - 38,
            ...mono(64, isOurs ? C.tg : mix(C.ink100, C.ink300, bankRecede), 600),
            letterSpacing: "-0.03em",
            lineHeight: "76px",
            opacity: Math.min(1, value * 12) * shown,
            textShadow: isOurs ? `0 0 ${(24 * landed).toFixed(1)}px ${rgba(C.tg, 0.6 * landed)}` : undefined,
          }}
        >
          {value.toFixed(2)}
        </div>
      </>
    );
  };

  return (
    <Canvas>
      <AbsoluteFill style={{ scale: `${drift}`, opacity: 1 - exitP }}>
        {/* title */}
        <div style={{ position: "absolute", left: X0, top: 188, ...rise(titleP, 16) }}>
          <div style={{ ...sans(36, 600, C.ink100, -0.02), display: "flex", alignItems: "center" }}>
            October alerts scored
            <Gte size={36} />
            0.5 by the bank
          </div>
        </div>
        <div style={{ position: "absolute", left: X0, top: 246, ...mono(17, C.ink400), ...rise(subP, 10) }}>
          hold-out month · never seen in training · n = <span style={{ color: C.ink200 }}>5,335</span> alerts
        </div>

        {/* chance marker */}
        <svg width={1920} height={1080} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: trackP * 0.9 }}>
          <line
            x1={X0 + TRACK_W * 0.5}
            x2={X0 + TRACK_W * 0.5}
            y1={BANK_Y - 18}
            y2={lerp(BANK_Y - 18, OURS_Y + BAR_H + 16, trackP)}
            stroke={C.ink500}
            strokeWidth={1.2}
            strokeDasharray="4 6"
          />
        </svg>
        <div style={{ position: "absolute", left: X0 + TRACK_W * 0.5 + 12, top: BANK_Y - 42, ...mono(14, C.ink400), ...rise(trackP, 6) }}>0.50 = chance</div>

        {/* bank */}
        <div style={{ position: "absolute", left: X0, top: BANK_Y - 46, ...sans(24, 500, mix(C.ink200, C.ink300, bankRecede), -0.01), ...rise(bankLabelP, 10) }}>
          The bank’s risk score
        </div>
        {bar(BANK_Y, bankV, trackP, "bank", lerp(1, 0.7, bankRecede))}
        <div style={{ position: "absolute", left: X0, top: BANK_Y + BAR_H + 18, ...sans(21, 400, C.ink300, -0.005), ...rise(bankCapP, 8) }}>
          ranks a real fraud above a false alarm <span style={{ color: C.ink100, fontWeight: 600 }}>60 times in 100</span>
        </div>

        {/* FraudLens */}
        <div style={{ position: "absolute", left: X0, top: OURS_Y - 46, display: "flex", alignItems: "center", gap: 12, ...rise(oursLabelP, 10) }}>
          <div style={{ width: 9, height: 9, borderRadius: 9, background: C.tg, boxShadow: `0 0 12px ${rgba(C.tg, 0.8)}` }} />
          <span style={sans(24, 600, C.ink100, -0.01)}>FraudLens transaction model</span>
        </div>
        {bar(OURS_Y, oursV, oursTrackP, "ours", 1)}
        <div style={{ position: "absolute", left: X0, top: OURS_Y + BAR_H + 18, ...sans(21, 400, C.ink300, -0.005), ...rise(oursCapP, 8) }}>
          <span style={{ color: C.tg300, fontWeight: 600 }}>93 times in 100</span>
        </div>

        {/* footnote */}
        <div style={{ position: "absolute", left: X0, right: X0, top: 858, height: 1, background: C.ink700, opacity: footP, transformOrigin: "0 0", scale: `${footP} 1` }} />
        <div style={{ position: "absolute", left: X0, top: 878, ...mono(16, C.ink400), ...rise(footP, 8) }}>
          All October transactions: bank score AUC <span style={{ color: C.ink200 }}>0.866</span> · FraudLens <span style={{ color: C.ink200 }}>0.973</span> · trained only on the bank’s 5,565 closed cases
        </div>
      </AbsoluteFill>
    </Canvas>
  );
};

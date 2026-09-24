import React from "react";
import { AbsoluteFill, interpolate, random, useCurrentFrame, useVideoConfig } from "remotion";
import { LensMarkAnimated, MARK, markToPx } from "../brand/LensMarkAnimated";
import { Canvas } from "../mg/Canvas";
import { EASE, EASE_IN, EASE_IO, breathe, clamp01, lerp, mix, rgba, rise, tween } from "../mg/anim";
import { BeatProps, makeTimeline } from "../mg/beats";
import { CardGlyph, CaseGlyph, CheckGlyph, PhoneGlyph } from "../mg/glyphs";
import { DrawPath, Packet, arc, cycle } from "../mg/paths";
import { Kicker, MaskRise, mono, sans } from "../mg/type";
import { C, FONT } from "../theme";

// Cold open. Line 1: a live stream of transactions, high-score alerts lift out of it and most are cleared as false
// alarms. Line 2: the one that is left opens up a graph: other cards, a shared device, closed cases. Line 3: the graph
// collapses into the FraudLens mark and the lockup lands.

export const COLD_OPEN_DEFAULT = { beats: [24, 282, 578], duration: 913 };

// ---------------------------------------------------------------- cues (frames into each narration line)
const CUE = {
  pops: [40, 56, 72, 88, 104], // "...raises thousands of alerts"
  clears: [146, 162, 178, 194], // "...most of the high-scoring ones are false alarms"
  line: 198,
  // line 2
  exitCleared: -14,
  toCentre: 4,
  toGraph: 98,
  edgeHub: 104,
  hubIn: 112,
  cardEdges: [116, 122, 128], // "on other cards"
  hubLit: 154, // "on shared devices"
  caseEdges: [202, 208, 214], // "in cases the bank already closed"
  // line 3
  converge: -22, // lasts 32 frames; the mark is whole by ~+10
  wordmark: 16, // "FraudLens"
  kicker: 64, // "a team of AI investigators"
  tigergraph: 176, // "...every case on TigerGraph"
  tagline: 194, // "and proves every claim it makes"
  proves: 218,
};

// ---------------------------------------------------------------- stream
const ROW_H = 34;
const COL_X = [150, 718, 1286];
const ROW_W = 486;
const SPEED = 0.8; // px per frame
const COL_PHASE = [0, 11, 23];

type Row = { id: string; card: string; amt: string; ch: string; score: string; hot: boolean };

const rowData = (col: number, i: number): Row => {
  const r = (k: string) => random(`co-${col}-${i}-${k}`);
  const seq = 3514948 + (i * 3 + col) * 6 + Math.floor(r("id") * 6);
  const cust = Math.floor(r("c") * 13553) + 1;
  const amt = 5 + 895 * Math.pow(r("a"), 2.6);
  const online = r("ch") < 0.64;
  const s = Math.max(0.01, Math.min(0.99, Math.pow(r("s"), 3.4)));
  return {
    id: String(seq),
    card: `C${String(cust).padStart(5, "0")}-K${1 + Math.floor(r("k") * 1.4)}`,
    amt: `$${amt.toFixed(2)}`,
    ch: online ? "online" : "in-person",
    score: s.toFixed(2),
    hot: s >= 0.85,
  };
};

const rowY = (col: number, i: number, frame: number) => i * ROW_H + COL_PHASE[col] - SPEED * frame;

// ---------------------------------------------------------------- alerts
// Illustrative alerts (the transaction id comes from the stream row each one lifts out of).
type Alert = { card: string; amt: string; risk: string; col: number; srcY: number; slot: [number, number] };
const ALERTS: Alert[] = [
  { card: "C01527-K1", amt: "$150.15", risk: "0.94", col: 0, srcY: 742, slot: [560, 322] },
  { card: "C04591-K2", amt: "$74.15", risk: "0.97", col: 2, srcY: 806, slot: [960, 294] },
  { card: "C01159-K1", amt: "$300.05", risk: "0.95", col: 1, srcY: 776, slot: [1360, 330] },
  { card: "C11928-K1", amt: "$52.07", risk: "0.96", col: 0, srcY: 838, slot: [752, 520] },
  { card: "C07219-K2", amt: "$150.04", risk: "0.95", col: 2, srcY: 760, slot: [1168, 506] },
];
const KEEP = 4; // the alert that is not a false alarm
const CLEAR_ORDER = [0, 2, 3, 1];
const CARD_W = 340;
const CARD_H = 132;

// ---------------------------------------------------------------- graph
const CENTRE = { x: 960, y: 540 };
const G_CARD = { x: 552, y: 540 };
const G_SCALE = 0.9;
const HUB = { x: 1010, y: 540 };
const HEX_R = 58;
const FAN_R = 360;
const polar = (deg: number) => ({ x: HUB.x + FAN_R * Math.cos((deg * Math.PI) / 180), y: HUB.y + FAN_R * Math.sin((deg * Math.PI) / 180) });
const OTHER = [
  { id: "C01289-K1", ...polar(-66) },
  { id: "C01996-K2", ...polar(-40) },
  { id: "C02910-K1", ...polar(-14) },
];
const CASES = [
  { id: "CC-2971", ...polar(14) },
  { id: "CC-2985", ...polar(40) },
  { id: "CC-3035", ...polar(66) },
];
const NODE_R = 27;
const CASE_S = 52;

// ---------------------------------------------------------------- lockup
const MARK_SIZE = 164;
const MARK_LEFT = 960 - MARK_SIZE / 2;
const MARK_TOP = 300;
const px = (p: { x: number; y: number }) => markToPx(MARK_SIZE, MARK_LEFT, MARK_TOP, p);
const DOT_TOP = px(MARK.dotTop);
const DOT_LEFT = px(MARK.dotLeft);
const DOT_RIGHT = px(MARK.dotRight);
const RING_C = px(MARK.ringC);
const K = MARK_SIZE / 32;

/** Hexagon (t=0) to circle (t=1) as six cubic segments, so the shape morphs without any re-parameterisation. */
const hexToCircle = (cx: number, cy: number, r: number, t: number) => {
  const k = (4 / 3) * Math.tan(Math.PI / 12);
  let d = "";
  for (let j = 0; j < 6; j++) {
    const a0 = (j * Math.PI) / 3;
    const a1 = ((j + 1) * Math.PI) / 3;
    const p0 = { x: Math.cos(a0), y: Math.sin(a0) };
    const p3 = { x: Math.cos(a1), y: Math.sin(a1) };
    const h1 = { x: p0.x + (p3.x - p0.x) / 3, y: p0.y + (p3.y - p0.y) / 3 };
    const h2 = { x: p0.x + ((p3.x - p0.x) * 2) / 3, y: p0.y + ((p3.y - p0.y) * 2) / 3 };
    const c1 = { x: p0.x - k * Math.sin(a0), y: p0.y + k * Math.cos(a0) };
    const c2 = { x: p3.x + k * Math.sin(a1), y: p3.y - k * Math.cos(a1) };
    const q = (a: { x: number; y: number }, b: { x: number; y: number }) => `${(cx + r * lerp(a.x, b.x, t)).toFixed(2)} ${(cy + r * lerp(a.y, b.y, t)).toFixed(2)}`;
    if (j === 0) d += `M ${q(p0, p0)} `;
    d += `C ${q(h1, c1)}, ${q(h2, c2)}, ${q(p3, p3)} `;
  }
  return d + "Z";
};

export const ColdOpen: React.FC<BeatProps> = ({ beats }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const T = makeTimeline(beats, D, COLD_OPEN_DEFAULT);
  const L1 = (f: number) => T.at(0, f);
  const L2 = (f: number) => T.at(1, f);
  const L3 = (f: number) => T.at(2, f);

  // ------------------------------------------------ global phases
  const exitP = tween(frame, D - 14, 14, EASE_IN);
  const camera = interpolate(frame, [0, D], [1, 1.035]);
  const streamIn = tween(frame, 0, 24);
  const streamDim = lerp(1, 0.7, tween(frame, L1(CUE.clears[0] - 6), 50, EASE_IO)) * lerp(1, 0.34, tween(frame, L2(-10), 44, EASE_IO));
  const streamBlur = 3 * tween(frame, L2(-6), 50, EASE_IO);
  const streamOut = 1 - tween(frame, L3(-30), 28, EASE_IO);
  const converge = (delay: number, dur = 30) => tween(frame, L3(CUE.converge + delay), dur, EASE_IO);
  const graphFade = 1 - tween(frame, L3(CUE.converge), 12, EASE_IO); // labels, edges, pulses leave first

  // ------------------------------------------------ alert cards
  const popAt = (k: number) => L1(CUE.pops[k]);
  const clearAt = (k: number) => {
    const idx = CLEAR_ORDER.indexOf(k);
    return idx < 0 ? 1e6 : L1(CUE.clears[idx]);
  };
  // the stream row each alert lifts out of (never two alerts on one row, whatever the beats are)
  const srcRows: number[] = [];
  ALERTS.forEach((a, k) => {
    let r = Math.round((a.srcY - COL_PHASE[a.col] + SPEED * popAt(k)) / ROW_H);
    while (ALERTS.some((b, j) => j < k && b.col === a.col && Math.abs(srcRows[j] - r) < 2)) r += 2;
    srcRows.push(r);
  });
  const srcRow = (k: number) => srcRows[k];
  const overrides = new Map<string, number>(ALERTS.map((a, k) => [`${a.col}:${srcRow(k)}`, k]));
  // an alert keeps the transaction id of the stream row it lifts out of, so the ids stay in sequence
  const alertId = (k: number) => rowData(ALERTS[k].col, srcRow(k)).id;

  // ------------------------------------------------ stream rows
  const rowEl = (key: string, col: number, y: number, d: Row, lit: number) => (
    <div
      key={key}
      style={{
        position: "absolute",
        left: COL_X[col] - 10,
        top: y,
        width: ROW_W + 20,
        height: ROW_H - 6,
        paddingLeft: 10,
        display: "flex",
        alignItems: "center",
        borderRadius: 6,
        background: lit > 0 ? rgba(C.tg, 0.12 * lit) : undefined,
        boxShadow: lit > 0 ? `inset 0 0 0 1px ${rgba(C.tg, 0.55 * lit)}, 0 0 24px ${rgba(C.tg, 0.18 * lit)}` : undefined,
        ...mono(15, lit > 0 ? C.tg300 : C.ink400),
      }}
    >
      <span style={{ width: 80 }}>{d.id}</span>
      <span style={{ width: 112 }}>{d.card}</span>
      <span style={{ width: 84, textAlign: "right", paddingRight: 18 }}>{d.amt}</span>
      <span style={{ width: 100 }}>{d.ch}</span>
      <span style={{ color: d.hot ? (lit > 0 ? C.tg : rgba(C.tg, 0.8)) : undefined }}>score {d.score}</span>
    </div>
  );
  const alertRow = (k: number): Row => ({ id: alertId(k), card: ALERTS[k].card, amt: ALERTS[k].amt, ch: "online", score: ALERTS[k].risk, hot: true });
  const rows: React.ReactNode[] = [];
  for (let col = 0; col < 3; col++) {
    const i0 = Math.floor((SPEED * frame - COL_PHASE[col]) / ROW_H) - 1;
    for (let i = i0; i < i0 + Math.ceil(1080 / ROW_H) + 3; i++) {
      const y = rowY(col, i, frame);
      if (y < -ROW_H || y > 1080) continue;
      const k = overrides.get(`${col}:${i}`);
      rows.push(rowEl(`${col}:${i}`, col, y, k === undefined ? rowData(col, i) : alertRow(k), 0));
    }
  }
  // the row an alert lifts out of lights up at full strength, above the dimmed stream
  const litRows = ALERTS.map((a, k) => {
    const lit = tween(frame, popAt(k) - 8, 8) * (1 - tween(frame, popAt(k) + 12, 26));
    if (lit <= 0) return null;
    return (
      <div key={`lit${k}`} style={{ opacity: lit }}>
        {rowEl(`lit${k}`, a.col, rowY(a.col, srcRow(k), frame), alertRow(k), 1)}
      </div>
    );
  });

  // ------------------------------------------------ counter
  const countP = tween(frame, 6, 54, EASE);
  const count = Math.round(590742 * countP).toLocaleString("en-US");

  // ------------------------------------------------ the kept card's trajectory
  const slot = ALERTS[KEEP].slot;
  const toC = tween(frame, L2(CUE.toCentre), 40, EASE_IO);
  const toG = tween(frame, L2(CUE.toGraph), 30, EASE_IO);
  const hold = tween(frame, L2(CUE.toCentre + 30), Math.max(1, L2(CUE.toGraph) - L2(CUE.toCentre + 30)), (t) => t);
  const keepPos = {
    x: lerp(lerp(slot[0], CENTRE.x, toC), G_CARD.x, toG),
    y: lerp(lerp(slot[1], CENTRE.y, toC), G_CARD.y, toG),
  };
  const keepScale = lerp(lerp(1, 1.08, toC * (1 - toG) * (0.4 + 0.6 * hold)), G_SCALE, toG);

  // ------------------------------------------------ graph geometry (live)
  const cardRight = keepPos.x + (CARD_W * keepScale) / 2;
  const hubEdge = `M ${(cardRight + 12).toFixed(1)} ${HUB.y} L ${HUB.x - HEX_R - 12} ${HUB.y}`;
  const spoke = (n: { x: number; y: number }, pad: number, bow: number) => {
    const dx = n.x - HUB.x;
    const dy = n.y - HUB.y;
    const l = Math.hypot(dx, dy);
    const ux = dx / l;
    const uy = dy / l;
    return arc(HUB.x + ux * (HEX_R + 10), HUB.y + uy * (HEX_R + 10), n.x - ux * pad, n.y - uy * pad, bow);
  };
  const otherD = OTHER.map((n) => spoke(n, NODE_R + 10, -18));
  const caseD = CASES.map((n) => spoke(n, CASE_S / 2 + 12, 18));

  const hubEdgeP = tween(frame, L2(CUE.edgeHub), 24, EASE_IO);
  const hubInP = tween(frame, L2(CUE.hubIn), 18);
  const hubLitP = tween(frame, L2(CUE.hubLit), 20);
  const otherEdgeP = OTHER.map((_, j) => tween(frame, L2(CUE.cardEdges[j]), 20, EASE_IO));
  const otherPop = OTHER.map((_, j) => tween(frame, L2(CUE.cardEdges[j] + 14), 16));
  const caseEdgeP = CASES.map((_, j) => tween(frame, L2(CUE.caseEdges[j]), 20, EASE_IO));
  const casePop = CASES.map((_, j) => tween(frame, L2(CUE.caseEdges[j] + 14), 16));

  // convergence of each piece
  const cvCard = converge(2, 30);
  const cvOther = OTHER.map((_, j) => converge(j * 2, 28));
  const cvCase = CASES.map((_, j) => converge(1 + j * 2, 28));
  const cvHub = converge(4, 28);
  const handleP = tween(frame, L3(CUE.converge + 28), 14, EASE);
  const triP = tween(frame, L3(CUE.converge + 30), 16, EASE);
  const markDone = cvCard >= 1 && cvHub >= 1 && cvOther.every((v) => v >= 1) && cvCase.every((v) => v >= 1);

  // ------------------------------------------------ lockup type
  const wordP = tween(frame, L3(CUE.wordmark), 26);
  const kickP = tween(frame, L3(CUE.kicker), 22);
  const tgP = tween(frame, L3(CUE.tigergraph), 20);
  const tag1 = tween(frame, L3(CUE.tagline), 22);
  const tag2 = tween(frame, L3(CUE.tagline + 8), 22);
  const provesP = tween(frame, L3(CUE.proves), 20);
  const lockupDrift = interpolate(frame, [L3(0), D], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  // ------------------------------------------------ render helpers
  const renderCard = (k: number) => {
    const a = ALERTS[k];
    const p0 = popAt(k);
    if (frame < p0 - 1) return null;
    const fly = tween(frame, p0, 30, EASE);
    const srcX = COL_X[a.col] + ROW_W / 2;
    const srcY = a.srcY + ROW_H / 2 - 3;
    const clr = tween(frame, clearAt(k), 18);
    const isKeep = k === KEEP;
    let x = lerp(srcX, a.slot[0], fly);
    let y = lerp(srcY, a.slot[1], fly) - Math.sin(fly * Math.PI) * 26;
    let s = lerp(0.56, 1, fly) * lerp(1, 0.965, clr);
    let o = Math.min(1, tween(frame, p0, 8));
    // cleared cards leave as line 2 starts
    if (!isKeep) {
      const out = tween(frame, L2(CUE.exitCleared + CLEAR_ORDER.indexOf(k) * 3), 16, EASE_IN);
      o *= 1 - out;
      y += out * 14;
      s *= lerp(1, 0.97, out);
      if (o <= 0.001) return null;
    } else {
      x = frame >= L2(CUE.toCentre) ? keepPos.x : x;
      y = frame >= L2(CUE.toCentre) ? keepPos.y : y;
      s = frame >= L2(CUE.toCentre) ? keepScale : s;
    }
    // morph into the orange dot of the mark
    const m = isKeep ? cvCard : 0;
    if (isKeep && m > 0) {
      x = lerp(G_CARD.x, DOT_TOP.x, m);
      y = lerp(G_CARD.y, DOT_TOP.y, m) - Math.sin(m * Math.PI) * 40;
      s = G_SCALE;
    }
    if (isKeep && markDone) return null;
    const dotD = MARK.dotTop.r * 2 * K;
    const w = lerp(CARD_W * s, dotD, m);
    const h = lerp(CARD_H * s, dotD, m);
    const glowKeep = isKeep ? tween(frame, L1(CUE.clears[3] + 20), 30) * (1 - m) : 0;
    const pulse = isKeep ? 0.55 + 0.45 * breathe(frame, 70) : 0;
    const border = m > 0 ? mix(rgba(C.tg, 0.7), C.tg, m) : mix(rgba(C.tg, 0.62), rgba(C.legit, 0.5), clr);
    const bg = m > 0 ? mix(C.ink850, C.tg, clamp01((m - 0.25) / 0.6)) : mix(C.ink850, "#0C1914", clr);
    const contentO = 1 - clamp01(m * 5);
    return (
      <div
        key={`card-${k}`}
        style={{
          position: "absolute",
          left: x - w / 2,
          top: y - h / 2,
          width: w,
          height: h,
          borderRadius: lerp(14 * s, dotD / 2, m),
          border: `1px solid ${border}`,
          background: bg,
          opacity: o,
          overflow: "hidden",
          boxShadow: [
            `0 ${24 * s}px ${60 * s}px rgba(0, 0, 0, ${0.45 * (1 - m)})`,
            `0 0 ${46 * s}px ${rgba(clr > 0.5 ? C.legit : C.tg, (0.1 + 0.16 * glowKeep * pulse) * (1 - m))}`,
          ].join(", "),
        }}
      >
        <div style={{ width: CARD_W, height: CARD_H, scale: `${s}`, transformOrigin: "0 0", position: "absolute", left: 0, top: 0, opacity: contentO, padding: "18px 20px", boxSizing: "border-box" }}>
          <div style={{ position: "relative", height: 16, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ position: "relative", height: 16, flex: 1 }}>
              <div style={{ position: "absolute", left: 0, top: 0, display: "flex", alignItems: "center", gap: 9, opacity: 1 - clr, translate: `0px ${-6 * clr}px` }}>
                <div style={{ width: 8, height: 8, borderRadius: 4, background: C.tg, boxShadow: `0 0 10px ${rgba(C.tg, 0.8)}` }} />
                <Kicker size={13} color={C.tg} track={0.16} style={{ fontWeight: 600 }}>
                  Alert
                </Kicker>
              </div>
              <div style={{ position: "absolute", left: -3, top: -2, display: "flex", alignItems: "center", gap: 6, opacity: clr, translate: `0px ${6 * (1 - clr)}px` }}>
                <CheckGlyph size={18} progress={tween(frame, clearAt(k) + 4, 14)} />
                <Kicker size={13} color={C.legit} track={0.14} style={{ fontWeight: 600 }}>
                  Cleared — false alarm
                </Kicker>
              </div>
            </div>
            <span style={mono(13, C.ink400)}>{alertId(k)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 14 }}>
            <span style={{ ...mono(14, C.ink400, 500), letterSpacing: "0.14em" }}>RISK</span>
            <span style={{ ...mono(38, mix(C.tg, C.ink400, clr), 600), letterSpacing: "-0.02em", lineHeight: "40px" }}>{a.risk}</span>
          </div>
          <div style={{ ...mono(15, clr > 0 ? mix(C.ink300, C.ink400, clr) : C.ink300), marginTop: 8 }}>
            {a.amt} · online · {a.card}
          </div>
        </div>
      </div>
    );
  };

  // hub (device) geometry through the morph
  const hubC = { x: lerp(HUB.x, RING_C.x, cvHub), y: lerp(HUB.y, RING_C.y, cvHub) - Math.sin(cvHub * Math.PI) * 30 };
  const hubR = lerp(HEX_R, MARK.ringR * K, cvHub);
  const hubPath = hexToCircle(hubC.x, hubC.y, hubR, cvHub);
  const hubStroke = cvHub > 0 ? mix(C.fraud, C.tg, cvHub) : mix(C.ink500, C.fraud, hubLitP);
  const hubWidth = lerp(lerp(1.5, 2, hubLitP), MARK.ringW * K, cvHub);
  const hubFill = mix(mix(rgba(C.ink850, 0.95), "rgba(58, 23, 22, 0.92)", hubLitP), "rgba(0,0,0,0)", clamp01(cvHub * 2.5));

  const otherPos = (j: number) => {
    const t = cvOther[j];
    return { x: lerp(OTHER[j].x, DOT_LEFT.x, t), y: lerp(OTHER[j].y, DOT_LEFT.y, t) - Math.sin(t * Math.PI) * 24, t };
  };
  const casePos = (j: number) => {
    const t = cvCase[j];
    return { x: lerp(CASES[j].x, DOT_RIGHT.x, t), y: lerp(CASES[j].y, DOT_RIGHT.y, t) + Math.sin(t * Math.PI) * 24, t };
  };

  const lineP = tween(frame, L1(CUE.line), 22);
  const lineOut = tween(frame, L2(CUE.exitCleared), 14, EASE_IN);

  return (
    <Canvas glow={1 + 0.5 * tween(frame, L3(0), 40)}>
      <AbsoluteFill style={{ scale: `${camera}` }}>
      {/* live stream */}
      <AbsoluteFill
        style={{
          opacity: streamIn * streamDim * streamOut * (1 - exitP) * 0.36,
          filter: streamBlur > 0.05 ? `blur(${streamBlur.toFixed(2)}px)` : undefined,
          maskImage: "linear-gradient(to bottom, transparent 0%, #000 22%, #000 80%, transparent 100%)",
          WebkitMaskImage: "linear-gradient(to bottom, transparent 0%, #000 22%, #000 80%, transparent 100%)",
        }}
      >
        {rows}
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: (1 - exitP) * streamOut }}>{litRows}</AbsoluteFill>

      <AbsoluteFill style={{ opacity: 1 - exitP }}>
        {/* counter */}
        <div
          style={{
            position: "absolute",
            left: 120,
            top: 92,
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "9px 18px 9px 16px",
            borderRadius: 999,
            background: "rgba(10, 13, 18, 0.94)",
            border: `1px solid ${C.ink700}`,
            boxShadow: "0 10px 30px rgba(0, 0, 0, 0.45)",
            ...rise(tween(frame, 4, 24), 10),
            opacity: tween(frame, 4, 24) * (1 - tween(frame, L3(-30), 20)),
          }}
        >
          <div style={{ width: 8, height: 8, borderRadius: 4, background: C.tg, opacity: 0.55 + 0.45 * breathe(frame, 48), boxShadow: `0 0 12px ${rgba(C.tg, 0.7)}` }} />
          <span style={{ ...mono(16, C.ink100, 500), fontVariantNumeric: "tabular-nums", minWidth: 70 }}>{count}</span>
          <Kicker size={14} color={C.ink300} track={0.16}>
            transactions · Jul–Dec 2016
          </Kicker>
        </div>

        {/* the one line of type in beat 1 */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 676,
            display: "flex",
            justifyContent: "center",
            opacity: lineP * (1 - lineOut),
          }}
        >
          <div style={{ position: "absolute", top: -40, width: 1100, height: 150, background: "radial-gradient(ellipse 50% 50% at 50% 50%, rgba(7, 9, 13, 0.92), transparent 100%)" }} />
          <div style={{ ...sans(44, 500, C.ink100, -0.02), position: "relative", ...rise(lineP, 18, 6) }}>
            Most high-score alerts are <span style={{ color: C.legit }}>false alarms.</span>
          </div>
        </div>

        {/* graph: edges */}
        <svg width={1920} height={1080} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: graphFade }}>
          <DrawPath d={hubEdge} progress={hubEdgeP} stroke={mix(rgba(C.ink300, 0.45), rgba(C.fraud, 0.55), hubLitP)} width={1.6} head={C.tg300} />
          {OTHER.map((n, j) => (
            <DrawPath key={n.id} d={otherD[j]} progress={otherEdgeP[j]} stroke={rgba(C.fraud, 0.5)} width={1.5} head={C.fraud} />
          ))}
          {CASES.map((n, j) => (
            <DrawPath key={n.id} d={caseD[j]} progress={caseEdgeP[j]} stroke={rgba(C.agent.precedent, 0.5)} width={1.5} head={C.agent.precedent} />
          ))}
          {/* slow packets once the picture is complete */}
          {hubEdgeP >= 1
            ? [0, 1].map((q) => <Packet key={`hp${q}`} d={hubEdge} t={cycle(frame, L2(CUE.edgeHub + 26), 70, 40, q * 35)} color={C.tg300} r={2.6} />)
            : null}
          {OTHER.map((n, j) =>
            otherPop[j] >= 1 ? <Packet key={`op${n.id}`} d={otherD[j]} t={cycle(frame, L2(CUE.cardEdges[j] + 30), 64, 34, j * 17)} color={C.fraud} r={2.4} /> : null,
          )}
          {CASES.map((n, j) =>
            casePop[j] >= 1 ? <Packet key={`cp${n.id}`} d={caseD[j]} t={cycle(frame, L2(CUE.caseEdges[j] + 30), 64, 34, j * 17)} color={C.agent.precedent} r={2.4} /> : null,
          )}
        </svg>

        {/* graph: nodes (they survive the fade and fly into the mark) */}
        <svg width={1920} height={1080} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {/* pulse rings on the other cards */}
          {OTHER.map((n, j) =>
            [0, 1].map((q) => {
              const start = L2(CUE.cardEdges[j] + 30);
              if (frame < start) return null;
              const ph = ((frame - start + q * 26) % 52) / 52;
              return (
                <circle key={`pr${j}${q}`} cx={n.x} cy={n.y} r={NODE_R + 26 * ph} fill="none" stroke={C.fraud} strokeWidth={1.4} opacity={0.42 * (1 - ph) * otherPop[j] * graphFade} />
              );
            }),
          )}
          {/* hub: hexagon that becomes the lens ring */}
          {hubInP > 0 && !markDone ? (
            <path
              d={hubPath}
              fill={hubFill}
              stroke={hubStroke}
              strokeWidth={hubWidth}
              opacity={hubInP}
              style={{ filter: hubLitP > 0 && cvHub < 1 ? `drop-shadow(0 0 ${18 * hubLitP}px ${rgba(C.fraud, 0.45 * (1 - cvHub))})` : undefined }}
            />
          ) : null}
          {OTHER.map((n, j) => {
            const p = otherPos(j);
            if (otherPop[j] <= 0 || markDone) return null;
            const r = lerp(NODE_R * lerp(0.6, 1, otherPop[j]), MARK.dotLeft.r * K, p.t);
            return (
              <circle
                key={n.id}
                cx={p.x}
                cy={p.y}
                r={r}
                fill={mix("rgba(58, 23, 22, 0.95)", C.ink100, clamp01(p.t * 1.6))}
                stroke={C.fraud}
                strokeOpacity={1 - clamp01(p.t * 2)}
                strokeWidth={2}
                opacity={otherPop[j]}
              />
            );
          })}
          {CASES.map((n, j) => {
            const p = casePos(j);
            if (casePop[j] <= 0 || markDone) return null;
            const s = lerp(CASE_S * lerp(0.6, 1, casePop[j]), MARK.dotRight.r * 2 * K, p.t);
            return (
              <rect
                key={n.id}
                x={p.x - s / 2}
                y={p.y - s / 2}
                width={s}
                height={s}
                rx={lerp(13, s / 2, p.t)}
                fill={mix(rgba(C.agent.precedent, 0.13), C.ink100, clamp01(p.t * 1.6))}
                stroke={C.agent.precedent}
                strokeOpacity={1 - clamp01(p.t * 2)}
                strokeWidth={2}
                opacity={casePop[j]}
              />
            );
          })}
        </svg>

        {/* graph: glyphs + labels */}
        <AbsoluteFill style={{ opacity: graphFade }}>
          {hubInP > 0 ? (
            <div style={{ position: "absolute", left: HUB.x - 17, top: HUB.y - 17, opacity: hubInP }}>
              <PhoneGlyph size={34} color={mix(C.ink400, "#F6A39C", hubLitP)} stroke={1.5} />
            </div>
          ) : null}
          <div style={{ position: "absolute", right: 1920 - (HUB.x - HEX_R - 18), top: HUB.y + 22, textAlign: "right", ...rise(tween(frame, L2(CUE.hubLit + 6), 20), 10) }}>
            <div style={{ ...mono(15, C.fraud, 500) }}>shared device</div>
            <div style={{ ...mono(20, C.ink100, 500), marginTop: 6 }}>SM-G935F</div>
            <div style={{ ...mono(15, C.ink300), marginTop: 4 }}>anonymous proxy</div>
          </div>
          {OTHER.map((n, j) => (
            <React.Fragment key={n.id}>
              <div style={{ position: "absolute", left: n.x - 12, top: n.y - 12, opacity: otherPop[j] }}>
                <CardGlyph size={24} color="#F6A39C" stroke={1.6} />
              </div>
              <div style={{ position: "absolute", left: n.x + NODE_R + 14, top: n.y - 10, ...mono(15, C.ink200), ...rise(tween(frame, L2(CUE.cardEdges[j] + 20), 16), 8) }}>{n.id}</div>
            </React.Fragment>
          ))}
          <div style={{ position: "absolute", left: OTHER[0].x - 120, width: 240, textAlign: "center", top: OTHER[0].y - NODE_R - 44, ...mono(15, C.fraud, 500), ...rise(tween(frame, L2(CUE.cardEdges[0] + 24), 18), 10) }}>
            other cards
          </div>
          {CASES.map((n, j) => (
            <React.Fragment key={n.id}>
              <div style={{ position: "absolute", left: n.x - 12, top: n.y - 12, opacity: casePop[j] }}>
                <CaseGlyph size={24} color="#F7A6CE" stroke={1.6} />
              </div>
              <div style={{ position: "absolute", left: n.x + CASE_S / 2 + 14, top: n.y - 10, ...mono(15, C.ink200), ...rise(tween(frame, L2(CUE.caseEdges[j] + 20), 16), 8) }}>{n.id}</div>
            </React.Fragment>
          ))}
          <div style={{ position: "absolute", left: CASES[2].x - 120, width: 240, textAlign: "center", top: CASES[2].y + CASE_S / 2 + 22, ...mono(15, C.agent.precedent, 500), ...rise(tween(frame, L2(CUE.caseEdges[0] + 24), 18), 10) }}>
            closed cases
          </div>
        </AbsoluteFill>

        {/* alert cards */}
        {ALERTS.map((_, k) => renderCard(k))}

        {/* lockup */}
        <AbsoluteFill style={{ scale: `${1 + 0.018 * lockupDrift}` }}>
          {cvHub > 0 ? (
            <div style={{ position: "absolute", left: MARK_LEFT, top: MARK_TOP }}>
              <LensMarkAnimated
                size={MARK_SIZE}
                ring={markDone ? 1 : 0}
                handle={handleP}
                tri={triP}
                dots={markDone ? [1, 1, 1] : [0, 0, 0]}
                glow={tween(frame, L3(CUE.converge + 30), 30)}
              />
            </div>
          ) : null}
          <div style={{ position: "absolute", left: 0, right: 0, top: 496, display: "flex", justifyContent: "center", ...rise(kickP, 12) }}>
            <Kicker size={17} color={C.ink300} track={0.22}>
              An agentic fraud investigator on <span style={{ color: mix(C.ink300, C.tg, tgP) }}>TigerGraph</span>
            </Kicker>
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 528, display: "flex", justifyContent: "center" }}>
            <MaskRise p={wordP}>
              <span style={{ fontFamily: FONT.sans, fontWeight: 700, fontSize: 128, letterSpacing: "-0.045em", lineHeight: "140px", color: C.ink100 }}>FraudLens</span>
            </MaskRise>
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 694, display: "flex", justifyContent: "center", gap: 12, ...sans(40, 500, C.ink100, -0.015) }}>
            <span style={rise(tag1, 14, 4)}>The model predicts.</span>
            <span
              style={{
                ...rise(tag2, 14, 4),
                color: mix(C.ink500, C.tg, provesP),
                textShadow: provesP > 0 ? `0 0 ${28 * provesP}px ${rgba(C.tg, 0.35 * provesP)}` : undefined,
              }}
            >
              TigerGraph proves.
            </span>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
      </AbsoluteFill>
    </Canvas>
  );
};

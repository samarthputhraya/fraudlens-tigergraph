import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Canvas } from "../mg/Canvas";
import { EASE, EASE_IN, EASE_IO, lerp, mix, rgba, rise, tween } from "../mg/anim";
import { BeatProps, makeTimeline } from "../mg/beats";
import { AnalystGlyph, BubbleGlyph, GaugeGlyph, GraphDbGlyph, LockGlyph } from "../mg/glyphs";
import { DrawPath, Packet, cycle, hCurve } from "../mg/paths";
import { Kicker, mono, sans } from "../mg/type";
import { C } from "../theme";

// Architecture. Line 1: triggers -> lead investigator -> four specialists. Line 2: every question goes through the
// official TigerGraph MCP server (read-only allowlist of 18 installed queries) to TigerGraph Savanna. Line 3: a code row
// (model, policy, compliance, writer, case memory) that writes back to the graph; code owns the decision.

export const ARCHITECTURE_DEFAULT = { beats: [14, 328, 647], duration: 988 };

const CUE = {
  // line 1 (frames into the line)
  agentsLabel: 18,
  chips: [50, 88, 134], // "a model score" / "a customer complaint" / "an analyst's hunch"
  chipEdges: 162,
  lead: 190, // "A lead investigator"
  leadEdges: 222,
  specs: [234, 242, 250, 258], // "sends four specialists after it"
  // line 2
  specEdges: 0,
  mcp: 20,
  mcpEdge: 36,
  sav: 46, // "goes to TigerGraph"
  savLabels: 70,
  tagOfficial: 108, // "through the official MCP server"
  tagReadOnly: 176, // "read-only"
  tagQueries: 230, // "limited to eighteen installed queries"
  // line 3
  codeLabel: 0,
  evidence: 2,
  model: 16, // "A model trained on the bank's own closed cases"
  policy: 40,
  compliance: 58,
  writer: 76,
  memory: 94,
  writeBack: 108,
  highlight: 160, // "Code, not the language model"
  pulses: [222, 260, 284], // "the policy", "the numbers", "and the approvals"
};

// ---------------------------------------------------------------- layout (1920x1080, safe area 120..1800)
const MID = 382;
const X = {
  trig: { x: 120, w: 232 },
  lead: { x: 412, w: 300 },
  spec: { x: 808, w: 320 },
  mcp: { x: 1206, w: 292 },
  sav: { x: 1556, w: 244 },
};
const CHIP_H = 58;
const CHIP_Y = [MID - 84 - CHIP_H / 2, MID - CHIP_H / 2, MID + 84 - CHIP_H / 2];
const LEAD = { y: MID - 68, h: 136 };
const SPEC_H = 76;
const SPEC_GAP = 20;
const SPEC_Y = [0, 1, 2, 3].map((i) => MID - (4 * SPEC_H + 3 * SPEC_GAP) / 2 + i * (SPEC_H + SPEC_GAP));
const MCP = { y: MID - 110, h: 220 };
const SAV = { y: MID - 184, h: 368 };
const ROW = { y: 772, h: 98, w: 304, gap: 40 };
const ROW_X = [0, 1, 2, 3, 4].map((i) => 120 + i * (ROW.w + ROW.gap));

const SPECS = [
  { name: "Transaction", color: C.agent.transaction },
  { name: "Identity & Device", color: C.agent.identity },
  { name: "Network & Ring", color: C.agent.network },
  { name: "Precedent & Memory", color: C.agent.precedent },
];
const CHIPS = [
  { name: "Model score", Glyph: GaugeGlyph },
  { name: "Customer report", Glyph: BubbleGlyph },
  { name: "Analyst request", Glyph: AnalystGlyph },
];
const CODE_ROW = [
  { title: "Transaction model", sub: "LightGBM on closed cases", badge: "AUC 0.97", code: true },
  { title: "Policy engine", sub: "R1–R10 · §3a · §6 · routes", badge: "", code: true },
  { title: "Compliance reviewer", sub: "checks it against policy", badge: "Gemini", code: false },
  { title: "Writer", sub: "summary + SAR", badge: "Gemini", code: false },
  { title: "Case memory", sub: "cases + embeddings", badge: "", code: false },
];

// ---------------------------------------------------------------- connectors
const chipD = CHIP_Y.map((y) => hCurve(X.trig.x + X.trig.w + 6, y + CHIP_H / 2, X.lead.x - 6, MID, 0.55));
const leadD = SPEC_Y.map((y) => hCurve(X.lead.x + X.lead.w + 6, MID, X.spec.x - 6, y + SPEC_H / 2, 0.55));
const MCP_PORTS = [-27, -9, 9, 27];
const specD = SPEC_Y.map((y, i) => hCurve(X.spec.x + X.spec.w + 6, y + SPEC_H / 2, X.mcp.x - 6, MID + MCP_PORTS[i], 0.55));
const mcpD = `M ${X.mcp.x + X.mcp.w + 6} ${MID} L ${X.sav.x - 6} ${MID}`;
const mcpBackD = `M ${X.sav.x - 6} ${MID} L ${X.mcp.x + X.mcp.w + 6} ${MID}`;
const specBackD = SPEC_Y.map((y, i) => hCurve(X.mcp.x - 6, MID + MCP_PORTS[i], X.spec.x + X.spec.w + 6, y + SPEC_H / 2, 0.55));
const EV_X = 384;
const evidenceD = `M ${X.lead.x + 150} ${LEAD.y + LEAD.h + 6} V ${632} Q ${X.lead.x + 150} ${652} ${X.lead.x + 130} ${652} H ${EV_X + 20} Q ${EV_X} ${652} ${EV_X} ${672} V ${ROW.y - 6}`;
const rowD = [0, 1, 2, 3].map((i) => `M ${ROW_X[i] + ROW.w + 5} ${ROW.y + ROW.h / 2} L ${ROW_X[i + 1] - 5} ${ROW.y + ROW.h / 2}`);
const WB_X0 = ROW_X[4] + ROW.w / 2 + 40;
const WB_X1 = X.sav.x + X.sav.w / 2 + 20;
const writeBackD = `M ${WB_X0} ${ROW.y - 6} C ${WB_X0} ${ROW.y - 80}, ${WB_X1} ${SAV.y + SAV.h + 90}, ${WB_X1} ${SAV.y + SAV.h + 10}`;

// ---------------------------------------------------------------- building blocks
type NodeProps = {
  x: number;
  y: number;
  w: number;
  h: number;
  p: number;
  accent?: string;
  glow?: number;
  dim?: number;
  radius?: number;
  badge?: React.ReactNode;
  style?: React.CSSProperties;
  children?: React.ReactNode;
};

const Node: React.FC<NodeProps> = ({ x, y, w, h, p, accent = C.tg, glow = 0, dim = 0, radius = 14, badge, style, children }) => {
  if (p <= 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        opacity: p * (1 - dim),
        translate: `0px ${((1 - p) * 14).toFixed(2)}px`,
        scale: `${lerp(0.97, 1, p)}`,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: radius,
          background: `linear-gradient(180deg, ${mix(C.ink800, "#1C1510", glow * 0.6)} 0%, ${C.ink850} 100%)`,
          border: `1px solid ${mix(C.ink700, rgba(accent, 0.75), glow)}`,
          boxShadow: [
            "inset 0 1px 0 rgba(255, 255, 255, 0.035)",
            "0 18px 40px rgba(0, 0, 0, 0.35)",
            glow > 0 ? `0 0 ${(44 * glow).toFixed(1)}px ${rgba(accent, 0.26 * glow)}` : "",
            glow > 0 ? `inset 0 0 ${(28 * glow).toFixed(1)}px ${rgba(accent, 0.1 * glow)}` : "",
          ]
            .filter(Boolean)
            .join(", "),
          ...style,
        }}
      />
      <div style={{ position: "relative", width: "100%", height: "100%" }}>{children}</div>
      {badge ? <div style={{ position: "absolute", right: 16, top: -12 }}>{badge}</div> : null}
    </div>
  );
};

const Badge: React.FC<{ children: React.ReactNode; color?: string; border?: string }> = ({ children, color = C.ink300, border = C.ink600 }) => (
  <div
    style={{
      ...mono(13, color, 500),
      padding: "3px 9px",
      borderRadius: 7,
      background: C.ink900,
      border: `1px solid ${border}`,
      letterSpacing: "0.02em",
    }}
  >
    {children}
  </div>
);

const Dot: React.FC<{ color: string; size?: number }> = ({ color, size = 10 }) => (
  <div style={{ width: size, height: size, borderRadius: size, background: color, boxShadow: `0 0 12px ${rgba(color, 0.7)}`, flexShrink: 0 }} />
);

const SectionLabel: React.FC<{ x: number; y: number; p: number; hl?: number; children: React.ReactNode }> = ({ x, y, p, hl = 0, children }) => (
  <div style={{ position: "absolute", left: x, top: y, display: "flex", alignItems: "center", gap: 12, ...rise(p, 10) }}>
    <div style={{ width: 22 * p, height: 2, borderRadius: 1, background: mix(C.ink500, C.tg, hl) }} />
    <Kicker size={15} color={mix(C.ink300, C.tg, hl)} track={0.22}>
      {children}
    </Kicker>
  </div>
);

export const Architecture: React.FC<BeatProps> = ({ beats }) => {
  const frame = useCurrentFrame();
  const { durationInFrames: D } = useVideoConfig();
  const T = makeTimeline(beats, D, ARCHITECTURE_DEFAULT);
  const L1 = (f: number) => T.at(0, f);
  const L2 = (f: number) => T.at(1, f);
  const L3 = (f: number) => T.at(2, f);
  const tw = (start: number, dur = 20, e = EASE) => tween(frame, start, dur, e);

  const exitP = tween(frame, D - 14, 14, EASE_IN);
  // camera: framed on the agents while they appear, pulls back to the whole top row for the graph, then to the system
  const camA = { x: 624, y: 372, s: 1.34 };
  const camB = { x: 960, y: 380, s: 0.985 };
  const camC = { x: 960, y: 512, s: 0.978 };
  const c1 = tween(frame, L2(-24), 60, EASE_IO);
  const c2 = tween(frame, L3(-20), 56, EASE_IO);
  const drift = interpolate(frame, [0, D], [1, 1.02]);
  const camS = lerp(lerp(camA.s, camB.s, c1), camC.s, c2) * drift;
  const camX = lerp(lerp(camA.x, camB.x, c1), camC.x, c2);
  const camY = lerp(lerp(camA.y, camB.y, c1), camC.y, c2);

  // line 3 emphasis: code owns the decision
  const hl = tw(L3(CUE.highlight), 26, EASE_IO);
  const pulse = (at: number) => {
    const a = tw(L3(at), 7);
    const b = tw(L3(at) + 7, 30, EASE_IO);
    return a * (1 - b);
  };
  const llmDim = 0.5 * hl;
  const otherDim = 0.2 * hl;

  // appear progress
  const chipP = CUE.chips.map((c) => tw(L1(c), 22));
  const chipEdgeP = CHIPS.map((_, i) => tw(L1(CUE.chipEdges + i * 4), 28, EASE_IO));
  const leadP = tw(L1(CUE.lead), 22);
  const leadEdgeP = SPECS.map((_, i) => tw(L1(CUE.leadEdges + i * 4), 26, EASE_IO));
  const specP = CUE.specs.map((c) => tw(L1(c), 20));
  const specEdgeP = SPECS.map((_, i) => tw(L2(CUE.specEdges + i * 4), 30, EASE_IO));
  const mcpP = tw(L2(CUE.mcp), 22);
  const mcpEdgeP = tw(L2(CUE.mcpEdge), 18, EASE_IO);
  const savP = tw(L2(CUE.sav), 24);
  const savDraw = tw(L2(CUE.sav + 4), 44, EASE_IO);
  const savLabelP = [tw(L2(CUE.savLabels), 18), tw(L2(CUE.savLabels + 8), 18)];
  const tagP = [tw(L2(CUE.tagOfficial), 20), tw(L2(CUE.tagReadOnly), 20), tw(L2(CUE.tagQueries), 20)];
  const lockClosed = tw(L2(CUE.tagReadOnly) + 2, 12, EASE_IO);
  const codeLabelP = tw(L3(CUE.codeLabel), 20);
  const evidenceP = tw(L3(CUE.evidence), 30, EASE_IO);
  const rowStarts = [CUE.model, CUE.policy, CUE.compliance, CUE.writer, CUE.memory];
  const rowP = rowStarts.map((c) => tw(L3(c), 22));
  const rowEdgeP = [0, 1, 2, 3].map((i) => tw(L3(rowStarts[i + 1] - 10), 14, EASE_IO));
  const writeBackP = tw(L3(CUE.writeBack), 34, EASE_IO);
  const writeBackLabelP = tw(L3(CUE.writeBack + 20), 20);

  const tag17 = tagP[2];

  const connector = rgba(C.ink300, 0.34);

  // packets
  const packets: React.ReactNode[] = [];
  if (leadP >= 1) {
    CHIPS.forEach((_, i) => packets.push(<Packet key={`cp${i}`} d={chipD[i]} t={cycle(frame, L1(CUE.lead + 6), 96, 30, i * 12)} color={C.ink200} r={2.4} opacity={1 - otherDim} />));
  }
  SPECS.forEach((s, i) => {
    if (specP[i] >= 1) packets.push(<Packet key={`lp${i}`} d={leadD[i]} t={cycle(frame, L1(CUE.specs[i] + 10), 88, 28, 0)} color={s.color} r={2.6} opacity={1 - llmDim} />);
    if (specEdgeP[i] >= 1) {
      packets.push(<Packet key={`sp${i}`} d={specD[i]} t={cycle(frame, L2(CUE.specEdges + 34), 100, 30, i * 23)} color={s.color} r={2.6} opacity={1 - otherDim} />);
      if (savP >= 1) packets.push(<Packet key={`sb${i}`} d={specBackD[i]} t={cycle(frame, L2(CUE.specEdges + 34), 100, 30, i * 23 + 62)} color={C.tg300} r={2.4} opacity={1 - otherDim} />);
    }
  });
  if (savP >= 1) {
    packets.push(<Packet key="m1" d={mcpD} t={cycle(frame, L2(CUE.specEdges + 34), 100 / 4, 16, 30)} color={C.ink100} r={2.4} tail={30} opacity={1 - otherDim} />);
    packets.push(<Packet key="m2" d={mcpBackD} t={cycle(frame, L2(CUE.specEdges + 34), 100 / 4, 16, 46)} color={C.tg} r={2.4} tail={30} opacity={1 - otherDim} />);
  }
  if (evidenceP >= 1) packets.push(<Packet key="ev" d={evidenceD} t={cycle(frame, L3(CUE.evidence + 30), 110, 44, 0)} color={C.tg300} r={2.6} />);
  rowD.forEach((d, i) => {
    if (rowP[i + 1] >= 1) packets.push(<Packet key={`rp${i}`} d={d} t={cycle(frame, L3(CUE.memory + 24), 110, 12, 44 + i * 13)} color={i < 1 ? C.tg : C.ink200} r={2.4} tail={24} />);
  });
  if (writeBackP >= 1) packets.push(<Packet key="wb" d={writeBackD} t={cycle(frame, L3(CUE.writeBack + 36), 110, 36, 0)} color={C.agent.precedent} r={2.6} />);

  return (
    <Canvas>
      <AbsoluteFill
        style={{
          opacity: 1 - exitP,
          transformOrigin: "0 0",
          transform: `translate(${(960 - camX * camS).toFixed(2)}px, ${(540 - camY * camS).toFixed(2)}px) scale(${camS.toFixed(5)})`,
        }}
      >
        {/* section labels */}
        <SectionLabel x={120} y={150} p={tw(L1(CUE.agentsLabel), 22)}>
          Agents investigate
        </SectionLabel>
        <SectionLabel x={120} y={716} p={codeLabelP} hl={hl}>
          Code decides
        </SectionLabel>

        {/* connectors */}
        <svg width={1920} height={1080} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <g opacity={1 - otherDim}>
            {chipD.map((d, i) => (
              <DrawPath key={`c${i}`} d={d} progress={chipEdgeP[i]} stroke={connector} head={C.ink200} />
            ))}
          </g>
          <g opacity={1 - llmDim}>
            {leadD.map((d, i) => (
              <DrawPath key={`l${i}`} d={d} progress={leadEdgeP[i]} stroke={rgba(SPECS[i].color, 0.42)} head={SPECS[i].color} />
            ))}
          </g>
          <g opacity={1 - otherDim}>
            {specD.map((d, i) => (
              <DrawPath key={`s${i}`} d={d} progress={specEdgeP[i]} stroke={connector} head={SPECS[i].color} />
            ))}
            <DrawPath d={mcpD} progress={mcpEdgeP} stroke={rgba(C.tg, 0.5)} width={1.8} head={C.tg300} />
          </g>
          <DrawPath d={evidenceD} progress={evidenceP} stroke={rgba(C.tg300, 0.4)} dash="5 6" width={1.5} />
          {rowD.map((d, i) => (
            <DrawPath key={`r${i}`} d={d} progress={rowEdgeP[i]} stroke={i === 0 ? mix(connector, rgba(C.tg, 0.7), hl) : connector} width={1.6} />
          ))}
          <DrawPath d={writeBackD} progress={writeBackP} stroke={rgba(C.agent.precedent, 0.55)} width={1.6} head={C.agent.precedent} />
          {writeBackP > 0.96 ? (
            <path
              d={`M ${WB_X1 - 7} ${SAV.y + SAV.h + 20} L ${WB_X1} ${SAV.y + SAV.h + 10} L ${WB_X1 + 7} ${SAV.y + SAV.h + 20}`}
              fill="none"
              stroke={rgba(C.agent.precedent, 0.8)}
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={tw(L3(CUE.writeBack + 30), 8)}
            />
          ) : null}
          {packets}
        </svg>

        {/* evidence + write-back labels */}
        <div style={{ position: "absolute", left: EV_X + 24, top: 626, ...mono(14, C.ink400), ...rise(tw(L3(CUE.evidence + 18), 18), 6) }}>evidence</div>
        <div style={{ position: "absolute", right: 1920 - (WB_X0 - 14), top: 664, textAlign: "right", ...mono(15, C.agent.precedent), ...rise(writeBackLabelP, 8) }}>
          written back to the graph
        </div>

        {/* trigger chips */}
        {CHIPS.map((c, i) => (
          <Node key={c.name} x={X.trig.x} y={CHIP_Y[i]} w={X.trig.w} h={CHIP_H} p={chipP[i]} radius={CHIP_H / 2} dim={otherDim}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, height: "100%", paddingLeft: 20 }}>
              <c.Glyph size={22} color={C.ink200} />
              <span style={sans(21, 500, C.ink100)}>{c.name}</span>
            </div>
          </Node>
        ))}

        {/* lead investigator */}
        <Node
          x={X.lead.x}
          y={LEAD.y}
          w={X.lead.w}
          h={LEAD.h}
          p={leadP}
          glow={0.55 * leadP * (1 - hl)}
          dim={llmDim}
          badge={<Badge>Gemini</Badge>}
        >
          <div style={{ padding: "30px 26px 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Dot color={C.agent.lead} />
              <span style={sans(27, 600, C.ink100, -0.015)}>Lead Investigator</span>
            </div>
            <div style={{ ...mono(15, C.ink300), marginTop: 14, marginLeft: 22 }}>plans · delegates · asks</div>
          </div>
        </Node>

        {/* specialists */}
        {SPECS.map((s, i) => (
          <Node key={s.name} x={X.spec.x} y={SPEC_Y[i]} w={X.spec.w} h={SPEC_H} p={specP[i]} accent={s.color} glow={0.35 * specP[i] * (1 - hl)} dim={llmDim}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, height: "100%", paddingLeft: 24 }}>
              <Dot color={s.color} />
              <span style={sans(24, 600, C.ink100, -0.01)}>{s.name}</span>
            </div>
          </Node>
        ))}

        {/* MCP gate */}
        <Node x={X.mcp.x} y={MCP.y} w={X.mcp.w} h={MCP.h} p={mcpP} dim={otherDim} glow={0.25 * tag17 * (1 - hl)}>
          <div style={{ padding: "22px 20px 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <LockGlyph size={26} color={mix(C.ink200, C.tg300, lockClosed)} closed={lockClosed} />
              <span style={sans(25, 600, C.ink100, -0.015)}>TigerGraph MCP</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 20 }}>
              {["official tigergraph-mcp", "read-only allowlist", "18 installed GSQL queries"].map((t, i) => (
                <div
                  key={t}
                  style={{
                    ...mono(15, mix(C.ink500, C.ink100, tagP[i])),
                    padding: "6px 10px",
                    borderRadius: 8,
                    background: mix(C.ink900, "#141A23", tagP[i]),
                    border: `1px solid ${mix(C.ink800, rgba(C.tg, 0.6), tagP[i] * (1 - tw(L2([CUE.tagOfficial, CUE.tagReadOnly, CUE.tagQueries][i]) + 24, 40)))}`,
                    boxShadow: tagP[i] > 0 ? `0 0 18px ${rgba(C.tg, 0.18 * tagP[i] * (1 - tw(L2([CUE.tagOfficial, CUE.tagReadOnly, CUE.tagQueries][i]) + 24, 40)))}` : undefined,
                    opacity: lerp(0.55, 1, tagP[i]),
                  }}
                >
                  {i === 2 ? (
                    <>
                      <span style={{ color: C.tg300 }}>17</span> installed GSQL queries
                    </>
                  ) : (
                    t
                  )}
                </div>
              ))}
            </div>
          </div>
        </Node>

        {/* TigerGraph Savanna */}
        <Node x={X.sav.x} y={SAV.y} w={X.sav.w} h={SAV.h} p={savP} dim={otherDim} glow={0.5 * savP * (0.6 + 0.4 * writeBackP)} radius={18}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 26 }}>
            <GraphDbGlyph width={118} draw={savDraw} />
            <div style={{ ...sans(28, 600, C.ink100, -0.02), textAlign: "center", lineHeight: "32px", marginTop: 16 }}>
              TigerGraph
              <br />
              Savanna
            </div>
            <div style={{ width: 170, height: 1, background: C.ink700, margin: "18px 0 14px", opacity: savLabelP[0] }} />
            <div style={{ ...mono(15, C.ink300), textAlign: "center", lineHeight: "24px", ...rise(savLabelP[0], 8) }}>
              <span style={{ color: C.ink100 }}>590,742</span> transactions
              <br />
              <span style={{ color: C.ink100 }}>5,565</span> closed cases
            </div>
            <div style={{ ...mono(15, C.ink300), textAlign: "center", lineHeight: "24px", marginTop: 8, ...rise(savLabelP[1], 8) }}>
              TigerVector
              <br />
              GDBMS_ALGO · WCC
            </div>
          </div>
        </Node>

        {/* code row */}
        {CODE_ROW.map((n, i) => {
          const isHl = n.code;
          const g = isHl ? hl + 0.9 * pulse(CUE.pulses[i === 0 ? 1 : 0]) + (i === 1 ? 0.9 * pulse(CUE.pulses[2]) : 0) : 0;
          const dim = n.badge === "Gemini" ? llmDim : isHl ? 0 : otherDim;
          return (
            <Node
              key={n.title}
              x={ROW_X[i]}
              y={ROW.y}
              w={ROW.w}
              h={ROW.h}
              p={rowP[i]}
              glow={Math.min(1.4, g)}
              dim={dim}
              accent={i === 4 ? C.agent.precedent : C.tg}
              badge={n.badge ? <Badge color={i === 0 ? C.tg300 : C.ink300} border={i === 0 ? rgba(C.tg, 0.5) : C.ink600}>{n.badge}</Badge> : null}
            >
              <div style={{ padding: "22px 22px 0" }}>
                <div style={sans(24, 600, C.ink100, -0.015)}>{n.title}</div>
                <div style={{ ...mono(15, isHl ? mix(C.ink300, C.tg300, hl) : C.ink300), marginTop: 10 }}>{n.sub}</div>
              </div>
            </Node>
          );
        })}
      </AbsoluteFill>
    </Canvas>
  );
};

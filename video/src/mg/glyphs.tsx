import { evolvePath } from "@remotion/paths";
import React from "react";

// Small line icons in the product's style (1.5px strokes, round joins). All are pure functions of their props.

type G = { size?: number; color?: string; stroke?: number; style?: React.CSSProperties };

const svg = (size: number, vb: string, style: React.CSSProperties | undefined, children: React.ReactNode) => (
  <svg width={size} height={size} viewBox={vb} style={{ display: "block", overflow: "visible", ...style }}>
    {children}
  </svg>
);

/** Mobile phone. */
export const PhoneGlyph: React.FC<G> = ({ size = 40, color = "#E7EBF1", stroke = 1.6, style }) =>
  svg(
    size,
    "0 0 24 24",
    style,
    <g fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      <rect x="6.5" y="2.5" width="11" height="19" rx="2.6" />
      <path d="M10.5 5.2 H13.5" />
      <circle cx="12" cy="18.2" r="0.55" fill={color} />
    </g>,
  );

/** Payment card. */
export const CardGlyph: React.FC<G> = ({ size = 24, color = "#E7EBF1", stroke = 1.6, style }) =>
  svg(
    size,
    "0 0 24 24",
    style,
    <g fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5.5" width="18" height="13" rx="2.4" />
      <path d="M3 9.8 H21" />
      <path d="M6.5 14.8 H10" />
    </g>,
  );

/** Closed case: a document with a tick. */
export const CaseGlyph: React.FC<G> = ({ size = 24, color = "#E7EBF1", stroke = 1.6, style }) =>
  svg(
    size,
    "0 0 24 24",
    style,
    <g fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 2.8 H14.2 L19 7.6 V21.2 H6 Z" />
      <path d="M14 2.8 V7.8 H19" />
      <path d="M9 14.6 L11.3 16.8 L15.4 12.4" />
    </g>,
  );

/** Padlock; `closed` 0..1 lowers the shackle into the body. */
export const LockGlyph: React.FC<G & { closed?: number }> = ({ size = 24, color = "#E7EBF1", stroke = 1.6, closed = 1, style }) =>
  svg(
    size,
    "0 0 24 24",
    style,
    <g fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      <rect x="4.5" y="10.5" width="15" height="10.5" rx="2.4" />
      <path d="M8 10.5 V7.4 a4 4 0 0 1 8 0 V10.5" transform={`translate(0 ${(-(1 - closed) * 3.2).toFixed(2)})`} />
      <path d="M12 14.6 V16.6" />
    </g>,
  );

/** Tick that draws on with `progress`. */
export const CheckGlyph: React.FC<G & { progress?: number }> = ({ size = 16, color = "#3CC585", stroke = 2, progress = 1, style }) => {
  const d = "M4.5 12.5 L9.5 17.2 L19.5 6.8";
  const ev = evolvePath(Math.max(0.0001, Math.min(1, progress)), d);
  return svg(
    size,
    "0 0 24 24",
    style,
    <path d={d} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={ev.strokeDasharray} strokeDashoffset={ev.strokeDashoffset} opacity={progress > 0 ? 1 : 0} />,
  );
};

/** Gauge: a model score. */
export const GaugeGlyph: React.FC<G> = ({ size = 22, color = "#C3CBD7", stroke = 1.6, style }) =>
  svg(
    size,
    "0 0 24 24",
    style,
    <g fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 16.5 a8 8 0 1 1 16 0" />
      <path d="M12 16.5 L16.2 10.6" />
      <circle cx="12" cy="16.5" r="1.1" fill={color} />
    </g>,
  );

/** Speech bubble: a customer report. */
export const BubbleGlyph: React.FC<G> = ({ size = 22, color = "#C3CBD7", stroke = 1.6, style }) =>
  svg(
    size,
    "0 0 24 24",
    style,
    <g fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6.5 a2.5 2.5 0 0 1 2.5 -2.5 H17.5 a2.5 2.5 0 0 1 2.5 2.5 V13.5 a2.5 2.5 0 0 1 -2.5 2.5 H10 L6 20 V16 H6.5 a2.5 2.5 0 0 1 -2.5 -2.5 Z" />
      <path d="M8.5 8.6 H15.5" />
      <path d="M8.5 11.6 H13" />
    </g>,
  );

/** Person with a magnifier: an analyst's request. */
export const AnalystGlyph: React.FC<G> = ({ size = 22, color = "#C3CBD7", stroke = 1.6, style }) =>
  svg(
    size,
    "0 0 24 24",
    style,
    <g fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9.5" cy="8" r="3.5" />
      <path d="M3.5 20 a6 6 0 0 1 9.4 -4.9" />
      <circle cx="17" cy="15.5" r="3" />
      <path d="M19.2 17.7 L21 19.5" />
    </g>,
  );

/** Graph database: a cylinder holding a small graph. `draw` 0..1 draws it on. */
export const GraphDbGlyph: React.FC<{ width?: number; draw?: number; color?: string; ink?: string }> = ({
  width = 120,
  draw = 1,
  color = "#F58025",
  ink = "#E7EBF1",
}) => {
  const body = "M10 20 V80 A50 13 0 0 0 110 80 V20";
  const top = "M10 20 A50 13 0 0 1 110 20 A50 13 0 0 1 10 20";
  const edges = "M36 52 L60 42 L86 54 M36 52 L50 70 L74 68 L86 54 M60 42 L74 68 M50 70 L60 42";
  const nodes: [number, number, number][] = [
    [36, 52, 3.4],
    [60, 42, 4.2],
    [86, 54, 3.4],
    [50, 70, 3.2],
    [74, 68, 3.6],
  ];
  const p = (lo: number, hi: number) => Math.max(0.0001, Math.min(1, (draw - lo) / (hi - lo)));
  const e1 = evolvePath(p(0, 0.55), top);
  const e2 = evolvePath(p(0.1, 0.7), body);
  const e3 = evolvePath(p(0.45, 0.95), edges);
  return (
    <svg width={width} height={width * (100 / 120)} viewBox="0 0 120 100" style={{ display: "block", overflow: "visible" }}>
      <path d={top} fill="none" stroke={color} strokeWidth={1.8} strokeDasharray={e1.strokeDasharray} strokeDashoffset={e1.strokeDashoffset} />
      <path d={body} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeDasharray={e2.strokeDasharray} strokeDashoffset={e2.strokeDashoffset} />
      <path d={edges} fill="none" stroke={ink} strokeOpacity={0.5} strokeWidth={1.3} strokeLinejoin="round" strokeDasharray={e3.strokeDasharray} strokeDashoffset={e3.strokeDashoffset} />
      {nodes.map(([x, y, r], i) => {
        const s = Math.max(0, Math.min(1, (draw - 0.6 - i * 0.05) / 0.2));
        return <circle key={i} cx={x} cy={y} r={r * s} fill={i === 1 ? color : ink} />;
      })}
    </svg>
  );
};

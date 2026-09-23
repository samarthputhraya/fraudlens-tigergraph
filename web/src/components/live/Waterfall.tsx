import { Bar, BarChart, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Contribution, InvEvent } from "../../api/types";
import { logit, sigmoid, P_MAX, P_MIN, STOP_HI, STOP_LO } from "../../lib/ledger";
import { bandColor } from "./Gauge";
import { titleCase } from "../../lib/format";

interface Row {
  name: string;
  range: [number, number];
  delta: number;
  kind: "prior" | "step" | "post";
  lr?: number;
  family?: string;
  claim?: string;
  p?: number;
}

const FRAUD = "#EF5A50";
const LEGIT = "#3CC585";

export function EvidenceWaterfall({
  prior, contributions, p, findings, triggerLabel,
}: { prior: number; contributions: Contribution[]; p: number | null; findings: InvEvent[]; triggerLabel: string }) {
  const lp = logit(prior);
  const rows: Row[] = [{ name: "Prior", range: [0, lp], delta: lp, kind: "prior", claim: `Starting belief for a ${triggerLabel} alert`, p: prior }];
  let cum = lp;
  for (const c of contributions) {
    const f = findings.find((x) => x.key === c.key);
    rows.push({
      name: titleCase(c.key),
      range: [cum, cum + c.delta_logodds],
      delta: c.delta_logodds,
      kind: "step",
      lr: c.lr,
      family: c.family,
      claim: f?.claim,
    });
    cum += c.delta_logodds;
  }
  const clamped = cum > logit(P_MAX) || cum < logit(P_MIN);
  if (p != null) rows.push({ name: "Posterior", range: [0, logit(p)], delta: logit(p), kind: "post", p, claim: clamped ? `Ledger total ${cum.toFixed(2)} log-odds, capped at ${p.toFixed(2)} by the calibration bounds` : undefined });

  const all = rows.flatMap((r) => r.range);
  const lo = Math.min(-3.6, Math.floor(Math.min(...all) - 0.4));
  const hi = Math.max(3.6, Math.ceil(Math.max(...all) + 0.8));
  const ticks = [0.03, STOP_LO, 0.5, STOP_HI, 0.97].map(logit).filter((t) => t >= lo && t <= hi);
  const height = rows.length * 30 + 34;

  const color = (r: Row) =>
    r.kind === "prior" ? "#96A1B3" : r.kind === "post" ? bandColor(r.p ?? 0.5) : r.delta > 0.001 ? FRAUD : r.delta < -0.001 ? LEGIT : "#465265";

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 48, bottom: 4, left: 4 }} barCategoryGap={7}>
          <XAxis
            type="number"
            domain={[lo, hi]}
            ticks={ticks}
            tickFormatter={(x: number) => sigmoid(x).toFixed(2)}
            tick={{ fill: "#6A7688", fontSize: 10, fontFamily: "JetBrains Mono Variable" }}
            axisLine={{ stroke: "#2B3544" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={104}
            tick={{ fill: "#C3CBD7", fontSize: 11.5 }}
            axisLine={false}
            tickLine={false}
          />
          <ReferenceLine x={0} stroke="#2B3544" />
          <ReferenceLine x={logit(STOP_HI)} stroke={FRAUD} strokeOpacity={0.55} strokeDasharray="3 3" />
          <ReferenceLine x={logit(STOP_LO)} stroke={LEGIT} strokeOpacity={0.55} strokeDasharray="3 3" />
          <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} content={<Tip />} />
          <Bar dataKey="range" radius={3} isAnimationActive animationDuration={550}>
            {rows.map((r, i) => (
              <Cell key={i} fill={color(r)} fillOpacity={r.kind === "prior" ? 0.55 : 0.9} />
            ))}
            <LabelList dataKey="delta" content={<EndLabel rows={rows} />} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function EndLabel(props: any) {
  const { x, y, width, height, index, rows } = props;
  const r: Row | undefined = rows?.[index];
  if (!r) return null;
  const end = Math.max(x, x + width);
  const txt = r.kind === "step" ? `${r.delta >= 0 ? "+" : "−"}${Math.abs(r.delta).toFixed(2)}` : (r.p ?? 0).toFixed(2);
  return (
    <text x={end + 6} y={y + height / 2 + 3.5} fill={r.kind === "step" ? "#96A1B3" : "#E7EBF1"} fontSize={10.5} fontFamily="JetBrains Mono Variable" fontWeight={r.kind === "post" ? 700 : 500}>
      {txt}
    </text>
  );
}

function Tip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const r: Row = payload[0].payload;
  return (
    <div className="max-w-[300px] rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-xs shadow-panel">
      <div className="font-semibold text-ink-100">{r.name}</div>
      {r.kind === "step" && (
        <div className="mt-0.5 font-mono text-[11px] text-ink-300">
          {r.family} · LR ×{r.lr} · {r.delta >= 0 ? "+" : ""}
          {r.delta.toFixed(3)} log-odds
        </div>
      )}
      {r.kind !== "step" && <div className="mt-0.5 font-mono text-[11px] text-ink-300">p = {(r.p ?? 0).toFixed(3)}</div>}
      {r.claim && <div className="mt-1.5 leading-5 text-ink-200">{r.claim}</div>}
    </div>
  );
}

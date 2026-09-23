import {
  CartesianGrid, Cell, LabelList, Pie, PieChart, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis, Bar, BarChart, Line, ComposedChart,
} from "recharts";
import { Info, Network } from "lucide-react";
import { useLoad } from "../api";
import type { Metrics } from "../api/types";
import { Empty, IdChip, Panel, Skeleton, cx } from "../components/ui";
import { money, patternLabel, pct } from "../lib/format";
import { deviceLabel } from "../lib/entities";

const AXIS = { fill: "#6A7688", fontSize: 10.5, fontFamily: "JetBrains Mono Variable" };

function Tile({ label, value, hint, tone }: { label: string; value: string; hint: string; tone?: "good" | "warn" | "bad" }) {
  const color = tone === "good" ? "#3CC585" : tone === "warn" ? "#EDB341" : tone === "bad" ? "#EF5A50" : "#E7EBF1";
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-850 px-4 py-3.5 shadow-panel">
      <div className="text-xs text-ink-400">{label}</div>
      <div className="mt-1 text-[28px] font-semibold leading-8 tracking-[-0.02em]" style={{ color }}>
        {value}
      </div>
      <div className="mt-1 text-[11.5px] leading-4 text-ink-400">{hint}</div>
    </div>
  );
}

const toneHi = (v: number | undefined | null, good: number, ok: number) => (v == null ? undefined : v >= good ? "good" : v >= ok ? "warn" : "bad");
const toneLo = (v: number | undefined | null, good: number, ok: number) => (v == null ? undefined : v <= good ? "good" : v <= ok ? "warn" : "bad");

const VERDICT_COLORS: Record<string, string> = { fraud: "#EF5A50", legitimate: "#3CC585", uncertain: "#EDB341" };

export default function InsightsView() {
  const { data, loading, error } = useLoad<Metrics>((a) => a.metrics());
  if (loading && !data)
    return (
      <div className="mx-auto grid max-w-[1560px] grid-cols-6 gap-4 px-8 py-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  if (error || !data) return <Empty title="Metrics did not load">{error}</Empty>;

  const b = data.backtest;
  const p = data.portfolio;
  const brier = b?.brier ?? b?.brier_balanced;
  const rel = (b?.reliability || []).map((r) => ({ ...r, label: r.bin }));
  const verdicts = p ? Object.entries(p.verdicts).filter(([, n]) => n > 0).map(([k, n]) => ({ name: k, value: n })) : [];
  const nCases = verdicts.reduce((s, x) => s + x.value, 0);
  const patterns = p
    ? Object.entries(p.patterns).filter(([k]) => k !== "none").map(([k, n]) => ({ name: patternLabel(k), value: n })).sort((a, b) => b.value - a.value)
    : [];
  const noPattern = p?.patterns?.none || 0;
  const pMax = Math.max(1, ...patterns.map((x) => x.value));
  const pTicks = Array.from({ length: Math.floor(pMax / (pMax > 8 ? 2 : 1)) + 1 }, (_, i) => i * (pMax > 8 ? 2 : 1));

  return (
    <div className="mx-auto max-w-[1560px] px-8 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.015em] text-ink-100">Insights</h2>
          <p className="mt-1 text-[13px] text-ink-400">
            {b ? `Backtest of the deterministic core against ${b.n_cases} closed cases with known outcomes, and the portfolio of cases the agent has closed.` : "Portfolio of cases the agent has closed."}
          </p>
        </div>
      </div>

      {b && (
        <>
          <h3 className="mt-6 text-[14px] font-semibold text-ink-200">Backtest on closed-case history</h3>
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Tile label="Pattern accuracy" value={pct(b.pattern_accuracy)} hint="confirmed-fraud cases whose pattern the agent named correctly" tone={toneHi(b.pattern_accuracy, 0.7, 0.5)} />
            <Tile label="Episode Jaccard" value={b.episode_jaccard.toFixed(2)} hint="overlap between the agent's fraud episode and the true one" tone={toneHi(b.episode_jaccard, 0.75, 0.5)} />
            <Tile label="SAR agreement" value={pct(b.sar_agreement)} hint="file or don't-file decisions matching the analysts" tone={toneHi(b.sar_agreement, 0.75, 0.5)} />
            <Tile label="Exposure MAE" value={money(b.exposure_mae, 0)} hint="mean absolute error of the exposure in USD" tone={toneLo(b.exposure_mae, 100, 300)} />
            <Tile label="Verdict accuracy" value={pct(b.verdict_accuracy)} hint={b.uncertain_share != null ? `on decided cases; ${pct(b.uncertain_share)} left uncertain` : "fraud vs cleared on decided cases"} tone={toneHi(b.verdict_accuracy, 0.75, 0.5)} />
            <Tile label={b.brier_balanced != null && b.brier == null ? "Brier, class-balanced" : "Brier score"} value={brier != null ? brier.toFixed(3) : "—"} hint="squared error of the probability; lower is better" tone={toneLo(brier, 0.15, 0.25)} />
          </div>
          {b.note && (
            <div className="mt-3 flex gap-2.5 rounded-lg border border-ink-700 bg-ink-850 px-4 py-2.5 text-[12.5px] leading-5 text-ink-300">
              <Info size={15} className="mt-0.5 shrink-0 text-tg-400" />
              <span>
                {b.note}
                {b.evidence_auc_all != null && (
                  <>
                    {" "}
                    Evidence-only AUC: <span className="font-mono text-ink-100">{b.evidence_auc_all.toFixed(3)}</span>
                    {b.evidence_auc_score_ge_0_5 != null && (
                      <>
                        {" "}overall, <span className="font-mono text-ink-100">{b.evidence_auc_score_ge_0_5.toFixed(3)}</span> on alerts scored 0.5 or higher
                      </>
                    )}
                    .
                  </>
                )}
              </span>
            </div>
          )}
        </>
      )}

      <div className="mt-5 grid grid-cols-12 gap-5">
        {b && (
          <Panel className="col-span-12 xl:col-span-6" title="Reliability diagram" aside={<span>predicted vs observed fraud rate, by bin</span>}>
            <div className="h-[330px]">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={rel} margin={{ top: 10, right: 16, bottom: 22, left: 0 }}>
                  <CartesianGrid stroke="#1F2733" />
                  <XAxis
                    type="number"
                    dataKey="predicted"
                    domain={[0, 1]}
                    ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
                    tick={AXIS}
                    axisLine={{ stroke: "#2B3544" }}
                    tickLine={false}
                    label={{ value: "Predicted probability", position: "insideBottom", offset: -12, fill: "#96A1B3", fontSize: 11.5 }}
                  />
                  <YAxis
                    type="number"
                    domain={[0, 1]}
                    ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
                    tick={AXIS}
                    axisLine={false}
                    tickLine={false}
                    width={58}
                    label={{ value: "Observed fraud rate", angle: -90, position: "insideLeft", offset: 2, fill: "#96A1B3", fontSize: 11.5, style: { textAnchor: "middle" } }}
                  />
                  <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#465265" strokeDasharray="4 4" ifOverflow="extendDomain" />
                  <Tooltip cursor={false} content={<RelTip />} />
                  <Line type="linear" dataKey="observed" stroke="#F58025" strokeWidth={2} dot={false} activeDot={false} isAnimationActive={false} />
                  <Scatter dataKey="observed" fill="#F58025" stroke="#0E1218" strokeWidth={2} shape={<SizedDot />} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-1 text-[11.5px] text-ink-400">Dashed diagonal is perfect calibration. Dot size is the number of cases in the bin.</p>
          </Panel>
        )}

        {p && (
          <Panel className="col-span-12 md:col-span-6 xl:col-span-3" title="Verdicts" aside={<span>{nCases} closed by the agent</span>}>
            <div className="relative h-[210px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={verdicts} dataKey="value" nameKey="name" innerRadius={62} outerRadius={88} paddingAngle={verdicts.length > 1 ? 2 : 0} stroke="none" isAnimationActive>
                    {verdicts.map((v) => (
                      <Cell key={v.name} fill={VERDICT_COLORS[v.name] || "#6A7688"} />
                    ))}
                  </Pie>
                  <Tooltip content={<SimpleTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <div className="text-[28px] font-semibold text-ink-100">{nCases}</div>
                <div className="text-[11px] text-ink-400">cases</div>
              </div>
            </div>
            <ul className="mt-2 space-y-1.5">
              {Object.entries(p.verdicts).map(([k, n]) => (
                <li key={k} className="flex items-center justify-between text-[12.5px]">
                  <span className="inline-flex items-center gap-2 text-ink-200">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: VERDICT_COLORS[k] || "#6A7688" }} />
                    {k[0].toUpperCase() + k.slice(1)}
                  </span>
                  <span className="font-mono tabular-nums text-ink-100">{n}</span>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {p && (
          <Panel className="col-span-12 md:col-span-6 xl:col-span-3" title="Portfolio">
            <dl className="space-y-3">
              {[
                ["Exposure under investigation", money(p.total_exposure)],
                ["SARs recommended", String(p.sar_filed)],
                ["Avg TigerGraph queries per case", p.avg_tool_calls.toFixed(1)],
                ["Avg LLM tokens per case", Math.round(p.avg_tokens).toLocaleString("en-US")],
                ["Avg time to decision", `${p.avg_latency_s.toFixed(1)} s`],
              ].map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-3 border-b border-ink-750 pb-2 last:border-0">
                  <dt className="text-[12.5px] text-ink-300">{k}</dt>
                  <dd className="font-mono text-[14px] font-semibold tabular-nums text-ink-100">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>
        )}

        {p && (
          <Panel className="col-span-12 xl:col-span-6" title="Patterns found" aside={<span>fraud and uncertain cases per pattern{noPattern ? `; ${noPattern} legitimate cases have none` : ""}</span>}>
            <div style={{ height: Math.max(90, patterns.length * 34 + 30) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={patterns} layout="vertical" margin={{ top: 0, right: 30, bottom: 0, left: 0 }} barCategoryGap={8}>
                  <XAxis type="number" allowDecimals={false} domain={[0, pMax]} ticks={pTicks} tick={AXIS} axisLine={{ stroke: "#2B3544" }} tickLine={false} />
                  <YAxis type="category" dataKey="name" width={150} tick={{ fill: "#C3CBD7", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} content={<SimpleTip />} />
                  <Bar dataKey="value" fill="#F58025" radius={[0, 4, 4, 0]} maxBarSize={18}>
                    <LabelList dataKey="value" position="right" fill="#C3CBD7" fontSize={11} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        )}

        {b?.pattern_confusion?.length ? (
          <Panel className="col-span-12 xl:col-span-6" title="Pattern confusion" aside={<span>true pattern → agent's pattern, top pairs</span>}>
            <table className="w-full text-left text-[12.5px]">
              <tbody>
                {b.pattern_confusion.slice(0, 8).map(([pair, n]) => {
                  const [t, pr] = pair.split("->");
                  const ok = t === pr;
                  return (
                    <tr key={pair} className="border-b border-ink-750 last:border-0">
                      <td className="py-1.5 text-ink-200">{patternLabel(t)}</td>
                      <td className="py-1.5 text-ink-500">→</td>
                      <td className={cx("py-1.5", ok ? "text-legit" : "text-unsure")}>{patternLabel(pr)}</td>
                      <td className="py-1.5 text-right font-mono tabular-nums text-ink-100">{n}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        ) : null}

        <Panel
          className="col-span-12"
          title={
            <span className="inline-flex items-center gap-2">
              <Network size={14} className="text-fraud" /> Fraud rings
            </span>
          }
          aside={<span>connected components over shared rare devices</span>}
        >
          {!data.rings.length && <p className="text-[13px] text-ink-400">No rings detected yet.</p>}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {data.rings.map((r) => (
              <div key={String(r.component)} className="rounded-xl border border-fraud-line/60 bg-fraud-soft/30 p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[13px] font-semibold text-ink-100">{String(r.component)}</span>
                  <span className="text-xs text-ink-300">
                    <span className="font-mono text-fraud">{r.members.length}</span> cards
                  </span>
                </div>
                {!!r.devices.length && (
                  <div className="mt-2 text-[12px] text-ink-300">
                    via{" "}
                    {r.devices.map((d) => (
                      <span key={d} className="font-mono text-[#8DEBDD]" title={d}>
                        {deviceLabel(d)}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-2.5 flex flex-wrap gap-1">
                  {r.members.map((m) => (
                    <IdChip key={m} id={m} tone="ring" />
                  ))}
                </div>
                {!!r.fraud_cases.length && (
                  <div className="mt-2.5 flex flex-wrap items-center gap-1">
                    <span className="mr-1 text-[11.5px] text-ink-400">linked closed cases</span>
                    {r.fraud_cases.map((m) => (
                      <IdChip key={m} id={m} tone="case" />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function SizedDot(props: any) {
  const { cx: x, cy: y, payload } = props;
  if (x == null || y == null) return null;
  const r = 4 + Math.sqrt(payload?.n || 1) * 0.9;
  return <circle cx={x} cy={y} r={r} fill="#F58025" fillOpacity={0.85} stroke="#0E1218" strokeWidth={2} />;
}

function RelTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-xs shadow-panel">
      <div className="font-mono font-semibold text-ink-100">bin {r.bin}</div>
      <div className="mt-0.5 text-ink-300">
        predicted <span className="font-mono text-ink-100">{r.predicted.toFixed(3)}</span> · observed <span className="font-mono text-ink-100">{r.observed.toFixed(3)}</span>
      </div>
      <div className="text-ink-400">{r.n} cases</div>
    </div>
  );
}

function SimpleTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const r = payload[0];
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800 px-3 py-1.5 text-xs shadow-panel">
      <span className="text-ink-200">{r.name ?? r.payload?.name}</span> <span className="font-mono font-semibold text-ink-100">{r.value}</span>
    </div>
  );
}

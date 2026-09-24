import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Pie, PieChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import { Fingerprint, History, Info, Network, Sigma, Table2 } from "lucide-react";
import type { ReactNode } from "react";
import { useLoad } from "../api";
import type { Metrics, ModelReport } from "../api/types";
import { Empty, IdChip, Panel, Skeleton, cx } from "../components/ui";
import { money, patternLabel, pct } from "../lib/format";
import { deviceLabel } from "../lib/entities";

const MONO = "JetBrains Mono Variable";
const AXIS = { fill: "#6A7688", fontSize: 10.5, fontFamily: MONO };
const SURFACE = "#0E1218"; // ink-850, the panel surface
const BANK = "#465265";
const MODEL = "#F58025";
const FRAUD = "#EF5A50";
const LEGIT = "#3CC585";

/** AUCs to three decimals, rounding half up (0.8865 reads 0.887, as in eval/model_card.md). */
const auc3 = (v: number | null | undefined) => (v == null ? "—" : (Math.round(v * 1000 + 1e-6) / 1000).toFixed(3));

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

// Graph findings the transaction model cannot see: the single-signal likelihood ratios the v2 ledger still counts
// (agent/detectors.py, eval/likelihoods.md). Signals the model already reads are shown as evidence, never counted twice.
const LEDGER = [
  {
    name: "Structuring just under $500", sub: "3+ online buys of $400–499 in an hour", lr: 40, label: "40",
    rule: "Three or more online purchases between $400 and $500 on one card within 60 minutes.",
  },
  {
    name: "Card-testing sequence", sub: "3+ online auths under $5, then a buy", lr: 30, label: "30",
    rule: "Three or more online authorisations under $5 within an hour, followed by a larger purchase.",
  },
  {
    name: "Ring: new device + proxy", sub: "one device, new to 3+ other customers", lr: 28, label: "28",
    rule: "One device profile used as a New device by three or more other customers, mostly behind an anonymising proxy. Grows with the number of customers, up to 28.",
  },
  {
    name: "Fraud on other cards (R6)", sub: "same rare device, model-scored as fraud", lr: 5.5, label: "4–7",
    rule: "A rare device (10 cards or fewer) also used on other customers' cards, where the transaction model scores those uses as fraud. Grows with the number of customers.",
  },
  {
    name: "Card named in a confirmed case", sub: "listed as a connected card in closed fraud", lr: 4, label: "4",
    rule: "The card was listed as a connected card in a confirmed-fraud closed case.",
  },
  {
    name: "Second alert on the same account", sub: "another ≥ 0.7 score within 48 hours", lr: 2.5, label: "2.5",
    rule: "Another transaction on the same resolved account, within 48 hours, was also scored 0.7 or higher by the bank.",
  },
  {
    name: "Mixed channels + identity anomaly", sub: "in person and online within 48 h", lr: 2, label: "2",
    rule: "Both card-present and online purchases on the same account within 48 hours, with a new device, a proxy or a name/address mismatch flag.",
  },
  {
    name: "Several days in one new region", sub: "a stay: travel, not a clone", lr: 0.5, label: "0.5",
    rule: "Card-present purchases in a region new to the card on three or more different days: a trip, which points away from fraud.",
  },
  {
    name: "Same-identity recurring charge (R7)", sub: "monthly, same e-mail, device, product", lr: 0.3, label: "0.3",
    rule: "The same amount on the same day of earlier months, from the same e-mail domain, device and product. 0.3 when the customer disputes it, 0.7 otherwise.",
  },
];
const LEDGER_SUBS: Record<string, string> = Object.fromEntries(LEDGER.map((d) => [d.name, d.sub]));

const READS = [
  { icon: Table2, title: "Unnamed Vesta C, D, M and V columns", detail: "plus amount, product, card fields and e-mail domains" },
  { icon: Fingerprint, title: "The identity record", detail: "device profile, proxy and the other identity fields" },
  { icon: Sigma, title: "Running account aggregates", detail: "resolved account, card, device and e-mail domain, over earlier transactions only" },
  { icon: History, title: "Graph memory of prior closed cases", detail: "confirmed and cleared cases on the same account and card, closed before the transaction" },
];

const REL_TICKS = [0, 0.02, 0.1, 0.25, 0.5, 1];

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
  const m = data.model;
  const verdicts = p ? Object.entries(p.verdicts).filter(([, n]) => n > 0).map(([k, n]) => ({ name: k, value: n })) : [];
  const nCases = verdicts.reduce((s, x) => s + x.value, 0);
  const patterns = p
    ? Object.entries(p.patterns).filter(([k]) => k !== "none").map(([k, n]) => ({ name: patternLabel(k), value: n })).sort((a, b) => b.value - a.value)
    : [];
  const noPattern = p?.patterns?.none || 0;
  const pMax = Math.max(1, ...patterns.map((x) => x.value));
  const pTicks = Array.from({ length: Math.floor(pMax / (pMax > 8 ? 2 : 1)) + 1 }, (_, i) => i * (pMax > 8 ? 2 : 1));
  // The report's note ends with a sentence about the retired evidence-only AUC: keep only the selection-bias caveat,
  // and say whose alerts the cleared cases were, now that "the model" on this page means the FraudLens model.
  const caveat = b?.note
    ?.replace(/\s*evidence_auc_\*[^.]*\./, "")
    .replace("high-score model alert", "high-score bank alert")
    .trim();
  const hl = b?.headline;

  return (
    <div className="mx-auto max-w-[1560px] px-8 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.015em] text-ink-100">Insights</h2>
          <p className="mt-1 text-[13px] text-ink-400">
            {m && b
              ? `The transaction model on its October hold-out, a replay of ${b.n_cases} October closed cases through the deterministic core, and the portfolio of cases the agent has closed.`
              : b
                ? `Backtest of the deterministic core against ${b.n_cases} closed cases with known outcomes, and the portfolio of cases the agent has closed.`
                : "Portfolio of cases the agent has closed."}
          </p>
        </div>
      </div>

      {m && <ModelPanel m={m} />}

      {b && (
        <>
          <div className="mt-6 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="text-[14px] font-semibold text-ink-200">Backtest on October closed cases</h3>
            {b.n_confirmed != null && b.n_cleared != null && (
              <span className="text-[12px] text-ink-400">
                {b.n_cases} cases ({b.n_confirmed} confirmed fraud, {b.n_cleared} cleared), each replayed as it looked when the alert fired
              </span>
            )}
          </div>
          <div className={cx("mt-3 grid grid-cols-2 gap-3 md:grid-cols-3", hl ? "xl:grid-cols-4" : "2xl:grid-cols-6")}>
            {b.auc_final_probability != null && (
              <Tile label="Fraud vs false alarm (AUC)" value={auc3(b.auc_final_probability)} hint="final probability, October closed cases" tone={toneHi(b.auc_final_probability, 0.8, 0.7)} />
            )}
            {b.auc_final_probability_score_ge_0_5 != null && (
              <Tile
                label="On high-score alerts"
                value={auc3(b.auc_final_probability_score_ge_0_5)}
                hint={`final probability on the ${b.n_score_ge_0_5 ?? ""} alerts the bank scored ≥ 0.5`}
                tone={toneHi(b.auc_final_probability_score_ge_0_5, 0.8, 0.7)}
              />
            )}
            <Tile label="Pattern accuracy" value={pct(b.pattern_accuracy)} hint="confirmed-fraud cases whose pattern the agent named correctly" tone={toneHi(b.pattern_accuracy, 0.7, 0.5)} />
            <Tile label="Episode Jaccard" value={b.episode_jaccard.toFixed(2)} hint="overlap between the agent's fraud episode and the true one" tone={toneHi(b.episode_jaccard, 0.75, 0.5)} />
            <Tile label="SAR agreement" value={pct(b.sar_agreement)} hint="file or don't-file decisions matching the analysts" tone={toneHi(b.sar_agreement, 0.75, 0.5)} />
            <Tile label="Exposure MAE" value={money(b.exposure_mae, 0)} hint="mean absolute error of the exposure in USD" tone={toneLo(b.exposure_mae, 100, 300)} />
            {hl?.card_id_rule_match != null && (
              <Tile label="Card-ID rule" value={pct(hl.card_id_rule_match)} hint="bank card IDs reproduced from (network, type) on 14,955 closed-case transactions" tone={toneHi(hl.card_id_rule_match, 0.75, 0.5)} />
            )}
            {hl?.graph_vs_mirror_parity != null && (
              <Tile label="Graph ↔ mirror parity" value={pct(hl.graph_vs_mirror_parity)} hint="installed GSQL queries on Savanna match an independent implementation" tone={toneHi(hl.graph_vs_mirror_parity, 0.75, 0.5)} />
            )}
          </div>
          {(caveat || b.auc_final_probability != null) && (
            <div className="mt-3 flex gap-2.5 rounded-lg border border-ink-700 bg-ink-850 px-4 py-2.5 text-[12.5px] leading-5 text-ink-300">
              <Info size={15} className="mt-0.5 shrink-0 text-tg-400" />
              <span>
                {caveat}
                {b.auc_final_probability != null && (
                  <>
                    {caveat ? " " : ""}
                    Final-probability AUC: <Num>{auc3(b.auc_final_probability)}</Num> on all {b.n_cases} cases
                    {b.auc_model_only != null && (
                      <>
                        {" "}(<Num>{auc3(b.auc_model_only)}</Num> from the transaction model alone)
                      </>
                    )}
                    {b.auc_final_probability_score_ge_0_5 != null && (
                      <>
                        , <Num>{auc3(b.auc_final_probability_score_ge_0_5)}</Num> on the {b.n_score_ge_0_5} alerts scored 0.5 or higher
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
        {m && (
          <Panel
            className="col-span-12 xl:col-span-6"
            title="What still moves the ledger"
            aside={<Legend items={[["points to fraud", FRAUD], ["points to legitimate", LEGIT]]} />}
          >
            <div className="h-[400px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={LEDGER} layout="vertical" margin={{ top: 2, right: 34, bottom: 18, left: 4 }} barCategoryGap="30%">
                  <CartesianGrid stroke="#1F2733" horizontal={false} />
                  <XAxis type="number" scale="log" domain={[0.1, 50]} ticks={[0.1, 0.3, 1, 3, 10, 30]} tick={AXIS} axisLine={{ stroke: "#2B3544" }} tickLine={false}
                    label={{ value: "Likelihood ratio (log scale; >1 points to fraud)", position: "insideBottom", offset: -12, fill: "#96A1B3", fontSize: 11.5 }} />
                  <YAxis type="category" dataKey="name" width={236} interval={0} tick={<TwoLineTick subs={LEDGER_SUBS} />} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} content={<LedgerTip />} />
                  <Bar dataKey={(d: (typeof LEDGER)[number]) => [Math.min(1, d.lr), Math.max(1, d.lr)]} shape={<LrBar />} maxBarSize={18} isAnimationActive={false} />
                  <ReferenceLine x={1} stroke="#465265" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-[11.5px] leading-[17px] text-ink-400">
              The model's calibrated probability is the starting point; these graph findings about other cards, devices and past cases move it. Signals the model
              already sees are shown in the evidence but never counted twice. A customer dispute starts at <Num>0.86</Num> and an analyst request at{" "}
              <Num>0.45</Num> instead, each moved by the model's likelihood ratio.
            </p>
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

// ---------- Transaction model ----------
function ModelPanel({ m }: { m: ModelReport }) {
  const v = m.validation;
  const without = m.validation_without_risk_score;
  const rows = [
    {
      group: "All October transactions",
      sub: `${v.n_valid.toLocaleString("en-US")} transactions, ${pct(v.fraud_rate_valid, 1)} fraud`,
      bank: m.bank_score.auc_october_all,
      model: v.auc_october_all,
    },
    {
      group: "Alerts the bank scored ≥ 0.5",
      sub: `${v.n_alerts_score_ge_0_5.toLocaleString("en-US")} alerts`,
      bank: m.bank_score.auc_october_alerts_score_ge_0_5,
      model: v.auc_october_alerts_score_ge_0_5,
    },
  ];
  const subs = Object.fromEntries(rows.map((r) => [r.group, r.sub]));
  return (
    <Panel
      className="mt-6"
      title="Transaction model"
      aside={<span>LightGBM{m.n_features ? ` · ${m.n_features} features` : ""} · trained on July–September, tested on October</span>}
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-12">
        <div className="md:col-span-2 xl:col-span-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-[12.5px] font-semibold text-ink-200">Fraud vs false alarm (AUC)</h4>
            <Legend items={[["Bank risk score", BANK], ["FraudLens model", MODEL]]} />
          </div>
          <div className="mt-2 h-[214px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 46, bottom: 18, left: 4 }} barGap={2} barCategoryGap="24%">
                <CartesianGrid stroke="#1F2733" horizontal={false} />
                <XAxis type="number" domain={[0.5, 1]} ticks={[0.5, 0.6, 0.7, 0.8, 0.9, 1]} tickFormatter={(t: number) => t.toFixed(1)} tick={AXIS} axisLine={{ stroke: "#2B3544" }} tickLine={false}
                  label={{ value: "AUC (0.5 = chance, 1.0 = perfect ranking)", position: "insideBottom", offset: -12, fill: "#96A1B3", fontSize: 11.5 }} />
                <YAxis type="category" dataKey="group" width={214} interval={0} tick={<TwoLineTick subs={subs} />} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} content={<AucTip />} />
                <Bar dataKey="bank" name="Bank risk score" fill={BANK} barSize={20} radius={[0, 4, 4, 0]}>
                  <LabelList dataKey="bank" position="right" formatter={auc3} fill="#96A1B3" fontSize={11.5} fontFamily={MONO} />
                </Bar>
                <Bar dataKey="model" name="FraudLens model" fill={MODEL} barSize={20} radius={[0, 4, 4, 0]}>
                  <LabelList dataKey="model" position="right" formatter={auc3} fill="#E7EBF1" fontSize={11.5} fontWeight={600} fontFamily={MONO} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[12px] leading-[18px] text-ink-400">
            AUC = how often a real fraud is ranked above a false alarm. October was held out: the model never saw its labels. Features use only what the bank
            knew at transaction time.
          </p>
        </div>

        <div className="xl:col-span-3 xl:border-l xl:border-ink-700/70 xl:pl-6">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-[12.5px] font-semibold text-ink-200">Reliability</h4>
            <span className="text-[11px] text-ink-400">October, raw scores</span>
          </div>
          <div className="mt-2 h-[214px]">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 6, right: 12, bottom: 18, left: 0 }}>
                <CartesianGrid stroke="#1F2733" />
                <XAxis type="number" dataKey="predicted" scale="sqrt" domain={[0, 1]} ticks={REL_TICKS} tickFormatter={relTick} tick={AXIS} axisLine={{ stroke: "#2B3544" }} tickLine={false}
                  label={{ value: "predicted", position: "insideBottom", offset: -12, fill: "#96A1B3", fontSize: 11.5 }} />
                <YAxis type="number" dataKey="observed" scale="sqrt" domain={[0, 1]} ticks={REL_TICKS} tickFormatter={relTick} tick={AXIS} axisLine={false} tickLine={false} width={44}
                  label={{ value: "observed", angle: -90, position: "insideLeft", offset: 6, fill: "#96A1B3", fontSize: 11.5, style: { textAnchor: "middle" } }} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#465265" strokeDasharray="4 4" />
                <Tooltip cursor={false} content={<RelTip unit="transactions" />} />
                <Scatter data={m.reliability_october_raw} line={{ stroke: MODEL, strokeWidth: 2 }} shape={<RelDot />} isAnimationActive={false} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-[12px] leading-[18px] text-ink-400">
            Observed fraud rate per score bin on √ axes; dashed = perfect calibration. The agent reads the score after isotonic calibration.
          </p>
        </div>

        <div className="xl:col-span-3 xl:border-l xl:border-ink-700/70 xl:pl-6">
          <h4 className="text-[12.5px] font-semibold text-ink-200">What it reads</h4>
          <ul className="mt-2.5 space-y-2.5">
            {READS.map(({ icon: Icon, title, detail }) => (
              <li key={title} className="flex gap-2.5">
                <Icon size={15} className="mt-0.5 shrink-0 text-tg-400" />
                <div className="min-w-0">
                  <div className="text-[12.5px] leading-[18px] text-ink-100">{title}</div>
                  <div className="text-[11.5px] leading-4 text-ink-400">{detail}</div>
                </div>
              </li>
            ))}
          </ul>
          {without && (
            <div className="mt-3 border-t border-ink-700/70 pt-2.5 text-[12px] text-ink-300">
              Without the bank's score: <Num>{auc3(without.auc_october_all)}</Num> / <Num>{auc3(without.auc_october_alerts_score_ge_0_5)}</Num>{" "}
              <span className="whitespace-nowrap text-ink-400">(all / alerts ≥ 0.5)</span>
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}

const relTick = (t: number) => (t === 0 || t === 1 ? String(t) : String(t).replace(/^0/, ""));

function Num({ children }: { children: ReactNode }) {
  return <span className="font-mono text-ink-100">{children}</span>;
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="flex items-center gap-3 text-[11.5px] text-ink-300">
      {items.map(([label, color]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}

/** Category tick with a muted second line (the detail under each label). */
function TwoLineTick({ x, y, payload, subs }: any) {
  const sub = subs?.[payload?.value];
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={-12} y={sub ? -3 : 0} dy={sub ? undefined : "0.35em"} textAnchor="end" fill="#C3CBD7" fontSize={12}>
        {payload?.value}
      </text>
      {sub && (
        <text x={-12} y={11} textAnchor="end" fill="#6A7688" fontSize={10.5}>
          {sub}
        </text>
      )}
    </g>
  );
}

/** Likelihood-ratio bar that grows from LR 1 (no effect), rounded at its data end, with its value at the tip. */
function LrBar(props: any) {
  const { x, y, width, height, payload } = props;
  if (x == null || y == null || !width || !height) return null;
  const fraud = payload.lr >= 1;
  const w = Math.abs(width);
  const x0 = width < 0 ? x + width : x;
  const r = Math.min(4, w / 2, height / 2);
  const d = fraud
    ? `M${x0},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${height - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${r - w}Z`
    : `M${x0 + w},${y}h${r - w}a${r},${r} 0 0 0 ${-r},${r}v${height - 2 * r}a${r},${r} 0 0 0 ${r},${r}h${w - r}Z`;
  return (
    <g>
      <path d={d} fill={fraud ? FRAUD : LEGIT} />
      <text x={fraud ? x0 + w + 6 : x0 - 6} y={y + height / 2} dy="0.35em" textAnchor={fraud ? "start" : "end"} fill="#C3CBD7" fontSize={11} fontFamily={MONO}>
        {payload.label}
      </text>
    </g>
  );
}

function RelDot(props: any) {
  const { cx: x, cy: y } = props;
  if (x == null || y == null) return null;
  return (
    <g>
      <circle cx={x} cy={y} r={12} fill="transparent" />
      <circle cx={x} cy={y} r={5} fill={MODEL} stroke={SURFACE} strokeWidth={2} />
    </g>
  );
}

function AucTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-xs shadow-panel">
      <div className="font-semibold text-ink-100">{r.group}</div>
      {(
        [
          ["Bank risk score", BANK, r.bank],
          ["FraudLens model", MODEL, r.model],
        ] as [string, string, number][]
      ).map(([k, c, val]) => (
        <div key={k} className="mt-1 flex items-center gap-2 text-ink-300">
          <span className="h-2 w-2 rounded-sm" style={{ background: c }} />
          {k}
          <span className="ml-auto pl-4 font-mono text-ink-100">{auc3(val)}</span>
        </div>
      ))}
    </div>
  );
}

function LedgerTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as (typeof LEDGER)[number];
  return (
    <div className="max-w-[320px] rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-xs shadow-panel">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-semibold text-ink-100">{d.name}</span>
        <span className="shrink-0 font-mono text-ink-100">LR {d.label}</span>
      </div>
      <div className="mt-1 leading-[17px] text-ink-300">{d.rule}</div>
    </div>
  );
}

function RelTip({ active, payload, unit = "cases" }: any) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-xs shadow-panel">
      <div className="font-mono font-semibold text-ink-100">bin {r.bin}</div>
      <div className="mt-0.5 text-ink-300">
        predicted <span className="font-mono text-ink-100">{r.predicted.toFixed(3)}</span> · observed <span className="font-mono text-ink-100">{r.observed.toFixed(3)}</span>
      </div>
      <div className="text-ink-400">
        {Number(r.n).toLocaleString("en-US")} {unit}
      </div>
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

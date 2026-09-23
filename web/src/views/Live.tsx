import { useEffect, useMemo, useRef, useState } from "react";
import { animate } from "framer-motion";
import { Link, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { RotateCcw, FileText, Radio, CircleDot, Check, Minus, Timer, Database, Waypoints } from "lucide-react";
import { useApiState } from "../api";
import type { Action, CaseDetail, Contribution, GraphPayload } from "../api/types";
import { activeAgents, STAGES, useInvestigation, type RunState } from "../lib/investigation";
import { buildLiveGraph, probeTargets } from "../lib/liveGraph";
import { GraphCanvas, GraphLegend } from "../components/GraphCanvas";
import { Timeline } from "../components/live/Timeline";
import { ProbabilityGauge, bandColor } from "../components/live/Gauge";
import { EvidenceWaterfall } from "../components/live/Waterfall";
import { ActionList, BranchTree, EvidenceRequestCard, FlowArrow, diffActions } from "../components/Actions";
import { Badge, Button, IdChip, Panel, Segmented, VerdictBadge, cx, RuleText } from "../components/ui";
import { money, patternLabel, triggerLabel } from "../lib/format";
import { priorFor, runningP, STOP_HI, STOP_LO } from "../lib/ledger";
import { traceToEvents } from "../lib/replay";

function useElapsed(s: RunState) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (s.status !== "running" && s.status !== "connecting") return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [s.status]);
  const end = s.endedAt || (s.status === "running" || s.status === "connecting" ? now : s.startedAt);
  return Math.max(0, (end - s.startedAt) / 1000);
}

function StageRail({ s }: { s: RunState }) {
  const skippedVerify = !!s.decision && !s.evidenceRequests.length;
  return (
    <ol className="flex items-center gap-1 overflow-x-auto">
      {STAGES.map((st, i) => {
        const skipped = st.key === "verify" && skippedVerify;
        const done = !skipped && (i < s.stageIdx || (s.status === "done" && i <= s.stageIdx));
        const current = !skipped && i === s.stageIdx && s.status !== "done";
        return (
          <li key={st.key} className="flex items-center gap-1">
            <span
              className={cx(
                "inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[11px] font-medium transition-colors",
                current && "bg-tg-500/15 text-tg-300 ring-1 ring-tg-500/60",
                done && "text-ink-200",
                skipped && "text-ink-500",
                !current && !done && !skipped && "text-ink-500",
              )}
              title={skipped ? "No evidence request: the stop rule was met without one" : undefined}
            >
              {done ? <Check size={11} className="text-legit" /> : current ? <CircleDot size={11} className="animate-pulse" /> : skipped ? <Minus size={11} /> : <span className="h-1.5 w-1.5 rounded-full bg-ink-600" />}
              {st.label}
            </span>
            {i < STAGES.length - 1 && <span className={cx("h-px w-3 shrink-0", i < s.stageIdx ? "bg-ink-500" : "bg-ink-700")} />}
          </li>
        );
      })}
    </ol>
  );
}

function families(contribs: Contribution[]) {
  const fam: Record<string, number> = {};
  for (const c of contribs) fam[c.family] = (fam[c.family] || 0) + c.delta_logodds;
  const fraud = Object.entries(fam).filter(([, w]) => w >= Math.log(1.5)).map(([k]) => k);
  const legit = Object.entries(fam).filter(([, w]) => w <= -Math.log(1.4)).map(([k]) => k);
  return { fraud, legit };
}

export default function LiveView() {
  const { caseId } = useParams();
  const { api } = useApiState();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [source, setSource] = useState<"live" | "replay">("live");
  const replay = useMemo(() => (detail?.trace ? traceToEvents(detail.trace, detail.answer, detail.row) : null), [detail]);
  const { state: s, restart } = useInvestigation(api, caseId, source, replay);
  const [server, setServer] = useState<GraphPayload | null>(null);
  const elapsed = useElapsed(s);

  useEffect(() => {
    if (!api || !caseId) return;
    try {
      localStorage.setItem("fl.lastLive", caseId);
    } catch {}
    setDetail(null);
    setServer(null);
    setSource("live");
    api.caseDetail(caseId).then(setDetail).catch(() => setDetail(null));
  }, [api, caseId]);

  // When the run completes, merge the server's neighbourhood for this case.
  useEffect(() => {
    if (!api || !caseId || s.status !== "done" || !s.final) return;
    api.graph(caseId).then(setServer).catch(() => setServer(null));
  }, [api, caseId, s.status, s.final]);

  useEffect(() => {
    if (s.status === "connecting") setServer(null);
  }, [s.status]);

  const row = detail?.row;
  const trigger = s.trigger?.trigger_type || row?.trigger_type || "analyst_request";
  const score = row?.risk_score !== "" && row?.risk_score != null ? Number(row.risk_score) : Number(/at (0\.\d+)/.exec(s.trigger?.text || "")?.[1] || NaN);
  const prior = s.assessment?.prior ?? priorFor(trigger, Number.isNaN(score) ? null : score);
  const contributions: Contribution[] =
    s.assessment?.contributions ||
    s.findings.map((f) => ({ key: f.key, family: f.family, lr: f.lr, delta_logodds: Math.log(Math.max(Number(f.lr), 1e-6)) }));
  const pNow = s.decision?.p ?? s.assessment?.p ?? (s.findings.length ? runningP(prior, s.findings as any) : s.trigger ? prior : null);
  const gaugeState = s.decision ? "decided" : s.assessment ? "assessed" : s.findings.length ? "running estimate" : s.trigger ? "prior" : "waiting";
  const fams = families(contributions);
  const stopHi = pNow != null && pNow >= STOP_HI && fams.fraud.length >= 2;
  const stopLo = pNow != null && pNow <= STOP_LO && fams.legit.length >= 2;
  const settledByReply = !!s.evidenceRequests.length && !!s.decision;
  const stopMet = stopHi || stopLo || settledByReply;

  const graph = useMemo(() => buildLiveGraph(row, s, server), [row, s, server]);
  const probe = useMemo(() => (s.lastProbe ? { ids: probeTargets(s.lastProbe.ref), n: s.lastProbe.n } : null), [s.lastProbe]);
  const types = useMemo(() => [...new Set([...graph.nodes.values()].map((n) => n.type))], [graph]);
  const ringCount = useMemo(() => [...graph.nodes.values()].filter((n) => n.ring && n.type === "Card").length, [graph]);

  const initial: Action[] = s.assessment?.initial || [];
  const final: Action[] = s.decision?.final || [];
  const sig = (xs: Action[]) => xs.map((a) => `${a.action}/${a.route}`).join(",");
  const sameNba = !!final.length && sig(initial) === sig(final);
  const assumed = s.evidenceRequests[0]?.branch;
  const whatChanged = s.answer?.next_best_actions?.what_changed;
  const vias = new Set(s.toolCalls.map((c) => (c.via || "").toLowerCase()));
  const totalMs = s.toolCalls.reduce((a, c) => a + (Number(c.ms) || 0), 0);

  const running = s.status === "running" || s.status === "connecting";

  // Bring the next-best-action panel into view when the lead investigator decides (unless the user scrolled the column).
  const rightCol = useRef<HTMLDivElement>(null);
  const nbaRef = useRef<HTMLDivElement>(null);
  const userScrolled = useRef(false);
  useEffect(() => {
    if (s.status === "connecting") {
      userScrolled.current = false;
      rightCol.current?.scrollTo({ top: 0 });
    }
  }, [s.status]);
  useEffect(() => {
    const col = rightCol.current;
    const nba = nbaRef.current;
    if (!s.decision || !col || !nba || userScrolled.current) return;
    const panelH = (nba.nextElementSibling as HTMLElement | null)?.getBoundingClientRect().height || 0;
    const offset = Math.max(12, col.clientHeight - panelH - 12); // show the whole panel, keep what fits above it
    const rel = nba.getBoundingClientRect().top - col.getBoundingClientRect().top + col.scrollTop;
    const target = Math.min(rel - offset, col.scrollHeight - col.clientHeight);
    if (target <= col.scrollTop) return;
    const c = animate(col.scrollTop, target, { duration: 0.9, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => (col.scrollTop = v) });
    return () => c.stop();
  }, [s.decision]);
  const modeLabel = api?.mode === "mock" || source === "replay" ? "Replaying saved run" : "Streaming live from the agent";

  return (
    <div className="flex h-full flex-col">
      {/* Case strip */}
      <div className="border-b border-ink-700/80 bg-ink-900 px-5 pb-2.5 pt-3">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="font-mono text-[20px] font-semibold tracking-tight text-ink-100">{caseId}</h2>
              <Badge className="border-ink-600 bg-ink-800 text-ink-200">{triggerLabel(trigger)}</Badge>
              {(row?.flagged_txn_id || s.trigger) && (
                <span className="flex items-center gap-1.5 text-xs text-ink-400">
                  flagged <IdChip id={row?.flagged_txn_id || /\b3\d{6}\b/.exec(s.trigger?.text || "")?.[0] || "—"} tone="fraud" />
                  {row?.card_id && (
                    <>
                      on <IdChip id={row.card_id} />
                    </>
                  )}
                  {!Number.isNaN(score) && (
                    <>
                      model score <span className="font-mono text-ink-200">{score.toFixed(2)}</span>
                    </>
                  )}
                </span>
              )}
            </div>
            <p className="mt-1 line-clamp-1 max-w-[980px] text-[13px] text-ink-300" title={s.trigger?.text || row?.trigger_text}>
              {s.trigger?.text || row?.trigger_text || "Waiting for the alert"}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <div className="text-right">
              <div className={cx("flex items-center justify-end gap-1.5 text-xs font-medium", running ? "text-tg-400" : s.status === "error" ? "text-fraud" : "text-ink-300")}>
                <Radio size={13} className={running ? "animate-pulse" : ""} />
                {running ? modeLabel : s.status === "error" ? "Stream failed" : s.status === "done" ? "Investigation complete" : "Idle"}
              </div>
              <div className="mt-0.5 flex items-center justify-end gap-3 font-mono text-[11.5px] tabular-nums text-ink-400">
                <span className="inline-flex items-center gap-1">
                  <Timer size={12} />
                  {elapsed.toFixed(1)}s
                </span>
                <span className="inline-flex items-center gap-1">
                  <Database size={12} />
                  {s.toolCalls.length} queries · {totalMs.toFixed(0)} ms
                </span>
              </div>
            </div>
            {api?.mode === "live" && replay && (
              <Segmented<"live" | "replay">
                value={source}
                onChange={setSource}
                options={[
                  { value: "live", label: "Run live" },
                  { value: "replay", label: "Saved run" },
                ]}
              />
            )}
            <Button variant="outline" onClick={restart} title={source === "live" && api?.mode === "live" ? "Start a new live investigation" : "Replay the saved run"}>
              <RotateCcw size={14} /> {api?.mode === "mock" || source === "replay" ? "Replay" : "Re-run"}
            </Button>
            <Link to={`/case/${caseId}`}>
              <Button variant={s.final ? "primary" : "outline"} disabled={!s.final && !detail?.answer}>
                <FileText size={14} /> Case file
              </Button>
            </Link>
          </div>
        </div>
        <div className="mt-2.5">
          <StageRail s={s} />
        </div>
      </div>

      {s.status === "error" && (
        <div className="mx-4 mt-3 rounded-lg border border-fraud-line bg-fraud-soft px-4 py-2.5 text-[13px] text-fraud">
          {s.error}. Check that the API is running on port 8000, then select Re-run.
        </div>
      )}

      {/* Three columns */}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(330px,26%)_minmax(0,1fr)_minmax(360px,27%)] gap-3 p-3">
        <Panel
          className="flex min-h-0 flex-col"
          bodyClass="flex min-h-0 flex-1 flex-col p-0 pt-1"
          title="Agent timeline"
          aside={
            <span className="font-mono text-[11px] tabular-nums">
              {s.items.length} events · {s.findings.length} findings
            </span>
          }
        >
          <Timeline items={s.items} active={activeAgents(s)} />
        </Panel>

        <Panel
          className="relative flex min-h-0 flex-col overflow-hidden"
          bodyClass="relative min-h-0 flex-1 p-0"
          title={
            <span className="inline-flex items-center gap-2">
              <Waypoints size={14} className="text-tg-500" /> <span className="whitespace-nowrap">Evidence graph</span>
            </span>
          }
          aside={
            <span className="font-mono text-[11px] tabular-nums">
              {graph.nodes.size} vertices · {graph.edges.size} edges
              {ringCount > 0 && <span className="ml-2 text-fraud">{ringCount} ring cards</span>}
              {server && <span className="ml-2 hidden text-legit 2xl:inline">+ server neighbourhood</span>}
            </span>
          }
        >
          <GraphCanvas graph={graph} probe={probe} />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-950/95 via-ink-950/70 to-transparent px-4 pb-3 pt-8">
            <GraphLegend types={types} />
            {s.lastProbe && running && (
              <motion.div key={s.lastProbe.n} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-1.5 truncate font-mono text-[11px] text-ink-400">
                <span className="text-tg-400">▸</span> {s.lastProbe.ref.replace(/^query:/, "")}
              </motion.div>
            )}
            {!running && vias.size > 0 && (
              <div className="mt-1.5 text-[11px] text-ink-400">
                Every vertex came from an installed GSQL query {vias.has("mcp") ? "called through the TigerGraph MCP server" : vias.has("rest") ? "called over REST++" : "replayed from the offline mirror"}.
              </div>
            )}
          </div>
        </Panel>

        <div
          ref={rightCol}
          onWheel={() => (userScrolled.current = true)}
          className="scroll-thin flex min-h-0 flex-col gap-3 overflow-y-auto pr-0.5"
        >
          <Panel title="Fraud probability" aside={<span className="text-[11px]">calibrated log-odds ledger</span>} bodyClass="px-4 pb-4 pt-3">
            <ProbabilityGauge p={pNow} prior={s.trigger ? prior : null} state={gaugeState} />
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-ink-700/70 pt-3">
              <div>
                <div className="text-[11px] text-ink-400">Verdict</div>
                <div className="mt-1">{s.decision || s.assessment ? <VerdictBadge verdict={(s.decision || s.assessment)!.verdict} /> : <span className="text-xs text-ink-500">pending</span>}</div>
              </div>
              <div className="min-w-0">
                <div className="text-[11px] text-ink-400">Pattern</div>
                <div className="mt-1 truncate text-[12.5px] font-medium text-ink-100">{s.decision?.pattern || s.assessment?.pattern ? patternLabel(s.decision?.pattern || s.assessment?.pattern) : <span className="text-ink-500">pending</span>}</div>
              </div>
              <div>
                <div className="text-[11px] text-ink-400">Exposure</div>
                <div className="mt-1 font-mono text-[12.5px] font-medium text-ink-100">{s.decision || s.assessment ? money((s.decision ?? s.assessment)!.exposure) : <span className="font-sans text-ink-500">pending</span>}</div>
              </div>
            </div>
            <div
              className={cx(
                "mt-3 rounded-lg border px-3 py-2 text-[12px] leading-5",
                stopMet ? "border-legit-line bg-legit-soft/50 text-ink-100" : "border-ink-700 bg-ink-900/50 text-ink-300",
              )}
            >
              <div className="flex items-center gap-2 font-medium">
                <span className={cx("h-2 w-2 rounded-full", stopMet ? "bg-legit" : running ? "bg-unsure animate-pulse" : "bg-ink-500")} />
                Stop rule, policy section 6: {stopMet ? "met" : "not met yet"}
              </div>
              <div className="mt-0.5 text-[11.5px] text-ink-300">
                {stopHi && <>p {pNow!.toFixed(2)} ≥ 0.85 on {fams.fraud.length} independent evidence families ({fams.fraud.join(", ")}).</>}
                {stopLo && <>p {pNow!.toFixed(2)} ≤ 0.15 on {fams.legit.length} independent evidence families ({fams.legit.join(", ")}).</>}
                {!stopHi && !stopLo && settledByReply && <>The verification reply settles the question.</>}
                {!stopMet && <>Stop when p ≥ 0.85 or ≤ 0.15 with two independent pieces of evidence, or when a reply settles it.</>}
              </div>
              {s.answer?.stop_reason && (
                <p className="mt-1.5 line-clamp-2 border-t border-ink-700/60 pt-1.5 text-[11.5px] text-ink-400" title={s.answer.stop_reason}>
                  {s.answer.stop_reason}
                </p>
              )}
            </div>
          </Panel>

          <Panel title="Evidence waterfall" aside={<span className="text-[11px]">log-odds, axis in probability</span>} bodyClass="px-2 pb-3 pt-2">
            {s.trigger ? (
              <EvidenceWaterfall
                prior={prior}
                contributions={contributions}
                p={s.decision?.p ?? s.assessment?.p ?? null}
                findings={s.findings}
                triggerLabel={triggerLabel(trigger).toLowerCase()}
                reply={
                  s.evidenceRequests.length && s.assessment && s.decision
                    ? {
                        label: s.evidenceRequests[0].branch === "confirm" ? "Customer confirms" : s.evidenceRequests[0].branch === "deny" ? "Customer denies" : "No reply",
                        from: s.assessment.p,
                        to: s.decision.p,
                        text: s.evidenceRequests[0].assumed_response,
                      }
                    : null
                }
              />
            ) : (
              <p className="px-2 py-6 text-center text-xs text-ink-400">The prior appears when the alert opens.</p>
            )}
            <div className="flex items-center gap-4 px-2 pt-1 text-[11px] text-ink-400">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-3 rounded-sm bg-fraud" /> toward fraud
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-3 rounded-sm bg-legit" /> toward legitimate
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-3 w-0 border-l border-dashed border-ink-300" /> stop thresholds
              </span>
            </div>
          </Panel>

          <div ref={nbaRef} className="-mt-3" />
          <Panel title="Next best action" aside={s.decision ? <span className="text-[11px]">{s.decision.status?.replace(/_/g, " ")}</span> : null} bodyClass="p-3">
            {!s.assessment ? (
              <p className="px-1 py-4 text-center text-xs leading-5 text-ink-400">Recommendations appear once the lead investigator assesses the evidence.</p>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between px-0.5 text-xs">
                  <span className="font-medium text-ink-200">{sameNba ? "Initial and final" : "Initial"}</span>
                  <span className="font-mono text-[11px] text-ink-400">p {s.assessment.p?.toFixed(2)}</span>
                </div>
                <ActionList actions={initial} compact />
                {s.evidenceRequests.map((r, i) => (
                  <div key={i}>
                    <FlowArrow label="evidence requested" />
                    <EvidenceRequestCard type={r.type} branch={r.branch} reply={r.assumed_response} step={r.asked_after_step} />
                  </div>
                ))}
                {!!final.length && !sameNba && (
                  <>
                    <FlowArrow label="recommend again" />
                    <div className="flex items-center justify-between px-0.5 text-xs">
                      <span className="font-medium text-ink-200">Final</span>
                      <span className="font-mono text-[11px]" style={{ color: bandColor(s.decision?.p ?? 0.5) }}>
                        p {s.decision?.p?.toFixed(2)}
                      </span>
                    </div>
                    {(() => {
                      const d = diffActions(initial, final);
                      return <ActionList actions={d} diffs={d.map((x) => x.diff)} compact />;
                    })()}
                  </>
                )}
                {sameNba && !s.evidenceRequests.length && (
                  <p className="px-0.5 text-[11.5px] text-ink-400">No evidence was requested, so the final recommendation equals the initial one.</p>
                )}
                {whatChanged && whatChanged !== "nothing" && (
                  <p className="rounded-md bg-ink-800 px-2.5 py-2 text-[11.5px] leading-5 text-ink-200">
                    <span className="font-medium text-ink-100">What changed: </span>
                    <RuleText text={whatChanged} />
                  </p>
                )}
                <div className="pt-2">
                  <BranchTree branches={s.assessment.branches} assumed={assumed} />
                </div>
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Radar, Download, CheckCircle2, CircleSlash, FlaskConical, Printer, Database, FileText, UserRound, Globe, ScrollText, Loader2, ShieldCheck, Link2,
} from "lucide-react";
import { useApi, useApiState, useLoad } from "../api";
import type { Answer, CaseDetail, ReproveResult, ToolCall } from "../api/types";
import { ActionList, ActionRow, BranchTree, EvidenceRequestCard, diffActions } from "../components/Actions";
import { Badge, Button, Empty, IdChip, Panel, Popover, RuleText, Skeleton, StatusBadge, VerdictBadge, cx } from "../components/ui";
import { actionLabel, downloadJson, money, patternLabel, shortDate, triggerLabel } from "../lib/format";
import { deviceLabel, entityType, parseRef, shortEntity } from "../lib/entities";
import { bandColor } from "../components/live/Gauge";

const SOURCE_META: Record<string, { label: string; icon: typeof Database; cls: string }> = {
  graph: { label: "Graph", icon: Database, cls: "border-tg-700 bg-tg-500/10 text-tg-300" },
  document: { label: "Policy doc", icon: ScrollText, cls: "border-[#3d3470] bg-[#1b1633] text-[#c4b5fd]" },
  customer: { label: "Customer", icon: UserRound, cls: "border-[#23466e] bg-[#0f1e30] text-[#8cc2ff]" },
  external: { label: "External", icon: Globe, cls: "border-ink-600 text-ink-200" },
};

function SourceChip({ s }: { s: string }) {
  const m = SOURCE_META[s] || SOURCE_META.external;
  return (
    <Badge className={m.cls}>
      <m.icon size={11} />
      {m.label}
    </Badge>
  );
}

function RefText({ ref_ }: { ref_: string }) {
  const p = parseRef(ref_);
  if (!p) return <span className="font-mono text-[11.5px] text-ink-300">{ref_}</span>;
  return (
    <span className="font-mono text-[11.5px] leading-5 text-ink-300">
      <span className="text-ink-500">query:</span>
      <span className="font-semibold text-ink-100">{p.name}</span>
      <span className="text-ink-500">(</span>
      {Object.entries(p.params).map(([k, v], i) => (
        <span key={k}>
          {i > 0 && <span className="text-ink-500">, </span>}
          <span className="text-ink-400">{k}=</span>
          <span className="text-ink-200">{Array.isArray(v) ? `[${v.length} ids]` : entityType(v) === "DeviceProfile" ? deviceLabel(v) : v}</span>
        </span>
      ))}
      <span className="text-ink-500">)</span>
    </span>
  );
}

function Reprove({ ref_, original }: { ref_: string; original?: ToolCall }) {
  const api = useApi();
  const { health } = useApiState();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ReproveResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setOpen(true);
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.reprove(ref_));
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }
  const live = api.mode === "live" && res && (res.via === "mcp" || res.via === "rest");
  const cols = res?.sample?.length ? Object.keys(res.sample[0]).slice(0, 5) : [];
  return (
    <div className="relative">
      <Button size="sm" variant="outline" onClick={run} className="hover:border-tg-600 hover:text-tg-300" title="Re-run this GSQL query on TigerGraph">
        <FlaskConical size={13} /> Re-prove
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} className="w-[460px] p-4">
        {busy && (
          <div className="flex items-center gap-2 text-[13px] text-ink-200">
            <Loader2 size={15} className="animate-spin text-tg-500" /> Re-running on {api.mode === "live" ? health?.graph || "TigerGraph" : "the saved run"}
          </div>
        )}
        {err && <p className="text-[13px] text-fraud">The query did not run: {err}</p>}
        {res && !busy && (
          <div>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className={cx("flex items-center gap-1.5 text-[13px] font-semibold", res.ok ? "text-legit" : "text-unsure")}>
                  {res.ok ? <CheckCircle2 size={15} /> : <CircleSlash size={15} />}
                  {live ? `Re-run live on ${health?.graph || "TigerGraph Savanna"}` : res.ok ? "Recorded result from the saved run" : "Could not re-prove"}
                </div>
                <div className="mt-0.5 font-mono text-[12px] text-ink-200">{res.query}</div>
              </div>
              <Badge className={res.via === "mcp" ? "border-tg-700 bg-tg-500/10 text-tg-300" : "border-ink-600 text-ink-300"}>
                via {res.via === "mcp" ? "MCP" : res.via === "rest" ? "REST++" : res.via}
              </Badge>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2">
              <div className="rounded-lg bg-ink-900 px-3 py-2">
                <div className="text-[11px] text-ink-400">Rows</div>
                <div className="font-mono text-[18px] font-semibold text-ink-100">{res.rows}</div>
              </div>
              <div className="rounded-lg bg-ink-900 px-3 py-2">
                <div className="text-[11px] text-ink-400">Latency</div>
                <div className="font-mono text-[18px] font-semibold text-ink-100">
                  {Number(res.ms).toFixed(res.ms < 10 ? 1 : 0)}
                  <span className="text-xs font-normal text-ink-400"> ms</span>
                </div>
              </div>
              <div className="rounded-lg bg-ink-900 px-3 py-2">
                <div className="text-[11px] text-ink-400">Original run</div>
                <div className="font-mono text-[18px] font-semibold text-ink-100">
                  {original ? original.rows : "—"}
                  {original && <span className="text-xs font-normal text-ink-400"> rows</span>}
                </div>
              </div>
            </div>
            {original && res.ok && (
              <p className={cx("mt-2 text-[12px]", original.rows === res.rows ? "text-legit" : "text-unsure")}>
                {original.rows === res.rows
                  ? "Same row count as when the agent cited it: the evidence reproduces."
                  : `Row count changed since the agent's run (${original.rows} then, ${res.rows} now): the graph has new data.`}
              </p>
            )}
            {!!cols.length && (
              <div className="scroll-thin mt-3 max-h-56 overflow-auto rounded-lg border border-ink-700">
                <table className="w-full text-left font-mono text-[10.5px]">
                  <thead className="sticky top-0 bg-ink-800 text-ink-400">
                    <tr>
                      {cols.map((c) => (
                        <th key={c} className="px-2 py-1.5 font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {res.sample.slice(0, 8).map((r, i) => (
                      <tr key={i} className="border-t border-ink-750">
                        {cols.map((c) => (
                          <td key={c} className="max-w-[140px] truncate px-2 py-1 text-ink-200" title={String(r[c] ?? "")}>
                            {typeof r[c] === "object" ? JSON.stringify(r[c]) : String(r[c] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {res.note && <p className="mt-2 text-[11.5px] leading-5 text-ink-400">{res.note}</p>}
            {res.error && <p className="mt-2 text-[11.5px] text-unsure">{res.error}</p>}
          </div>
        )}
      </Popover>
    </div>
  );
}

function SarDocument({ a, caseId, openedAt }: { a: Answer; caseId: string; openedAt: string }) {
  const s = a.sar;
  const kind = (id: string) => {
    const t = entityType(id);
    return t === "DeviceProfile" ? "Device profile" : t === "Card" ? "Card" : t === "Customer" ? "Customer" : t === "Transaction" ? "Transaction" : "Other";
  };
  return (
    <article className="sar-doc rounded-md bg-[#FCFCFA] text-[#15171A] shadow-[0_24px_60px_-30px_rgba(0,0,0,0.9)]">
      <header className="flex items-start justify-between gap-6 border-b-2 border-[#15171A] px-8 pb-4 pt-7">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#5B6068]">Regulatory filing, draft for approval</div>
          <h3 className="mt-1 text-[24px] font-bold tracking-[-0.01em]">Suspicious Activity Report</h3>
          <p className="mt-1 text-[12px] text-[#4A4F57]">Prepared by the FraudLens agent. Submission requires fraud manager (L2) sign-off, per policy section 2.</p>
        </div>
        <div className="text-right font-mono text-[11px] leading-5 text-[#4A4F57]">
          <div>
            Case <span className="font-semibold text-[#15171A]">{caseId}</span>
          </div>
          {a.case.graph_case_id && <div>Graph case {a.case.graph_case_id}</div>}
          <div>Opened {openedAt}</div>
          <div>Filing type: initial</div>
        </div>
      </header>

      <section className="grid grid-cols-3 border-b border-[#D5D7DA]">
        <Field label="Total suspicious amount" value={money(s.total_amount_usd)} mono />
        <Field label="Activity from" value={s.activity_dates[0] || "—"} mono />
        <Field label="Activity to" value={s.activity_dates[1] || s.activity_dates[0] || "—"} mono last />
      </section>
      <section className="grid grid-cols-3 border-b border-[#D5D7DA]">
        <Field label="Typology" value={patternLabel(a.case.pattern)} />
        <Field label="Transactions in episode" value={a.case.affected_txn_ids.join(", ") || "—"} mono />
        <Field label="Institution action" value={a.next_best_actions.final.map((x) => actionLabel(x.action)).slice(0, 3).join(", ")} last />
      </section>

      <section className="px-8 py-5">
        <h4 className="text-[12px] font-bold uppercase tracking-[0.1em] text-[#5B6068]">Part I. Subjects</h4>
        <table className="mt-2 w-full border-collapse text-[12px]">
          <thead>
            <tr className="border-b border-[#15171A] text-left text-[11px] text-[#5B6068]">
              <th className="w-10 py-1 font-semibold">#</th>
              <th className="w-36 py-1 font-semibold">Type</th>
              <th className="py-1 font-semibold">Identifier</th>
            </tr>
          </thead>
          <tbody>
            {s.subjects.map((x, i) => (
              <tr key={x} className="border-b border-[#E4E5E7]">
                <td className="py-1 font-mono text-[11px] text-[#5B6068]">{i + 1}</td>
                <td className="py-1">{kind(x)}</td>
                <td className="py-1 font-mono text-[11.5px]">{x}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="px-8 pb-5">
        <h4 className="text-[12px] font-bold uppercase tracking-[0.1em] text-[#5B6068]">Part II. Narrative</h4>
        <p className="mt-2 max-w-[78ch] text-[13px] leading-[1.7]">{s.narrative}</p>
      </section>

      <section className="px-8 pb-5">
        <h4 className="text-[12px] font-bold uppercase tracking-[0.1em] text-[#5B6068]">Part III. Basis for filing</h4>
        <p className="mt-2 max-w-[78ch] text-[13px] leading-[1.7]">{s.reason}</p>
      </section>

      <footer className="grid grid-cols-2 gap-10 border-t border-[#D5D7DA] px-8 pb-8 pt-6 text-[11px] text-[#5B6068]">
        <div>
          <div className="h-8 border-b border-[#15171A]" />
          <div className="mt-1">Fraud manager (L2), name and signature</div>
        </div>
        <div>
          <div className="h-8 border-b border-[#15171A]" />
          <div className="mt-1">Date of approval</div>
        </div>
      </footer>
    </article>
  );
}

function Field({ label, value, mono, last }: { label: string; value: string; mono?: boolean; last?: boolean }) {
  return (
    <div className={cx("px-8 py-3", !last && "border-r border-[#D5D7DA]")}>
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[#5B6068]">{label}</div>
      <div className={cx("mt-1 text-[13.5px] font-semibold", mono && "font-mono text-[12.5px]")}>{value}</div>
    </div>
  );
}

export default function CaseFileView() {
  const { caseId } = useParams();
  const nav = useNavigate();
  const { data, error, loading } = useLoad<CaseDetail>((a) => a.caseDetail(caseId!), [caseId]);

  useEffect(() => {
    if (!caseId) return;
    try {
      localStorage.setItem("fl.lastCase", caseId);
    } catch {}
  }, [caseId]);

  if (loading && !data)
    return (
      <div className="mx-auto max-w-[1560px] space-y-4 px-8 py-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  if (error || !data)
    return (
      <Empty title={`Case ${caseId} did not load`} icon={<FileText size={28} />}>
        {error || "No data"}. <Link to="/" className="text-tg-400 underline">Back to the queue</Link>
      </Empty>
    );

  const { row, answer: a, trace } = data;
  if (!a)
    return (
      <div className="mx-auto max-w-[1560px] px-8 py-6">
        <CaseHeaderBare caseId={row.case_id} row={row} />
        <div className="mt-6 rounded-xl border border-ink-700 bg-ink-850">
          <Empty title="This alert has no case file yet" icon={<FileText size={28} />}>
            The agent writes the case file when it finishes investigating. Start a live investigation to produce one.
            <div className="mt-4">
              <Button variant="primary" onClick={() => nav(`/live/${row.case_id}`)}>
                <Radar size={15} /> Investigate live
              </Button>
            </div>
          </Empty>
        </div>
      </div>
    );

  const c = a.case;
  const nba = a.next_best_actions;
  const diff = diffActions(nba.initial, nba.final);
  const changed = diff.some((d) => d.diff !== "kept") || nba.initial.length !== nba.final.length;
  const calls = trace?.tool_calls || [];
  const branches = trace?.events.find((e) => e.kind === "assessment")?.branches;
  const assumed = trace?.events.find((e) => e.kind === "evidence_request")?.branch;
  const written = c.written_to_graph && c.graph_case_id;

  return (
    <div className="mx-auto max-w-[1560px] px-8 py-6">
      {/* Header */}
      <div className="rounded-2xl border border-ink-700 bg-ink-850 px-6 py-5 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="font-mono text-[26px] font-semibold tracking-tight text-ink-100">{row.case_id}</h2>
              <StatusBadge status={c.status} />
              <Badge className="border-ink-600 bg-ink-800 text-ink-200">{triggerLabel(row.trigger_type)}</Badge>
              <span className="text-xs text-ink-400">opened {shortDate(row.opened_at)}, {row.opened_at.slice(11, 16)}</span>
            </div>
            <p className="mt-2 max-w-[92ch] text-[13px] leading-5 text-ink-300">{row.trigger_text}</p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" onClick={() => nav(`/live/${row.case_id}`)}>
              <Radar size={15} /> Replay investigation
            </Button>
            <Button variant="outline" onClick={() => downloadJson(`${row.case_id}.json`, a)}>
              <Download size={15} /> Download answer JSON
            </Button>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-4 border-t border-ink-700/70 pt-4 md:grid-cols-3 xl:grid-cols-6">
          <div>
            <div className="text-xs text-ink-400">Verdict</div>
            <div className="mt-1.5">
              <VerdictBadge verdict={c.verdict} size="lg" />
            </div>
          </div>
          <div>
            <div className="text-xs text-ink-400">Fraud probability</div>
            <div className="mt-0.5 flex items-baseline gap-2">
              <span className="text-[28px] font-semibold leading-8 tracking-[-0.02em]" style={{ color: bandColor(c.fraud_probability) }}>
                {c.fraud_probability.toFixed(2)}
              </span>
            </div>
          </div>
          <div>
            <div className="text-xs text-ink-400">Pattern</div>
            <div className="mt-1.5 text-[15px] font-semibold text-ink-100">{patternLabel(c.pattern)}</div>
          </div>
          <div>
            <div className="text-xs text-ink-400">Exposure</div>
            <div className="mt-1 font-mono text-[18px] font-semibold text-ink-100">{money(c.exposure_usd)}</div>
          </div>
          <div>
            <div className="text-xs text-ink-400">SAR</div>
            <div className={cx("mt-1.5 text-[14px] font-semibold", a.sar.file ? "text-tg-400" : "text-ink-300")}>{a.sar.file ? "File with regulator" : "Not required"}</div>
          </div>
          <div className="min-w-0">
            <div className="text-xs text-ink-400">Case memory in TigerGraph</div>
            {written ? (
              <div className="mt-1.5 flex items-center gap-1.5 text-[13px] font-medium text-legit">
                <CheckCircle2 size={15} /> Written as <span className="truncate font-mono">{c.graph_case_id}</span>
              </div>
            ) : (
              <div className="mt-1.5 flex items-center gap-1.5 text-[13px] text-ink-400">
                <CircleSlash size={14} /> Not written in this run
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-12 gap-5">
        {/* Main column */}
        <div className="col-span-12 space-y-5 xl:col-span-8">
          <Panel title="Summary">
            <p className="max-w-[80ch] text-[15px] leading-7 text-ink-100">{c.summary}</p>
            {c.pattern_description && (
              <div className="mt-4 rounded-xl border border-tg-700/70 bg-tg-500/[0.06] px-4 py-3">
                <div className="text-[12.5px] font-semibold text-tg-300">
                  {c.pattern === "undocumented" ? "Undocumented pattern, described by the agent (R9)" : `${patternLabel(c.pattern)} pattern`}
                </div>
                <p className="mt-1 max-w-[80ch] text-[13px] leading-6 text-ink-200">{c.pattern_description}</p>
              </div>
            )}
          </Panel>

          <Panel
            title="Evidence"
            aside={
              <span>
                {c.evidence.length} claims · {c.evidence.filter((e) => e.ref.startsWith("query:")).length} re-provable on TigerGraph
              </span>
            }
            bodyClass="p-0"
          >
            <ul className="divide-y divide-ink-750">
              {c.evidence.map((e, i) => {
                const orig = calls.find((t) => t.ref === e.ref);
                return (
                  <li key={i} className="grid grid-cols-[1fr_auto] gap-4 px-4 py-3.5">
                    <div className="min-w-0">
                      <div className="flex items-start gap-2.5">
                        <SourceChip s={e.source} />
                        <p className="text-[13.5px] leading-6 text-ink-100">{e.claim}</p>
                      </div>
                      <div className="mt-1.5 pl-[74px]">
                        <div className="break-words">
                          <RefText ref_={e.ref} />
                        </div>
                        {!!e.entity_ids.length && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {e.entity_ids.slice(0, 12).map((id) => (
                              <IdChip key={id} id={shortEntity(id)} tone={entityType(id) === "ClosedCase" ? "case" : c.connected_card_ids.includes(id) ? "ring" : "default"} />
                            ))}
                            {e.entity_ids.length > 12 && <span className="self-center font-mono text-[10.5px] text-ink-400">+{e.entity_ids.length - 12} more</span>}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="pt-0.5">{e.ref.startsWith("query:") && <Reprove ref_={e.ref} original={orig} />}</div>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel title="Next best action" aside={<span>{changed ? "changed after the evidence request" : "unchanged"}</span>}>
            {changed ? (
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <div>
                  <div className="mb-2 text-xs font-medium text-ink-300">Initial, before any requested evidence</div>
                  <ActionList actions={nba.initial} />
                </div>
                <div>
                  <div className="mb-2 text-xs font-medium text-ink-300">Final, after the assumed replies</div>
                  <ActionList actions={diff} diffs={diff.map((d) => d.diff)} />
                </div>
              </div>
            ) : (
              <div>
                <div className="mb-2 text-xs font-medium text-ink-300">Initial and final recommendation, in the order they happen</div>
                <ul className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                  {nba.final.map((x, i) => (
                    <ActionRow key={i} a={x} />
                  ))}
                </ul>
              </div>
            )}
            {!!a.evidence_requests.length && (
              <div className="mt-4 space-y-2">
                {a.evidence_requests.map((r, i) => (
                  <EvidenceRequestCard key={i} type={r.type} reply={r.assumed_response} step={r.asked_after_step} branch={assumed} />
                ))}
              </div>
            )}
            <div className="mt-4 rounded-lg bg-ink-800 px-3.5 py-2.5 text-[13px] leading-6 text-ink-200">
              <span className="font-medium text-ink-100">What changed: </span>
              {nba.what_changed === "nothing" ? "Nothing. No evidence was requested, so the final recommendation is the initial one." : <RuleText text={nba.what_changed} />}
            </div>
            {branches && (
              <div className="mt-4">
                <BranchTree branches={branches} assumed={assumed} />
              </div>
            )}
          </Panel>

          <div>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-[15px] font-semibold text-ink-100">Suspicious activity report</h3>
                <p className="mt-0.5 text-xs text-ink-400">
                  <RuleText text={a.sar.file ? "FILE_REPORT is routed L2: the draft waits for a fraud manager." : a.sar.reason || "No report required for this case."} />
                </p>
              </div>
              {a.sar.file && (
                <Button variant="outline" onClick={() => window.print()} className="no-print">
                  <Printer size={15} /> Print or save as PDF
                </Button>
              )}
            </div>
            {a.sar.file ? (
              <SarDocument a={a} caseId={row.case_id} openedAt={row.opened_at} />
            ) : (
              <div className="rounded-xl border border-ink-700 bg-ink-850 px-5 py-4 text-[13px] leading-6 text-ink-300">
                <RuleText text={a.sar.reason} />
              </div>
            )}
          </div>
        </div>

        {/* Side column */}
        <div className="col-span-12 space-y-5 xl:col-span-4">
          <Panel title="Why the agent stopped">
            <p className="text-[13px] leading-6 text-ink-200">
              <RuleText text={a.stop_reason} />
            </p>
          </Panel>

          <Panel title="Fraud episode" aside={<span>{c.affected_txn_ids.length} transactions</span>}>
            <div className="flex flex-wrap gap-1.5">
              {c.affected_txn_ids.map((t) => (
                <span key={t} className="inline-flex items-center gap-1">
                  <IdChip id={t} tone="fraud" />
                  {t === c.first_suspicious_txn_id && <span className="text-[10.5px] text-ink-400">first</span>}
                  {t === row.flagged_txn_id && <span className="text-[10.5px] text-tg-400">flagged</span>}
                </span>
              ))}
              {!c.affected_txn_ids.length && <span className="text-xs text-ink-400">No fraudulent transactions identified.</span>}
            </div>
          </Panel>

          <Panel
            title={
              <span className="inline-flex items-center gap-2">
                <Link2 size={14} className="text-fraud" /> Connected cards
              </span>
            }
            aside={<span>{c.connected_card_ids.length} cards</span>}
          >
            {!!c.connected_device_profiles?.length && (
              <div className="mb-3 space-y-1.5">
                {c.connected_device_profiles.map((d) => (
                  <div key={d} className="rounded-lg border border-[#1d5a52] bg-[#0b2421] px-3 py-2">
                    <div className="text-[11px] text-[#8DEBDD]">Shared device profile</div>
                    <div className="mt-0.5 break-words font-mono text-[11.5px] leading-5 text-ink-100">{d}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {c.connected_card_ids.map((id) => (
                <IdChip key={id} id={id} tone="ring" />
              ))}
              {!c.connected_card_ids.length && <span className="text-xs text-ink-400">No other cards connected.</span>}
            </div>
            {c.connected_card_ids.length > 0 && (
              <p className="mt-3 text-[11.5px] leading-5 text-ink-400">
                <RuleText text="Placed under monitoring as MONITOR_CONNECTED_CARDS under R6." />
              </p>
            )}
          </Panel>

          <Panel title="Similar prior cases" aside={<span>retrieved from case memory</span>}>
            <div className="flex flex-wrap gap-1.5">
              {c.similar_prior_cases.map((id) => (
                <IdChip key={id} id={id} tone="case" />
              ))}
              {!c.similar_prior_cases.length && <span className="text-xs text-ink-400">No similar closed cases.</span>}
            </div>
            <p className="mt-3 text-[11.5px] leading-5 text-ink-400">Graph-filtered vector search over closed cases that share this case's cards and devices.</p>
          </Panel>

          {trace?.critic && (
            <Panel
              title={
                <span className="inline-flex items-center gap-2">
                  <ShieldCheck size={14} className="text-ink-200" /> Compliance review
                </span>
              }
            >
              <div className={cx("flex items-center gap-1.5 text-[13px] font-medium", trace.critic.agree ? "text-legit" : "text-unsure")}>
                {trace.critic.agree ? <CheckCircle2 size={15} /> : <CircleSlash size={15} />}
                {trace.critic.agree ? "Agrees with the decision" : "Raised issues"}
              </div>
              {!!trace.critic.issues.length && (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-[12.5px] leading-5 text-ink-300">
                  {trace.critic.issues.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              )}
            </Panel>
          )}
        </div>
      </div>

      {/* Footer stats */}
      <div className="mt-6 flex flex-wrap items-center gap-x-8 gap-y-2 rounded-xl border border-ink-700 bg-ink-850 px-5 py-3 text-[12.5px] text-ink-300">
        <span>
          <span className="font-mono font-semibold text-ink-100">{a.tool_calls}</span> TigerGraph queries
        </span>
        <span>
          <span className="font-mono font-semibold text-ink-100">{a.tokens.toLocaleString("en-US")}</span> LLM tokens
        </span>
        <span>
          <span className="font-mono font-semibold text-ink-100">{a.latency_s.toFixed(1)} s</span> end to end
        </span>
        {calls.length > 0 && (
          <span>
            <span className="font-mono font-semibold text-ink-100">{calls.reduce((s, x) => s + x.ms, 0).toFixed(0)} ms</span> total graph time
          </span>
        )}
        <span className="ml-auto text-ink-500">
          Answer format per the Hacker House Goa README: case, SAR, next best actions.
        </span>
      </div>
    </div>
  );
}

function CaseHeaderBare({ caseId, row }: { caseId: string; row: CaseDetail["row"] }) {
  return (
    <div className="rounded-2xl border border-ink-700 bg-ink-850 px-6 py-5">
      <div className="flex items-center gap-3">
        <h2 className="font-mono text-[26px] font-semibold tracking-tight text-ink-100">{caseId}</h2>
        <StatusBadge status={row.status} />
        <Badge className="border-ink-600 bg-ink-800 text-ink-200">{triggerLabel(row.trigger_type)}</Badge>
      </div>
      <p className="mt-2 text-[13px] text-ink-300">{row.trigger_text}</p>
    </div>
  );
}

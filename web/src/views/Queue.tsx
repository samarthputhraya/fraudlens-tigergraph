import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Gauge as GaugeIcon, MessageSquareWarning, UserSearch, Bot, Radar, Plus, Search, FileCheck2, ChevronRight } from "lucide-react";
import { useApi, useLoad } from "../api";
import type { CaseRow } from "../api/types";
import { Badge, Button, Dialog, Empty, Segmented, Skeleton, StatusBadge, VerdictBadge, cx, useToast } from "../components/ui";
import { money, normVerdict, patternLabel, shortDate, shortTime, triggerLabel } from "../lib/format";

const TRIGGER_ICON: Record<string, typeof GaugeIcon> = {
  risk_score: GaugeIcon,
  customer_report: MessageSquareWarning,
  analyst_request: UserSearch,
  autonomous: Bot,
};

function TriggerChip({ t }: { t: string }) {
  const Icon = TRIGGER_ICON[t] || Radar;
  return (
    <Badge className="border-ink-600 bg-ink-800 text-ink-200">
      <Icon size={12} className="text-ink-300" />
      {triggerLabel(t)}
    </Badge>
  );
}

function ScoreCell({ v }: { v: CaseRow["risk_score"] }) {
  const n = v === "" || v == null ? null : Number(v);
  if (n == null || Number.isNaN(n)) return <span className="text-xs text-ink-500">no score</span>;
  const color = n >= 0.85 ? "#EF5A50" : n >= 0.5 ? "#EDB341" : "#96A1B3";
  return (
    <div className="flex items-center gap-2">
      <span className="w-8 font-mono text-[12.5px] tabular-nums text-ink-100">{n.toFixed(2)}</span>
      <span className="relative h-1 w-12 overflow-hidden rounded-full bg-ink-700">
        <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${n * 100}%`, background: color }} />
      </span>
    </div>
  );
}

type StatusF = "all" | "new" | "open" | "escalated" | "closed";
type VerdictF = "all" | "fraud" | "legitimate" | "uncertain" | "none";
type TriggerF = "all" | "risk_score" | "customer_report" | "analyst_request" | "autonomous";

export default function QueueView() {
  const api = useApi();
  const nav = useNavigate();
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((a) => a.cases());
  const [status, setStatus] = useState<StatusF>("all");
  const [verdict, setVerdict] = useState<VerdictF>("all");
  const [trigger, setTrigger] = useState<TriggerF>("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [txn, setTxn] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const rows = data || [];
  const matchStatus = (r: CaseRow, s: StatusF) => s === "all" || (s === "closed" ? r.status.startsWith("closed") : r.status === s);
  const matchVerdict = (r: CaseRow, v: VerdictF) => v === "all" || (v === "none" ? !normVerdict(r.verdict) : normVerdict(r.verdict) === v);
  const matchTrigger = (r: CaseRow, t: TriggerF) => t === "all" || r.trigger_type === t;
  const matchQ = (r: CaseRow) => {
    if (!q.trim()) return true;
    const s = q.trim().toLowerCase();
    return [r.case_id, r.flagged_txn_id, r.card_id, r.customer_id, r.pattern || "", r.trigger_text].some((x) => (x || "").toLowerCase().includes(s));
  };
  const filtered = rows.filter((r) => matchStatus(r, status) && matchVerdict(r, verdict) && matchTrigger(r, trigger) && matchQ(r));

  const counts = useMemo(() => {
    const c = (f: (r: CaseRow) => boolean) => rows.filter(f).length;
    return {
      status: {
        all: rows.length, new: c((r) => r.status === "new"), open: c((r) => r.status === "open"),
        escalated: c((r) => r.status === "escalated"), closed: c((r) => r.status.startsWith("closed")),
      },
      verdict: {
        all: rows.length, fraud: c((r) => normVerdict(r.verdict) === "fraud"), legitimate: c((r) => normVerdict(r.verdict) === "legitimate"),
        uncertain: c((r) => normVerdict(r.verdict) === "uncertain"), none: c((r) => !normVerdict(r.verdict)),
      },
      trigger: {
        all: rows.length, risk_score: c((r) => r.trigger_type === "risk_score"), customer_report: c((r) => r.trigger_type === "customer_report"),
        analyst_request: c((r) => r.trigger_type === "analyst_request"), autonomous: c((r) => r.trigger_type === "autonomous"),
      },
    };
  }, [rows]);

  const exposure = rows.reduce((s, r) => s + (normVerdict(r.verdict) === "fraud" ? r.exposure_usd || 0 : 0), 0);
  const txnOk = /^\d{5,9}$/.test(txn.trim());

  async function startInvestigation() {
    if (!txnOk) return;
    setBusy(true);
    try {
      const row = await api.investigate(txn.trim(), note.trim());
      setOpen(false);
      setTxn("");
      setNote("");
      toast({ tone: "success", title: `Opened ${row.case_id}`, body: `Investigating transaction ${row.flagged_txn_id} live.` });
      nav(`/live/${row.case_id}`);
    } catch (e: any) {
      toast({ tone: "error", title: "Could not open the investigation", body: String(e?.message || e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1680px] px-8 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.015em] text-ink-100">Alert queue</h2>
          <p className="mt-1 text-[13px] text-ink-400">
            {rows.length} alerts, oldest first. Open a row for its case file, or watch the agents investigate it live.
          </p>
        </div>
        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="text-xs text-ink-400">Confirmed fraud exposure</div>
            <div className="text-lg font-semibold text-ink-100">{money(exposure)}</div>
          </div>
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus size={16} /> New investigation
          </Button>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Segmented<StatusF>
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: "All statuses", count: counts.status.all },
            { value: "new", label: "New", count: counts.status.new },
            { value: "open", label: "Open", count: counts.status.open },
            { value: "escalated", label: "Escalated", count: counts.status.escalated },
            { value: "closed", label: "Closed", count: counts.status.closed },
          ]}
        />
        <Segmented<VerdictF>
          value={verdict}
          onChange={setVerdict}
          options={[
            { value: "all", label: "Any verdict" },
            { value: "fraud", label: <><Dot c="#EF5A50" />Fraud</>, count: counts.verdict.fraud },
            { value: "legitimate", label: <><Dot c="#3CC585" />Legitimate</>, count: counts.verdict.legitimate },
            { value: "uncertain", label: <><Dot c="#EDB341" />Uncertain</>, count: counts.verdict.uncertain },
            { value: "none", label: "Not investigated", count: counts.verdict.none },
          ]}
        />
        <Segmented<TriggerF>
          value={trigger}
          onChange={setTrigger}
          options={[
            { value: "all", label: "Any trigger" },
            { value: "risk_score", label: "Risk score", count: counts.trigger.risk_score },
            { value: "customer_report", label: "Customer report", count: counts.trigger.customer_report },
            { value: "analyst_request", label: "Analyst", count: counts.trigger.analyst_request },
            { value: "autonomous", label: "Autonomous", count: counts.trigger.autonomous },
          ]}
        />
        <label className="ml-auto flex h-8 w-64 items-center gap-2 rounded-lg border border-ink-700 bg-ink-900 px-2.5 text-ink-400 focus-within:border-tg-500">
          <Search size={14} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Case, transaction, card"
            className="w-full bg-transparent text-[13px] text-ink-100 placeholder:text-ink-500 focus:outline-none"
          />
        </label>
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-ink-700 bg-ink-850 shadow-panel">
        <table className="w-full table-fixed border-collapse text-left">
          <colgroup>
            <col className="w-[30%]" />
            <col className="w-[9%]" />
            <col className="w-[11%]" />
            <col className="w-[8%]" />
            <col className="w-[9%]" />
            <col className="w-[10%]" />
            <col className="w-[9%]" />
            <col className="w-[7%]" />
            <col className="w-[4%]" />
            <col className="w-[13%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-ink-700 text-xs text-ink-400">
              <th className="px-4 py-2.5 font-medium">Case</th>
              <th className="px-2 py-2.5 font-medium">Opened</th>
              <th className="px-2 py-2.5 font-medium">Trigger</th>
              <th className="px-2 py-2.5 font-medium">Model score</th>
              <th className="px-2 py-2.5 font-medium">Status</th>
              <th className="px-2 py-2.5 font-medium">Verdict</th>
              <th className="px-2 py-2.5 font-medium">Pattern</th>
              <th className="px-2 py-2.5 text-right font-medium">Exposure</th>
              <th className="px-2 py-2.5 text-center font-medium">SAR</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {loading &&
              !data &&
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-b border-ink-750">
                  <td colSpan={10} className="px-4 py-3">
                    <Skeleton className="h-5 w-full" />
                  </td>
                </tr>
              ))}
            {filtered.map((r) => {
              const v = normVerdict(r.verdict);
              return (
                <tr
                  key={r.case_id}
                  onClick={() => nav(`/case/${r.case_id}`)}
                  className={cx(
                    "group cursor-pointer border-b border-ink-750 transition-colors last:border-0 hover:bg-ink-800",
                    v === "fraud" && "shadow-[inset_3px_0_0_0_#EF5A50]",
                    v === "uncertain" && "shadow-[inset_3px_0_0_0_#EDB341]",
                    v === "legitimate" && "shadow-[inset_3px_0_0_0_#3CC585]",
                  )}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[13px] font-semibold text-ink-100">{r.case_id}</span>
                      <span className="font-mono text-[11px] text-ink-400">txn {r.flagged_txn_id}</span>
                      {r.card_id && <span className="font-mono text-[11px] text-ink-500">{r.card_id}</span>}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-ink-400" title={r.trigger_text}>
                      {r.trigger_text}
                    </div>
                  </td>
                  <td className="px-2 py-3">
                    <div className="text-[12.5px] text-ink-200">{shortDate(r.opened_at)}</div>
                    <div className="font-mono text-[11px] text-ink-500">{shortTime(r.opened_at)}</div>
                  </td>
                  <td className="px-2 py-3">
                    <TriggerChip t={r.trigger_type} />
                  </td>
                  <td className="px-2 py-3">
                    <ScoreCell v={r.risk_score} />
                  </td>
                  <td className="px-2 py-3">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-2 py-3">
                    <VerdictBadge verdict={r.verdict} p={r.fraud_probability} />
                  </td>
                  <td className="truncate px-2 py-3 text-[12.5px] text-ink-200">{v ? patternLabel(r.pattern) : <span className="text-ink-500">—</span>}</td>
                  <td className="px-2 py-3 text-right font-mono text-[12.5px] tabular-nums text-ink-100">
                    {r.exposure_usd != null && v ? money(r.exposure_usd) : <span className="text-ink-500">—</span>}
                  </td>
                  <td className="px-2 py-3 text-center">
                    {r.sar ? (
                      <span title="Suspicious activity report filed" className="inline-flex text-tg-400">
                        <FileCheck2 size={16} />
                      </span>
                    ) : (
                      <span className="text-ink-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        className="group-hover:border-tg-600 group-hover:text-tg-300"
                        onClick={(e) => {
                          e.stopPropagation();
                          nav(`/live/${r.case_id}`);
                        }}
                      >
                        <Radar size={13} /> Investigate live
                      </Button>
                      <ChevronRight size={16} className="text-ink-600 group-hover:text-ink-300" />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!loading && !error && !filtered.length && (
          <Empty title="No alerts match these filters">Clear a filter or search for a different case, transaction or card.</Empty>
        )}
        {error && (
          <Empty title="The queue did not load">
            {error}.{" "}
            <button className="text-tg-400 underline" onClick={reload}>
              Retry
            </button>
          </Empty>
        )}
      </div>

      <Dialog open={open} onClose={() => setOpen(false)} title="New investigation">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            startInvestigation();
          }}
          className="space-y-4"
        >
          <label className="block">
            <span className="text-xs font-medium text-ink-300">Transaction ID</span>
            <input
              autoFocus
              value={txn}
              onChange={(e) => setTxn(e.target.value.replace(/\s/g, ""))}
              placeholder="3478561"
              inputMode="numeric"
              className="mt-1.5 h-10 w-full rounded-lg border border-ink-600 bg-ink-900 px-3 font-mono text-sm text-ink-100 placeholder:text-ink-500 focus:border-tg-500 focus:outline-none"
            />
            {txn && !txnOk && <span className="mt-1 block text-xs text-unsure">Enter the numeric transaction ID, for example 3478561.</span>}
          </label>
          <label className="block">
            <span className="text-xs font-medium text-ink-300">Analyst note</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="What made you look at this transaction?"
              className="mt-1.5 w-full resize-none rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm leading-6 text-ink-100 placeholder:text-ink-500 focus:border-tg-500 focus:outline-none"
            />
          </label>
          <p className="text-xs leading-5 text-ink-400">
            The lead investigator opens an analyst-request case, briefs the four specialists and streams every TigerGraph query to the live view.
          </p>
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={!txnOk || busy}>
              <Radar size={15} /> {busy ? "Opening case" : "Start investigation"}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}

function Dot({ c }: { c: string }) {
  return <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: c }} />;
}

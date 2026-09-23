import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bot, UserCheck, ShieldAlert, Check, X, Lock, Stamp } from "lucide-react";
import { useApi, useLoad } from "../api";
import type { Approval } from "../api/types";
import { Badge, Button, Empty, Panel, RouteBadge, RuleText, Segmented, Skeleton, cx, useToast } from "../components/ui";
import { actionLabel, money } from "../lib/format";

type Role = "agent" | "team_lead" | "fraud_manager";

const ROLES: Record<Role, { label: string; short: string; icon: typeof Bot; can: string[] }> = {
  agent: { label: "Agent", short: "Agent", icon: Bot, can: ["auto"] },
  team_lead: { label: "Team lead (L1)", short: "Team lead", icon: UserCheck, can: ["auto", "L1"] },
  fraud_manager: { label: "Fraud manager (L2)", short: "Fraud manager", icon: ShieldAlert, can: ["auto", "L1", "L2"] },
};

const POLICY = [
  {
    route: "auto",
    who: "The agent executes these itself",
    actions: "Allow, monitor card, monitor connected cards, warn or verify with customer, step-up auth, generate report, create case, escalate, close as no fraud",
  },
  { route: "L1", who: "A team lead approves", actions: "Decline transaction; block card when exposure is $2,500 or less" },
  { route: "L2", who: "A fraud manager approves", actions: "Block card above $2,500; block all cards; file a suspicious activity report" },
];

function statusText(s: string) {
  if (s === "pending_approval_team_lead") return "Waiting for a team lead";
  if (s === "pending_approval_fraud_manager") return "Waiting for a fraud manager";
  const m = /^(approved|rejected)_by_(team_lead|fraud_manager)$/.exec(s);
  if (m) return `${m[1] === "approved" ? "Approved" : "Rejected"} by ${m[2] === "team_lead" ? "team lead" : "fraud manager"}`;
  return s.replace(/_/g, " ");
}

export default function ApprovalsView() {
  const api = useApi();
  const toast = useToast();
  const { data, loading, error, reload, setData } = useLoad((a) => a.approvals());
  const [role, setRole] = useState<Role>(() => {
    try {
      return (localStorage.getItem("fl.role") as Role) || "team_lead";
    } catch {
      return "team_lead";
    }
  });
  const [tab, setTab] = useState<"pending" | "decided">("pending");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem("fl.role", role);
    } catch {}
  }, [role]);

  const items = data || [];
  const pending = items.filter((x) => x.status.startsWith("pending"));
  const decided = items.filter((x) => !x.status.startsWith("pending"));
  const shown = tab === "pending" ? pending : decided;
  const byCase = useMemo(() => {
    const m = new Map<string, Approval[]>();
    for (const a of shown) m.set(a.case_id, [...(m.get(a.case_id) || []), a]);
    return [...m.entries()];
  }, [shown]);

  async function decide(a: Approval, approve: boolean) {
    const verb = approve ? "approve" : "reject";
    if (role === "agent") {
      toast({
        tone: "error",
        title: `The agent cannot ${verb} ${actionLabel(a.action).toLowerCase()}`,
        body: `${a.action} is routed ${a.route}. Only auto actions run without a human (policy section 2). Switch to a human role to decide it.`,
      });
      return;
    }
    setBusy(a.action_id);
    try {
      const r = await api.decide(a.action_id, approve, role);
      if (!r.ok) {
        toast({ tone: "error", title: "Permission denied", body: r.error || `${ROLES[role].short} cannot decide ${a.route} actions.` });
        return;
      }
      toast({
        tone: "success",
        title: `${approve ? "Approved" : "Rejected"}: ${actionLabel(a.action)} on ${a.case_id}`,
        body: `${a.action_id} is now ${statusText(r.status).toLowerCase()}.`,
      });
      setData((xs) => (xs || []).map((x) => (x.action_id === a.action_id ? { ...x, status: r.status } : x)));
    } catch (e: any) {
      toast({ tone: "error", title: "The decision was not saved", body: String(e?.message || e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-[1560px] px-8 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[22px] font-semibold tracking-[-0.015em] text-ink-100">Approval inbox</h2>
          <p className="mt-1 text-[13px] text-ink-400">The agent recommends; people approve. Every L1 and L2 action waits here for the right role.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-ink-400">Acting as</span>
          <Segmented<Role>
            value={role}
            onChange={setRole}
            options={(Object.keys(ROLES) as Role[]).map((r) => {
              const R = ROLES[r];
              return { value: r, label: <><R.icon size={13} />{R.label}</> };
            })}
          />
        </div>
      </div>

      <div className="mt-5 grid grid-cols-12 gap-5">
        <div className="col-span-12 xl:col-span-8">
          <div className="mb-3 flex items-center gap-3">
            <Segmented
              value={tab}
              onChange={(v) => setTab(v as "pending" | "decided")}
              options={[
                { value: "pending", label: "Pending", count: pending.length },
                { value: "decided", label: "Decided", count: decided.length },
              ]}
            />
          </div>

          {loading && !data && <Skeleton className="h-40 w-full" />}
          {error && <Empty title="The inbox did not load">{error}</Empty>}
          {!loading && !error && !shown.length && (
            <div className="rounded-xl border border-ink-700 bg-ink-850">
              <Empty icon={<Stamp size={26} />} title={tab === "pending" ? "Nothing is waiting for approval" : "No decisions yet"}>
                {tab === "pending" ? "New L1 and L2 recommendations land here as the agent closes cases." : "Approve or reject a pending action and it moves here."}
              </Empty>
            </div>
          )}

          <div className="space-y-4">
            {byCase.map(([cid, xs]) => (
              <section key={cid} className="overflow-hidden rounded-xl border border-ink-700 bg-ink-850 shadow-panel">
                <header className="flex items-center justify-between border-b border-ink-700/70 px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    <Link to={`/case/${cid}`} className="font-mono text-[14px] font-semibold text-ink-100 hover:text-tg-400">
                      {cid}
                    </Link>
                    <span className="text-xs text-ink-400">exposure {money(xs[0].exposure_usd)}</span>
                  </div>
                  <Link to={`/case/${cid}`} className="text-xs text-ink-400 hover:text-ink-200">
                    Open case file
                  </Link>
                </header>
                <ul className="divide-y divide-ink-750">
                  {xs.map((a) => {
                    const allowed = ROLES[role].can.includes(a.route);
                    const pend = a.status.startsWith("pending");
                    return (
                      <li key={a.action_id} className="grid grid-cols-[1fr_auto] items-center gap-4 px-4 py-3.5">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[14px] font-semibold text-ink-100">{actionLabel(a.action)}</span>
                            <span className="font-mono text-[11px] text-ink-500">{a.action}</span>
                            <RouteBadge route={a.route} />
                            <span className="font-mono text-[10.5px] text-ink-500">{a.action_id}</span>
                          </div>
                          <p className="mt-1 max-w-[90ch] text-[12.5px] leading-5 text-ink-300">
                            <RuleText text={a.reason} />
                          </p>
                          <div className={cx("mt-1 text-[11.5px]", pend ? "text-ink-400" : a.status.startsWith("approved") ? "text-legit" : "text-fraud")}>
                            {statusText(a.status)}
                          </div>
                        </div>
                        {pend && (
                          <div className="flex items-center gap-2">
                            {!allowed && (
                              <span className="inline-flex items-center gap-1 text-[11px] text-ink-500" title="This role cannot decide this route">
                                <Lock size={12} /> needs {a.route === "L2" ? "fraud manager" : "team lead"}
                              </span>
                            )}
                            <Button size="sm" variant="danger" disabled={busy === a.action_id} onClick={() => decide(a, false)}>
                              <X size={13} /> Reject
                            </Button>
                            <Button size="sm" variant="success" disabled={busy === a.action_id} onClick={() => decide(a, true)}>
                              <Check size={13} /> Approve
                            </Button>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
          {!!items.length && (
            <button onClick={reload} className="mt-3 text-xs text-ink-400 hover:text-ink-200">
              Refresh
            </button>
          )}
        </div>

        <div className="col-span-12 space-y-5 xl:col-span-4">
          <Panel title="Permission model" aside={<span>Fraud Policy section 2</span>}>
            <ul className="space-y-3">
              {POLICY.map((p) => {
                const can = ROLES[role].can.includes(p.route);
                return (
                  <li key={p.route} className={cx("rounded-lg border px-3 py-2.5", can ? "border-ink-600 bg-ink-800/70" : "border-ink-750 bg-ink-900/40")}>
                    <div className="flex items-center justify-between gap-2">
                      <RouteBadge route={p.route} />
                      <span className={cx("inline-flex items-center gap-1 text-[11.5px]", can ? "text-legit" : "text-ink-500")}>
                        {can ? <Check size={12} /> : <Lock size={12} />}
                        {can ? (p.route === "auto" ? "runs automatically" : `${ROLES[role].short} can decide`) : `${ROLES[role].short} cannot decide`}
                      </span>
                    </div>
                    <div className="mt-1.5 text-[12.5px] font-medium text-ink-100">{p.who}</div>
                    <div className="mt-0.5 text-[12px] leading-5 text-ink-400">{p.actions}</div>
                  </li>
                );
              })}
            </ul>
            <p className="mt-3 text-[11.5px] leading-5 text-ink-400">
              A fraud manager can also decide L1 actions. Every decision is recorded against the action in the case graph.
            </p>
          </Panel>
          <Panel title="Queue load">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-xs text-ink-400">Team lead (L1)</div>
                <div className="mt-0.5 text-[22px] font-semibold text-unsure">{pending.filter((x) => x.route === "L1").length}</div>
              </div>
              <div>
                <div className="text-xs text-ink-400">Fraud manager (L2)</div>
                <div className="mt-0.5 text-[22px] font-semibold text-fraud">{pending.filter((x) => x.route === "L2").length}</div>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(pending.reduce<Record<string, number>>((m, x) => ((m[x.action] = (m[x.action] || 0) + 1), m), {})).map(([k, n]) => (
                <Badge key={k} className="border-ink-600 text-ink-200">
                  {actionLabel(k)} <span className="font-mono text-ink-400">{n}</span>
                </Badge>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

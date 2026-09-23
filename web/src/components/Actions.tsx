import { ArrowDown, MessageCircleQuestion, GitBranch, Check } from "lucide-react";
import type { Action } from "../api/types";
import { actionLabel } from "../lib/format";
import { RouteBadge, RuleText, cx } from "./ui";

export type Diff = "added" | "removed" | "kept";

export function diffActions(initial: Action[], final: Action[]) {
  const i = new Set(initial.map((a) => a.action));
  const f = new Set(final.map((a) => a.action));
  const rows: (Action & { diff: Diff })[] = final.map((a) => ({ ...a, diff: i.has(a.action) ? "kept" : "added" }));
  for (const a of initial) if (!f.has(a.action)) rows.push({ ...a, diff: "removed" });
  return rows;
}

export function ActionRow({ a, diff, compact }: { a: Action; diff?: Diff; compact?: boolean }) {
  return (
    <li
      className={cx(
        "rounded-lg border px-3 py-2",
        diff === "added" ? "border-legit-line/70 bg-legit-soft/40" : diff === "removed" ? "border-ink-700 bg-ink-900/40 opacity-60" : "border-ink-700 bg-ink-800/60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {diff === "added" && <span className="font-mono text-[11px] font-bold text-legit">+</span>}
          {diff === "removed" && <span className="font-mono text-[11px] font-bold text-ink-400">−</span>}
          <span className={cx("truncate text-[13px] font-medium text-ink-100", diff === "removed" && "line-through decoration-ink-400")}>{actionLabel(a.action)}</span>
          {!compact && <span className="hidden font-mono text-[10.5px] text-ink-500 xl:inline">{a.action}</span>}
        </div>
        <RouteBadge route={a.route} />
      </div>
      {a.reason && (
        <p className={cx("mt-1 text-[11.5px] leading-[1.15rem] text-ink-300", compact && "line-clamp-2")} title={compact ? a.reason : undefined}>
          <RuleText text={a.reason} />
        </p>
      )}
    </li>
  );
}

export function ActionList({ actions, compact, diffs }: { actions: Action[]; compact?: boolean; diffs?: Diff[] }) {
  if (!actions.length) return <p className="text-xs text-ink-400">No actions recommended.</p>;
  return (
    <ul className="space-y-1.5">
      {actions.map((a, i) => (
        <ActionRow key={`${a.action}-${i}`} a={a} compact={compact} diff={diffs?.[i]} />
      ))}
    </ul>
  );
}

const BRANCHES: { key: string; label: string; hint: string }[] = [
  { key: "confirm", label: "Customer confirms", hint: "R3" },
  { key: "deny", label: "Customer denies", hint: "R2" },
  { key: "no_reply", label: "No reply in 24h", hint: "R4" },
];

export function BranchTree({ branches, assumed }: { branches: Record<string, Action[]> | undefined; assumed?: string }) {
  if (!branches || !Object.keys(branches).length) return null;
  const sig = (xs: Action[] = []) => xs.map((a) => `${a.action}/${a.route}`).join(",");
  const same = BRANCHES.every((b) => sig(branches[b.key]) === sig(branches.confirm));
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs text-ink-300">
        <GitBranch size={13} className="text-ink-400" />
        Counterfactual branches
        {same && <span className="text-ink-500">· every reply leads to the same actions</span>}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {BRANCHES.map((b) => {
          const on = assumed === b.key;
          const xs = branches[b.key] || [];
          return (
            <div
              key={b.key}
              className={cx(
                "relative rounded-lg border p-2",
                on ? "border-tg-500/80 bg-tg-500/[0.07] shadow-glow" : "border-ink-700 bg-ink-900/40",
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <span className={cx("text-[11.5px] font-medium", on ? "text-tg-300" : "text-ink-200")}>{b.label}</span>
                <span className="font-mono text-[10px] text-ink-500">{b.hint}</span>
              </div>
              {on && (
                <span className="mt-0.5 inline-flex items-center gap-1 text-[10.5px] text-tg-400">
                  <Check size={11} /> assumed reply
                </span>
              )}
              <ul className="mt-1.5 space-y-1">
                {xs.map((a, i) => (
                  <li key={i} className="flex items-center justify-between gap-1 text-[11px] leading-4">
                    <span className="truncate text-ink-200">{actionLabel(a.action)}</span>
                    <span
                      className={cx(
                        "shrink-0 font-mono text-[9.5px]",
                        a.route === "L2" ? "text-fraud" : a.route === "L1" ? "text-unsure" : "text-ink-500",
                      )}
                    >
                      {a.route}
                    </span>
                  </li>
                ))}
                {!xs.length && <li className="text-[11px] text-ink-500">none</li>}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function EvidenceRequestCard({ type, branch, reply, step }: { type: string; branch?: string; reply: string; step?: number }) {
  const bl = BRANCHES.find((b) => b.key === branch)?.label;
  return (
    <div className="relative rounded-lg border border-dashed border-tg-600/70 bg-tg-500/[0.05] px-3 py-2.5">
      <div className="flex items-center gap-2 text-[12px] font-medium text-tg-300">
        <MessageCircleQuestion size={14} />
        {actionLabel(type.toUpperCase())}
        {step != null && <span className="font-normal text-ink-400">after step {step}</span>}
      </div>
      <p className="mt-1 text-[12px] leading-5 text-ink-200">
        {bl && <span className="mr-1 font-medium text-ink-100">{bl}:</span>}“{reply}”
      </p>
      <p className="mt-1 text-[10.5px] text-ink-500">Simulated reply, stated as an assumption in the case file (policy section 5).</p>
    </div>
  );
}

export function FlowArrow({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-1.5 pl-3 text-[11px] text-ink-500">
      <ArrowDown size={13} />
      {label}
    </div>
  );
}

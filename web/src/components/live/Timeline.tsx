import { AnimatePresence, animate, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Database, FileText, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import type { InvEvent } from "../../api/types";
import type { TimelineItem } from "../../lib/investigation";
import { findingAgent } from "../../lib/investigation";
import { AgentAvatar, agentOf } from "../../lib/agents";
import { actionLabel, money, patternLabel, triggerLabel } from "../../lib/format";
import { shortEntity, entityType } from "../../lib/entities";
import { Badge, IdChip, RiskBadge, RouteBadge, VerdictBadge, cx } from "../ui";

function ViaTag({ via }: { via: string }) {
  const v = (via || "").toLowerCase();
  if (v === "mcp")
    return <Badge className="border-tg-700 bg-tg-500/10 text-tg-300">via MCP</Badge>;
  if (v === "rest") return <Badge className="border-[#23466e] bg-[#0f1e30] text-[#8cc2ff]">via REST++</Badge>;
  return <Badge className="border-ink-600 text-ink-300">offline mirror</Badge>;
}

function EntityChips({ ids, max = 5 }: { ids: string[]; max?: number }) {
  if (!ids?.length) return null;
  const shown = ids.slice(0, max);
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {shown.map((id) => (
        <IdChip key={id} id={shortEntity(id)} tone={entityType(id) === "ClosedCase" ? "case" : "default"} />
      ))}
      {ids.length > max && <span className="self-center font-mono text-[10.5px] text-ink-400">+{ids.length - max} more</span>}
    </div>
  );
}

function Row({ agent, title, at, children, tone, dense }: { agent: string; title: React.ReactNode; at: number; children?: React.ReactNode; tone?: "warn"; dense?: boolean }) {
  const a = agentOf(agent);
  return (
    <div className={cx("relative flex gap-3 pl-1", dense ? "py-1.5" : "py-2.5")}>
      <div className="relative z-[1] pt-0.5">
        <AgentAvatar id={agent} size={dense ? 22 : 28} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <div className="min-w-0 text-[12.5px] leading-5">
            <span className="font-semibold" style={{ color: tone === "warn" ? "#EDB341" : a.color }}>
              {a.name}
            </span>{" "}
            <span className="text-ink-300">{title}</span>
          </div>
          <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-ink-500">+{at.toFixed(1)}s</span>
        </div>
        {children}
      </div>
    </div>
  );
}

function Expand({ children, label }: { children: React.ReactNode; label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1">
      <button onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1 text-[11px] text-ink-400 hover:text-ink-200">
        <ChevronDown size={12} className={cx("transition-transform", open && "rotate-180")} />
        {label}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function EventBody({ ev, at }: { ev: InvEvent; at: number }) {
  switch (ev.kind) {
    case "trigger":
      return (
        <Row agent="system" title={<>opened an alert · {triggerLabel(ev.trigger_type)}</>} at={at}>
          <p className="mt-1 rounded-lg border border-ink-700 bg-ink-800/70 px-3 py-2 text-[12.5px] leading-5 text-ink-100">{ev.text}</p>
        </Row>
      );
    case "stage":
      return (
        <Row agent={ev.agent || "lead"} title={ev.stage === "specialists" ? "briefed the specialists" : "is gathering evidence"} at={at}>
          <p className="mt-0.5 text-[12px] leading-5 text-ink-300">{ev.msg}</p>
        </Row>
      );
    case "tool_call":
      return (
        <Row agent={ev.agent} dense at={at} title={<span className="text-ink-400">ran a graph query</span>}>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-ink-700/80 bg-ink-900/70 px-2 py-1.5" title={ev.ref}>
            <Database size={12} className="text-ink-400" />
            <span className="font-mono text-[12px] font-semibold text-ink-100">{ev.query || ev.tool}</span>
            <span className="font-mono text-[11px] tabular-nums text-ink-300">
              {ev.rows} row{ev.rows === 1 ? "" : "s"} · {Number(ev.ms).toFixed(ev.ms < 10 ? 1 : 0)} ms
            </span>
            <span className="ml-auto">
              <ViaTag via={ev.via} />
            </span>
          </div>
        </Row>
      );
    case "plan":
      return (
        <Row agent="lead" title="set the hypotheses" at={at}>
          <ol className="mt-1 space-y-1">
            {(ev.hypotheses || []).map((h: string, i: number) => (
              <li key={i} className="flex gap-2 text-[12px] leading-5 text-ink-200">
                <span className="font-mono text-[11px] text-tg-400">H{i + 1}</span>
                <span className="line-clamp-3">{h}</span>
              </li>
            ))}
          </ol>
          {!!ev.calls?.length && (
            <Expand label={`${ev.calls.length} extra quer${ev.calls.length === 1 ? "y" : "ies"} requested`}>
              <ul className="mt-1 space-y-1">
                {ev.calls.map((c: any, i: number) => (
                  <li key={i} className="text-[11.5px] leading-5 text-ink-300">
                    <span className="font-mono text-ink-100">{c.tool}</span> {c.why}
                  </li>
                ))}
              </ul>
            </Expand>
          )}
        </Row>
      );
    case "specialist":
      return (
        <Row agent={ev.agent} title="reported" at={at}>
          <div className="mt-1">
            <RiskBadge risk={ev.risk} />
          </div>
          <p className="mt-1.5 text-[12px] leading-5 text-ink-200">{ev.assessment}</p>
          {!!ev.key_points?.length && (
            <Expand label={`${ev.key_points.length} key points`}>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-[11.5px] leading-5 text-ink-300">
                {ev.key_points.map((k: string, i: number) => (
                  <li key={i}>{k}</li>
                ))}
              </ul>
            </Expand>
          )}
        </Row>
      );
    case "finding": {
      const lr = Number(ev.lr);
      const dir = lr > 1.001 ? "fraud" : lr < 0.999 ? "legit" : "neutral";
      return (
        <Row agent={findingAgent(ev.family)} title="found evidence" at={at}>
          <div
            className={cx(
              "mt-1 rounded-lg border-l-2 bg-ink-800/60 py-1.5 pl-2.5 pr-2",
              dir === "fraud" ? "border-fraud" : dir === "legit" ? "border-legit" : "border-ink-500",
            )}
          >
            <p className="text-[12px] leading-5 text-ink-100">{ev.claim}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Badge className={dir === "fraud" ? "border-fraud-line bg-fraud-soft text-fraud" : dir === "legit" ? "border-legit-line bg-legit-soft text-legit" : "border-ink-600 text-ink-300"}>
                LR ×{lr}
                <span className="opacity-80">{dir === "fraud" ? "toward fraud" : dir === "legit" ? "toward legitimate" : "neutral"}</span>
              </Badge>
              <Badge className="border-ink-600 text-ink-300">{ev.family}</Badge>
            </div>
            <EntityChips ids={ev.entity_ids || []} />
          </div>
        </Row>
      );
    }
    case "assessment":
      return (
        <Row agent="lead" title="assessed the evidence" at={at}>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={ev.verdict} p={ev.p} />
            <span className="text-[12px] text-ink-300">{patternLabel(ev.pattern)}</span>
            <span className="font-mono text-[11.5px] text-ink-300">exposure {money(ev.exposure)}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {(ev.initial || []).map((a: any, i: number) => (
              <span key={i} className="inline-flex items-center gap-1 rounded-md bg-ink-800 px-1.5 py-0.5 text-[11px] text-ink-200">
                {actionLabel(a.action)}
                <span className={cx("font-mono text-[9.5px]", a.route === "L2" ? "text-fraud" : a.route === "L1" ? "text-unsure" : "text-ink-500")}>{a.route}</span>
              </span>
            ))}
          </div>
        </Row>
      );
    case "evidence_request":
      return (
        <Row agent="lead" title={<>requested evidence · {actionLabel(String(ev.type).toUpperCase())}</>} at={at}>
          <div className="mt-1 rounded-lg border border-dashed border-tg-600/70 bg-tg-500/[0.05] px-3 py-2 text-[12px] leading-5 text-ink-100">
            <span className="text-ink-400">Simulated reply ({String(ev.branch).replace("_", " ")}): </span>“{ev.assumed_response}”
          </div>
        </Row>
      );
    case "decision":
      return (
        <Row agent="lead" title="decided" at={at}>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={ev.verdict} p={ev.p} />
            <Badge className="border-ink-600 text-ink-200">{String(ev.status).replace(/_/g, " ")}</Badge>
            <span className="font-mono text-[11.5px] text-ink-300">
              {ev.episode?.length || 0} txn episode · {money(ev.exposure)}
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {(ev.final || []).map((a: any, i: number) => (
              <span key={i} className="inline-flex items-center gap-1">
                <span className="text-[11px] text-ink-200">{actionLabel(a.action)}</span>
                <RouteBadge route={a.route} />
              </span>
            ))}
          </div>
        </Row>
      );
    case "memory":
      return (
        <Row agent="precedent" title="recalled similar closed cases" at={at}>
          <EntityChips ids={ev.similar || []} max={8} />
          {!!ev.knowledge?.length && (
            <p className="mt-1.5 text-[11.5px] leading-5 text-ink-400">
              Policy and typology sections: {[...new Set(ev.knowledge as string[])].join(", ")}
            </p>
          )}
        </Row>
      );
    case "review":
      return (
        <Row agent="compliance" title={ev.agree ? "approved the decision" : "challenged the decision"} at={at}>
          <div className={cx("mt-1 flex items-center gap-1.5 text-[12px]", ev.agree ? "text-legit" : "text-unsure")}>
            {ev.agree ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
            {ev.agree ? "Consistent with the Fraud Policy" : "Issues raised"}
          </div>
          {!!ev.issues?.length && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11.5px] leading-5 text-ink-300">
              {ev.issues.map((x: string, i: number) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          )}
          {ev.what_would_change_verdict && <p className="mt-1 text-[11.5px] leading-5 text-ink-400">Would change the verdict: {ev.what_would_change_verdict}</p>}
        </Row>
      );
    case "warning":
      return (
        <Row agent="lead" tone="warn" title={<span className="inline-flex items-center gap-1 text-unsure"><AlertTriangle size={12} /> warning</span>} at={at}>
          <p className="mt-0.5 text-[12px] leading-5 text-unsure/90">{ev.msg}</p>
        </Row>
      );
    case "final": {
      const w = ev.written || {};
      return (
        <Row agent="lead" title="closed the investigation" at={at}>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px]">
            <Link to={`/case/${ev.answer?.case_id || ""}`} className="inline-flex items-center gap-1 rounded-md border border-tg-600 bg-tg-500/10 px-2 py-1 font-medium text-tg-300 hover:bg-tg-500/20">
              <FileText size={13} /> Open case file
            </Link>
            {w.ok ? (
              <span className="inline-flex items-center gap-1 text-legit">
                <CheckCircle2 size={13} /> written to TigerGraph as <span className="font-mono">{w.graph_case_id}</span>
                {w.n_vertices != null && <span className="text-ink-400">({w.n_vertices} vertices, {w.n_edges} edges)</span>}
              </span>
            ) : (
              <span className="text-ink-400">graph write skipped in this run</span>
            )}
          </div>
          {!!ev.problems?.length && <p className="mt-1 text-[11.5px] text-unsure">Validator: {ev.problems.join("; ")}</p>}
        </Row>
      );
    }
    default:
      return null;
  }
}

export function Timeline({ items, active }: { items: TimelineItem[]; active: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const auto = useRef(false); // true while we scroll programmatically, so our own scroll events don't unstick
  useEffect(() => {
    const el = ref.current;
    if (!el || !stick.current) return;
    if (!items.length) {
      el.scrollTop = 0;
      return;
    }
    // wait a frame so the new row has its height
    const raf = requestAnimationFrame(() => {
      auto.current = true;
      const c = animate(el.scrollTop, el.scrollHeight - el.clientHeight, {
        duration: 0.35,
        ease: [0.22, 1, 0.36, 1],
        onUpdate: (v) => (el.scrollTop = v),
        onComplete: () => (auto.current = false),
      });
      (el as any)._anim?.stop?.();
      (el as any)._anim = c;
    });
    return () => cancelAnimationFrame(raf);
  }, [items.length]);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={ref}
        onScroll={(e) => {
          if (auto.current) return;
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        onWheel={() => {
          auto.current = false;
          (ref.current as any)?._anim?.stop?.();
        }}
        className="scroll-thin relative min-h-0 flex-1 overflow-y-auto px-4 pb-4"
      >
        <div className="absolute bottom-0 left-[31px] top-0 w-px bg-ink-700/70" aria-hidden />
        <AnimatePresence initial={false}>
          {items.map((it) => (
            <motion.div
              key={it.id}
              layout="position"
              initial={{ opacity: 0, x: -10, filter: "blur(2px)" }}
              animate={{ opacity: 1, x: 0, filter: "blur(0px)" }}
              transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            >
              <EventBody ev={it.ev} at={it.at} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      <AnimatePresence>
        {!!active.length && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="flex items-center gap-2 border-t border-ink-700 bg-ink-850 px-4 py-2.5"
          >
            <div className="flex -space-x-1">
              {active.map((a) => (
                <AgentAvatar key={a} id={a} size={22} active />
              ))}
            </div>
            <span className="truncate text-[11.5px] text-ink-300">
              {active.map((a) => agentOf(a).name.split(" ")[0]).join(", ")} working
            </span>
            <span className="ml-auto flex gap-0.5">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="h-1 w-1 rounded-full bg-tg-500"
                  animate={{ opacity: [0.2, 1, 0.2] }}
                  transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.18 }}
                />
              ))}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

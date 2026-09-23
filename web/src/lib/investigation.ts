import { useCallback, useEffect, useReducer, useRef } from "react";
import type { Api, InvEvent, ToolCall, Answer } from "../api/types";
import { playEvents } from "./replay";

export interface TimelineItem {
  id: number;
  at: number; // seconds since the run started (client clock)
  ev: InvEvent;
}

export interface RunState {
  status: "idle" | "connecting" | "running" | "done" | "error";
  error?: string;
  startedAt: number;
  endedAt?: number;
  items: TimelineItem[];
  trigger?: InvEvent;
  stageIdx: number;
  toolCalls: (ToolCall & { at: number })[];
  plan?: InvEvent;
  specialistsStarted: boolean;
  specialists: Record<string, InvEvent>;
  findings: InvEvent[];
  assessment?: InvEvent;
  evidenceRequests: InvEvent[];
  decision?: InvEvent;
  memory?: InvEvent;
  review?: InvEvent;
  final?: InvEvent;
  answer?: Answer;
  warnings: InvEvent[];
  lastProbe?: { ref: string; agent: string; n: number };
}

export const STAGES = [
  { key: "trigger", label: "Alert" },
  { key: "gather", label: "Gather" },
  { key: "plan", label: "Plan" },
  { key: "specialists", label: "Specialists" },
  { key: "assess", label: "Assess" },
  { key: "verify", label: "Verify" },
  { key: "decide", label: "Decide" },
  { key: "recall", label: "Recall" },
  { key: "review", label: "Review" },
  { key: "final", label: "Case file" },
];

function stageOf(e: InvEvent): number {
  switch (e.kind) {
    case "trigger": return 0;
    case "tool_call": return 1;
    case "stage": return e.stage === "specialists" ? 3 : e.stage === "gather" ? 1 : -1;
    case "plan": return 2;
    case "specialist": return 3;
    case "finding":
    case "assessment": return 4;
    case "evidence_request": return 5;
    case "decision": return 6;
    case "memory": return 7;
    case "review": return 8;
    case "final": return 9;
    default: return -1;
  }
}

const initial = (): RunState => ({
  status: "idle",
  startedAt: Date.now(),
  items: [],
  stageIdx: -1,
  toolCalls: [],
  specialistsStarted: false,
  specialists: {},
  findings: [],
  evidenceRequests: [],
  warnings: [],
});

type Act = { type: "start" } | { type: "event"; ev: InvEvent } | { type: "end"; err?: string };

let seq = 0;

function reduce(s: RunState, a: Act): RunState {
  if (a.type === "start") return { ...initial(), status: "connecting", startedAt: Date.now() };
  if (a.type === "end") {
    if (s.status === "done" || s.status === "error") return s;
    if (a.err === "cancelled") return s;
    return { ...s, status: a.err && !s.items.length ? "error" : "done", error: a.err, endedAt: Date.now() };
  }
  const ev = a.ev;
  const at = (Date.now() - s.startedAt) / 1000;
  const n: RunState = { ...s, status: "running", items: [...s.items, { id: ++seq, at, ev }] };
  const st = stageOf(ev);
  if (st > n.stageIdx) n.stageIdx = st;
  switch (ev.kind) {
    case "trigger": n.trigger = ev; break;
    case "stage": if (ev.stage === "specialists") n.specialistsStarted = true; break;
    case "tool_call":
      n.toolCalls = [...s.toolCalls, { ...(ev as unknown as ToolCall), at }];
      n.lastProbe = { ref: ev.ref || "", agent: ev.agent || "lead", n: (s.lastProbe?.n || 0) + 1 };
      break;
    case "plan": n.plan = ev; break;
    case "specialist": n.specialists = { ...s.specialists, [ev.agent]: ev }; n.specialistsStarted = true; break;
    case "finding": n.findings = [...s.findings, ev]; break;
    case "assessment": n.assessment = ev; break;
    case "evidence_request": n.evidenceRequests = [...s.evidenceRequests, ev]; break;
    case "decision": n.decision = ev; break;
    case "memory": n.memory = ev; break;
    case "review": n.review = ev; break;
    case "warning": n.warnings = [...s.warnings, ev]; break;
    case "final":
      n.final = ev;
      if (ev.answer) n.answer = ev.answer as Answer;
      break;
  }
  return n;
}

// source "live": stream GET /api/cases/{id}/run (or the mock's replay offline).
// source "replay": play a saved trace client-side, without asking the server to investigate again.
export function useInvestigation(api: Api | null, caseId: string | undefined, source: "live" | "replay" = "live", replay?: InvEvent[] | null) {
  const [state, dispatch] = useReducer(reduce, undefined, initial);
  const stopRef = useRef<(() => void) | null>(null);
  const replayRef = useRef(replay);
  replayRef.current = replay;
  const ready = source === "live" || !!replay;

  const start = useCallback(() => {
    if (!api || !caseId || !ready) return;
    stopRef.current?.();
    dispatch({ type: "start" });
    const onEv = (ev: InvEvent) => dispatch({ type: "event", ev });
    const onEnd = (err?: string) => dispatch({ type: "end", err });
    stopRef.current = source === "replay" && replayRef.current ? playEvents(replayRef.current, onEv, onEnd) : api.run(caseId, onEv, onEnd);
  }, [api, caseId, source, ready]);

  useEffect(() => {
    start();
    return () => {
      stopRef.current?.();
      stopRef.current = null;
    };
  }, [start]);

  return { state, restart: start };
}

// Which specialist agents are still working (between the "specialists" stage and their own report).
export function activeAgents(s: RunState): string[] {
  if (s.status !== "running" && s.status !== "connecting") return [];
  const out: string[] = [];
  if (s.specialistsStarted) {
    for (const a of ["transaction", "identity", "network", "precedent"]) if (!s.specialists[a]) out.push(a);
  }
  if (s.stageIdx <= 2) out.push("lead");
  if (s.memory && !s.review) out.push("compliance");
  if (s.decision && !s.memory) out.push("precedent");
  return out;
}

export function findingAgent(family: string | undefined): string {
  switch (family) {
    case "device":
    case "identity":
    case "account": return "identity";
    case "network":
    case "ring": return "network";
    case "precedent":
    case "history":
    case "memory": return "precedent";
    default: return "transaction";
  }
}

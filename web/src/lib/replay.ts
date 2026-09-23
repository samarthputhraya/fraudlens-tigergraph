// Turn a saved trace (runs/traces/{id}.json) back into the SSE event stream the live view consumes, and play it
// with realistic pacing. Used by the offline mock and by "Replay saved run" when the backend is up.
import type { Answer, CaseRow, InvEvent, ToolCall, Trace } from "../api/types";

export function traceToEvents(tr: Trace, ans: Answer | null | undefined, row?: CaseRow | null): InvEvent[] {
  const events = tr.events.map((e) => ({ ...e }));
  const hasCalls = events.some((e) => e.kind === "tool_call");
  if (!hasCalls && tr.tool_calls?.length) {
    // The trace stores tool calls separately; re-insert each where it happened: core toolkit after "gather",
    // the lead's extra calls after "plan", case-memory retrieval before "memory".
    const calls = tr.tool_calls.map((c, i) => ({ ...c, i }));
    const recallQ = new Set(["similar_cases", "search_knowledge"]);
    const recall = calls.filter((c) => recallQ.has(c.query) && c.agent === "precedent");
    const taken = new Set(recall.map((c) => c.i));
    const extras: typeof calls = [];
    for (const x of tr.lead?.extra_calls || []) {
      const cand = calls.filter((c) => c.query === x.tool && !taken.has(c.i));
      if (cand.length >= 2) {
        const last = cand[cand.length - 1];
        extras.push(last);
        taken.add(last.i);
      }
    }
    extras.sort((a, b) => a.i - b.i);
    const gather = calls.filter((c) => !taken.has(c.i));
    const toEv = (c: ToolCall & { i: number; params?: unknown }): InvEvent => {
      const { i, params, ...rest } = c;
      return { kind: "tool_call", ...rest };
    };
    const out: InvEvent[] = [];
    let placedGather = false;
    for (const e of events) {
      if (e.kind === "memory") out.push(...recall.map(toEv));
      out.push(e);
      if (e.kind === "stage" && e.stage === "gather") {
        out.push(...gather.map(toEv));
        placedGather = true;
      }
      if (e.kind === "plan") out.push(...extras.map(toEv));
    }
    if (!placedGather) out.splice(1, 0, ...gather.map(toEv));
    events.length = 0;
    events.push(...out);
  }
  if (!events.some((e) => e.kind === "trigger") && row) {
    events.unshift({ kind: "trigger", case_id: row.case_id, trigger_type: row.trigger_type, text: row.trigger_text, opened_at: row.opened_at });
  }
  const fin = events.find((e) => e.kind === "final");
  if (fin && !fin.answer && ans) fin.answer = ans;
  if (!fin && ans) events.push({ kind: "final", answer: ans, problems: tr.problems || [], written: tr.written || { ok: false } });
  return events;
}

const DELAY: Record<string, [number, number]> = {
  trigger: [250, 350],
  stage: [450, 650],
  tool_call: [170, 420],
  plan: [650, 700],
  specialist: [550, 700],
  finding: [380, 560],
  assessment: [600, 700],
  evidence_request: [650, 700],
  decision: [550, 700],
  memory: [450, 600],
  review: [600, 700],
  warning: [200, 300],
  final: [450, 600],
};

function delayFor(kind: string) {
  const [a, b] = DELAY[kind] || [150, 400];
  return a + Math.random() * (b - a);
}

export function playEvents(events: InvEvent[], onEvent: (e: InvEvent) => void, onEnd: (err?: string) => void): () => void {
  let i = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  const step = () => {
    if (stopped) return;
    if (i >= events.length) {
      stopped = true;
      onEnd();
      return;
    }
    const e = events[i++];
    onEvent({ ...e, t: Date.now() / 1000 });
    timer = setTimeout(step, delayFor(events[i]?.kind || "final"));
  };
  timer = setTimeout(step, 400);
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}

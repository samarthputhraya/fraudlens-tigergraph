// Real client for the FastAPI backend (docs/api_contract.md).
import type { Api, ApprovalResult, CaseDetail, CaseRow, GraphPayload, Health, InvEvent, Metrics, ReproveResult, Approval } from "./types";

export const EVENT_KINDS = [
  "trigger", "stage", "tool_call", "plan", "specialist", "finding", "assessment", "evidence_request",
  "decision", "memory", "review", "warning", "final", "done", "error",
];

async function j<T>(path: string, init?: RequestInit, timeoutMs = 30000): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(path, {
      ...init,
      signal: ctl.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    const text = await res.text();
    let body: any = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { detail: text };
    }
    if (!res.ok) {
      // Approval permission errors come back as {ok:false, error} with a 403; surface them as data, not exceptions.
      if (body && typeof body === "object" && "ok" in body) return body as T;
      const msg = body?.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : res.statusText;
      throw new Error(`${res.status} ${msg}`);
    }
    return body as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function probeHealth(timeoutMs = 2500): Promise<Health | null> {
  try {
    const h = await j<Health>("/api/health", undefined, timeoutMs);
    return h && typeof h === "object" && "graph" in h ? h : null;
  } catch {
    return null;
  }
}

export function createClient(): Api {
  return {
    mode: "live",
    health: () => j<Health>("/api/health", undefined, 5000),
    cases: () => j<CaseRow[]>("/api/cases"),
    caseDetail: (id) => j<CaseDetail>(`/api/cases/${encodeURIComponent(id)}`),
    investigate: (txn_id, note) => j<CaseRow>("/api/investigate", { method: "POST", body: JSON.stringify({ txn_id, note }) }, 60000),
    approvals: () => j<Approval[]>("/api/approvals"),
    decide: (action_id, approve, role) =>
      j<ApprovalResult>(`/api/approvals/${encodeURIComponent(action_id)}`, { method: "POST", body: JSON.stringify({ approve, role }) }),
    reprove: (ref) => j<ReproveResult>("/api/reprove", { method: "POST", body: JSON.stringify({ ref }) }, 60000),
    graph: (id) => j<GraphPayload>(`/api/graph/${encodeURIComponent(id)}`),
    metrics: () => j<Metrics>("/api/metrics"),
    run(id, onEvent, onEnd) {
      const es = new EventSource(`/api/cases/${encodeURIComponent(id)}/run`);
      let closed = false;
      let received = 0;
      const finish = (err?: string) => {
        if (closed) return;
        closed = true;
        es.close();
        onEnd(err);
      };
      const handle = (name: string) => (msg: MessageEvent) => {
        let data: InvEvent;
        try {
          data = msg.data ? JSON.parse(msg.data) : { kind: name };
        } catch {
          data = { kind: "warning", msg: String(msg.data) };
        }
        if (!data.kind || data.kind === "message") data.kind = name;
        received++;
        if (data.kind === "done") {
          finish();
          return;
        }
        if (data.kind === "error") {
          onEvent({ kind: "warning", msg: data.msg || data.detail || "The run reported an error" });
          finish(data.msg || "error");
          return;
        }
        onEvent(data);
      };
      for (const k of EVENT_KINDS) es.addEventListener(k, handle(k) as EventListener);
      es.onmessage = handle("message");
      es.onerror = () => {
        // EventSource retries forever by default; a closed stream after events means the run ended.
        finish(received ? undefined : "Could not open the live event stream");
      };
      return () => finish("cancelled");
    },
  };
}

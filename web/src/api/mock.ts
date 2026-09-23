// Offline mock of the Command Center API. Serves the contract from real agent output copied into src/fixtures:
//   fixtures/case_pack.json      the 20 benchmark alerts (data/raw/case_pack.csv)
//   fixtures/cases/*.json        answer files written by the agent (cases/*.json)
//   fixtures/traces/*.json       saved runs (runs/traces/*.json), replayed as SSE with realistic delays
//   fixtures/backtest_report.json the backtest over closed-case history (eval/report.json)
// Run `npm run sync-fixtures` to refresh them from the repo.
import casePack from "../fixtures/case_pack.json";
import backtestReport from "../fixtures/backtest_report.json";
import type {
  Answer, Api, Approval, CaseDetail, CaseRow, GEdge, GNode, GraphPayload, Health, InvEvent, Metrics, ReproveResult, ToolCall, Trace,
} from "./types";

const answerFiles = import.meta.glob("../fixtures/cases/*.json", { eager: true, import: "default" }) as Record<string, Answer>;
const traceFiles = import.meta.glob("../fixtures/traces/*.json", { eager: true, import: "default" }) as Record<string, Trace>;

const byId = <T>(files: Record<string, T>) =>
  Object.fromEntries(Object.entries(files).map(([p, v]) => [p.split("/").pop()!.replace(/\.json$/, ""), v])) as Record<string, T>;

const ANSWERS = byId(answerFiles);
const TRACES = byId(traceFiles);

type PackRow = Record<string, string>;
const adhoc: CaseRow[] = [];
const decided: Record<string, string> = {};

function statusFrom(a: Answer | undefined) {
  return a ? a.case.status : "new";
}

function rowFor(p: PackRow): CaseRow {
  const a = ANSWERS[p.case_id];
  return {
    case_id: p.case_id,
    opened_at: p.opened_at,
    trigger_type: p.trigger_type,
    trigger_text: p.trigger_text,
    flagged_txn_id: p.flagged_txn_id,
    card_id: p.card_id,
    customer_id: p.customer_id,
    risk_score: p.risk_score ?? "",
    status: statusFrom(a),
    verdict: a ? (a.case.verdict as CaseRow["verdict"]) : null,
    fraud_probability: a ? a.case.fraud_probability : null,
    pattern: a ? a.case.pattern : null,
    exposure_usd: a ? a.case.exposure_usd : null,
    sar: a ? a.sar.file : null,
    source: "benchmark",
  };
}

function allRows(): CaseRow[] {
  const rows = (casePack as PackRow[]).map(rowFor).concat(adhoc);
  return rows.sort((a, b) => a.opened_at.localeCompare(b.opened_at));
}

const wait = <T>(v: T, ms = 120) => new Promise<T>((r) => setTimeout(() => r(structuredClone(v)), ms));

// ---------------------------------------------------------------------------------------------
// Replay: the saved trace records the agent's reasoning events; its tool calls are stored separately. Re-insert
// each call where it happened (core toolkit after "gather", the lead's extra calls after "plan", case-memory
// retrieval before "memory") so the live view sees the same stream the server sends.
function replayEvents(caseId: string): InvEvent[] {
  const tr = TRACES[caseId];
  const ans = ANSWERS[caseId];
  const row = allRows().find((r) => r.case_id === caseId);
  if (!tr) {
    return [
      { kind: "trigger", case_id: caseId, trigger_type: row?.trigger_type || "analyst_request", text: row?.trigger_text || "", opened_at: row?.opened_at || "" },
      { kind: "stage", stage: "gather", agent: "lead", msg: "Waiting for the investigation service" },
      { kind: "warning", msg: `No saved run for ${caseId} in this offline build. Start the API (uvicorn) to investigate it live on TigerGraph.` },
    ];
  }
  const events = tr.events.map((e) => ({ ...e }));
  const hasCalls = events.some((e) => e.kind === "tool_call");
  if (!hasCalls && tr.tool_calls?.length) {
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
    const toEv = (c: ToolCall & { i: number }): InvEvent => {
      const { i, ...rest } = c;
      return { kind: "tool_call", ...rest };
    };
    const out: InvEvent[] = [];
    for (const e of events) {
      if (e.kind === "memory") out.push(...recall.map(toEv));
      out.push(e);
      if (e.kind === "stage" && e.stage === "gather") out.push(...gather.map(toEv));
      if (e.kind === "plan") out.push(...extras.map(toEv));
    }
    events.length = 0;
    events.push(...out);
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

// ---------------------------------------------------------------------------------------------
function key(type: string, raw: string) {
  const p: Record<string, string> = {
    Transaction: "txn", Card: "card", Customer: "cust", DeviceProfile: "dev", ClosedCase: "cc", InvestigationCase: "case",
    BillingRegion: "region", Account: "acct",
  };
  return `${p[type] || type.toLowerCase()}:${raw}`;
}

function graphFor(caseId: string): GraphPayload {
  const row = allRows().find((r) => r.case_id === caseId);
  const a = ANSWERS[caseId];
  const nodes = new Map<string, GNode>();
  const edges: GEdge[] = [];
  const node = (type: string, raw: string, label: string, extra: Partial<GNode> = {}) => {
    const id = key(type, raw);
    const cur = nodes.get(id);
    nodes.set(id, { ...(cur || { id, label, type }), ...extra });
    return id;
  };
  const edge = (s: string, t: string, type: string) => {
    if (!edges.some((e) => e.source === s && e.target === t)) edges.push({ source: s, target: t, type });
  };
  if (!row) return { nodes: [], edges: [] };
  const card = node("Card", row.card_id, row.card_id);
  const cust = node("Customer", row.customer_id, row.customer_id);
  edge(cust, card, "OWNS");
  const flagged = node("Transaction", row.flagged_txn_id, row.flagged_txn_id, { flagged: true });
  edge(card, flagged, "MADE");
  if (!a) return { nodes: [...nodes.values()], edges };
  const fraud = a.case.verdict === "fraud";
  for (const t of a.case.affected_txn_ids) {
    const id = node("Transaction", t, t, { affected: true, fraud });
    edge(card, id, "MADE");
  }
  const devs = a.case.connected_device_profiles || [];
  for (const d of devs) {
    const dev = node("DeviceProfile", d, d.split(" | ").slice(0, 2).join(" · "));
    edge(flagged, dev, "FROM_DEVICE");
    for (const c of a.case.connected_card_ids) {
      const cid = node("Card", c, c, { ring: true });
      edge(cid, dev, "CARD_DEVICE");
    }
  }
  if (!devs.length) {
    for (const c of a.case.connected_card_ids) edge(card, node("Card", c, c, { ring: true }), "RING_LINK");
  }
  const inv = node("InvestigationCase", a.case.graph_case_id || caseId, a.case.graph_case_id || caseId);
  edge(inv, flagged, "CASE_TXN");
  for (const cc of a.case.similar_prior_cases) edge(inv, node("ClosedCase", cc, cc), "CASE_CITES");
  return { nodes: [...nodes.values()], edges };
}

// ---------------------------------------------------------------------------------------------
function approvalsAll(): Approval[] {
  const out: Approval[] = [];
  for (const row of allRows()) {
    const a = ANSWERS[row.case_id];
    if (!a) continue;
    const num = row.case_id.replace(/\D/g, "").padStart(3, "0");
    const year = row.opened_at.slice(0, 4);
    a.next_best_actions.final.forEach((act, i) => {
      if (act.route !== "L1" && act.route !== "L2") return;
      const id = `CASE-${year}-${num}-F${i + 1}`;
      out.push({
        action_id: id,
        case_id: row.case_id,
        action: act.action,
        route: act.route,
        reason: act.reason,
        status: decided[id] || (act.route === "L1" ? "pending_approval_team_lead" : "pending_approval_fraud_manager"),
        exposure_usd: a.case.exposure_usd,
      });
    });
  }
  return out;
}

function metricsAll(): Metrics {
  const answers = Object.values(ANSWERS);
  const verdicts: Record<string, number> = { fraud: 0, legitimate: 0, uncertain: 0 };
  const patterns: Record<string, number> = {};
  let exp = 0, calls = 0, toks = 0, lat = 0, sar = 0;
  for (const a of answers) {
    verdicts[a.case.verdict] = (verdicts[a.case.verdict] || 0) + 1;
    patterns[a.case.pattern] = (patterns[a.case.pattern] || 0) + 1;
    exp += a.case.exposure_usd || 0;
    calls += a.tool_calls || 0;
    toks += a.tokens || 0;
    lat += a.latency_s || 0;
    if (a.sar.file) sar++;
  }
  const n = Math.max(answers.length, 1);
  const rings = answers
    .filter((a) => a.case.connected_card_ids.length >= 3)
    .map((a) => {
      const row = allRows().find((r) => r.case_id === a.case_id);
      return {
        component: `${a.case_id} device ring`,
        members: [row?.card_id, ...a.case.connected_card_ids].filter(Boolean) as string[],
        devices: a.case.connected_device_profiles || [],
        fraud_cases: a.case.similar_prior_cases,
      };
    });
  return {
    backtest: backtestReport as unknown as Metrics["backtest"],
    portfolio: {
      verdicts, patterns, sar_filed: sar, total_exposure: Math.round(exp * 100) / 100,
      avg_tool_calls: calls / n, avg_tokens: toks / n, avg_latency_s: lat / n,
    },
    rings,
  };
}

export function createMock(): Api {
  return {
    mode: "mock",
    health: () =>
      wait<Health>({ graph: "offline mirror", host: "bundled fixtures", graph_name: "Fraud", mcp: false, llm: "recorded run" }),
    cases: () => wait(allRows()),
    caseDetail: (id) => {
      const row = allRows().find((r) => r.case_id === id);
      if (!row) return Promise.reject(new Error(`404 Case ${id} not found`));
      return wait<CaseDetail>({ row, answer: ANSWERS[id] || null, trace: TRACES[id] || null });
    },
    investigate: (txn_id, note) => {
      const n = adhoc.length + 1;
      const now = new Date();
      const row: CaseRow = {
        case_id: `ADHOC-${String(n).padStart(3, "0")}`,
        opened_at: now.toISOString().slice(0, 19).replace("T", " "),
        trigger_type: "analyst_request",
        trigger_text: note ? `Analyst request: ${note} Review transaction ${txn_id}.` : `Analyst request: review transaction ${txn_id}.`,
        flagged_txn_id: txn_id,
        card_id: "",
        customer_id: "",
        risk_score: "",
        status: "new",
        verdict: null,
        fraud_probability: null,
        pattern: null,
        exposure_usd: null,
        sar: null,
        source: "analyst",
      };
      adhoc.push(row);
      return wait(row, 300);
    },
    approvals: () => wait(approvalsAll()),
    decide: (action_id, approve, role) => {
      const ap = approvalsAll().find((a) => a.action_id === action_id);
      if (!ap) return wait({ ok: false, status: "unknown", error: `No action ${action_id}` });
      if (!ap.status.startsWith("pending")) return wait({ ok: false, status: ap.status, error: `${action_id} was already decided (${ap.status.replace(/_/g, " ")})` });
      if (ap.route === "L2" && role !== "fraud_manager") {
        return wait({
          ok: false,
          status: ap.status,
          error: `Team leads can approve L1 actions only. ${ap.action} is routed L2 and needs a fraud manager (policy section 2).`,
        });
      }
      const st = `${approve ? "approved" : "rejected"}_by_${role}`;
      decided[action_id] = st;
      return wait({ ok: true, status: st });
    },
    reprove: (ref) => {
      const m = /^query:(\w+)\((.*)\)$/s.exec(ref);
      const q = m?.[1] || ref;
      const call = Object.values(TRACES).flatMap((t) => t.tool_calls || []).find((c) => c.ref === ref);
      const r: ReproveResult = {
        ok: !!call,
        query: q,
        params: m?.[2] || "",
        rows: call?.rows ?? 0,
        ms: call?.ms ?? 0,
        via: call?.via || "mirror",
        sample: [],
        note: "Offline mock: this is the result recorded in the saved run. Start the API to re-run the query on TigerGraph.",
        error: call ? undefined : "This query is not in the saved run",
      };
      return wait(r, 650);
    },
    graph: (id) => wait(graphFor(id), 250),
    metrics: () => wait(metricsAll()),
    run(id, onEvent, onEnd) {
      const events = replayEvents(id);
      let i = 0;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let stopped = false;
      const t0 = Date.now() / 1000;
      const step = () => {
        if (stopped) return;
        if (i >= events.length) {
          stopped = true;
          onEnd();
          return;
        }
        const e = events[i++];
        onEvent({ ...e, t: Date.now() / 1000, t0 });
        timer = setTimeout(step, delayFor(events[i]?.kind || "final"));
      };
      timer = setTimeout(step, 400);
      return () => {
        stopped = true;
        if (timer) clearTimeout(timer);
      };
    },
  };
}

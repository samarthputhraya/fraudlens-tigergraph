// Types for the Command Center API contract (docs/api_contract.md).

export type TriggerType = "risk_score" | "customer_report" | "analyst_request" | "autonomous";
export type Verdict = "fraud" | "legitimate" | "uncertain";
export type Route = "auto" | "L1" | "L2";
export type AgentId = "lead" | "transaction" | "identity" | "network" | "precedent" | "compliance";

export interface Health {
  graph: string; // "TigerGraph Savanna" | "offline mirror"
  host: string;
  graph_name: string;
  mcp: boolean;
  llm: string;
}

export interface CaseRow {
  case_id: string;
  opened_at: string;
  trigger_type: TriggerType | string;
  trigger_text: string;
  flagged_txn_id: string;
  card_id: string;
  customer_id: string;
  risk_score: string | number | null;
  status: string; // open | closed_fraud | closed_legitimate | escalated | new
  verdict: Verdict | null | "null" | string;
  fraud_probability: number | null;
  pattern: string | null;
  exposure_usd: number | null;
  sar: boolean | null;
  source: string;
}

export interface Action {
  action: string;
  route: Route | string;
  reason: string;
}

export interface EvidenceItem {
  claim: string;
  source: string; // graph | document | customer | external
  ref: string;
  entity_ids: string[];
}

export interface Answer {
  case_id: string;
  case: {
    status: string;
    verdict: Verdict | string;
    fraud_probability: number;
    pattern: string;
    pattern_description?: string;
    affected_txn_ids: string[];
    first_suspicious_txn_id?: string;
    connected_card_ids: string[];
    connected_device_profiles?: string[];
    exposure_usd: number;
    evidence: EvidenceItem[];
    similar_prior_cases: string[];
    summary: string;
    written_to_graph: boolean;
    graph_case_id: string;
  };
  evidence_requests: { type: string; asked_after_step: number; assumed_response: string }[];
  next_best_actions: { initial: Action[]; final: Action[]; what_changed: string };
  sar: {
    file: boolean;
    reason: string;
    narrative: string;
    subjects: string[];
    total_amount_usd: number;
    activity_dates: string[];
  };
  stop_reason: string;
  tool_calls: number;
  tokens: number;
  latency_s: number;
}

export interface ToolCall {
  agent: AgentId | string;
  tool: string;
  query: string;
  ref: string;
  rows: number;
  ms: number;
  via: string; // mcp | rest | mirror
}

export interface Specialist {
  assessment: string;
  risk: string;
  key_points: string[];
  open_questions?: string[];
}

export interface Trace {
  case_id: string;
  events: InvEvent[];
  tool_calls: ToolCall[];
  specialists: Record<string, Specialist> | null;
  lead: { hypotheses: string[]; extra_calls: { tool: string; why: string }[]; focus: string } | null;
  critic: { agree: boolean; issues: string[]; what_would_change_verdict: string } | null;
  problems: string[] | null;
  written: { ok: boolean; graph_case_id?: string; n_vertices?: number; n_edges?: number } | null;
}

export interface Contribution {
  key: string;
  family: string;
  lr: number;
  delta_logodds: number;
}

// One SSE event. `kind` doubles as the SSE `event:` name.
export type InvEvent = { kind: string; t?: number; [k: string]: any };

export interface CaseDetail {
  row: CaseRow;
  answer: Answer | null;
  trace: Trace | null;
}

export interface Approval {
  action_id: string;
  case_id: string;
  action: string;
  route: Route | string;
  reason: string;
  status: string;
  exposure_usd: number;
}

export interface ApprovalResult {
  ok: boolean;
  status: string;
  error?: string;
}

export interface ReproveResult {
  ok: boolean;
  query: string;
  params: Record<string, unknown> | string;
  rows: number;
  ms: number;
  via: string;
  sample: Record<string, unknown>[];
  error?: string;
  note?: string;
}

export interface GNode {
  id: string;
  label: string;
  type: string;
  flagged?: boolean;
  affected?: boolean;
  fraud?: boolean;
  ring?: boolean;
}

export interface GEdge {
  source: string;
  target: string;
  type: string;
}

export interface GraphPayload {
  nodes: GNode[];
  edges: GEdge[];
}

export interface Metrics {
  backtest: {
    n_cases: number;
    pattern_accuracy: number;
    verdict_accuracy: number;
    episode_jaccard: number;
    exposure_mae: number;
    sar_agreement: number;
    brier?: number;
    brier_balanced?: number;
    reliability: { bin: string; predicted: number; observed: number; n: number }[];
    n_confirmed?: number;
    n_cleared?: number;
    uncertain_share?: number;
    fraud_recall?: number;
    cleared_specificity?: number;
    evidence_auc_all?: number | null;
    evidence_auc_score_ge_0_5?: number | null;
    pattern_confusion?: [string, number][];
    note?: string;
  } | null;
  portfolio: {
    verdicts: Record<string, number>;
    patterns: Record<string, number>;
    sar_filed: number;
    total_exposure: number;
    avg_tool_calls: number;
    avg_tokens: number;
    avg_latency_s: number;
  } | null;
  rings: { component: string | number; members: string[]; devices: string[]; fraud_cases: string[] }[];
}

export interface Api {
  mode: "live" | "mock";
  health(): Promise<Health>;
  cases(): Promise<CaseRow[]>;
  caseDetail(id: string): Promise<CaseDetail>;
  run(id: string, onEvent: (e: InvEvent) => void, onEnd: (err?: string) => void): () => void;
  investigate(txn_id: string, note: string): Promise<CaseRow>;
  approvals(): Promise<Approval[]>;
  decide(action_id: string, approve: boolean, role: "team_lead" | "fraud_manager"): Promise<ApprovalResult>;
  reprove(ref: string): Promise<ReproveResult>;
  graph(id: string): Promise<GraphPayload>;
  metrics(): Promise<Metrics>;
}

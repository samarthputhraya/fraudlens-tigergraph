export const money = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(v)
    ? "—"
    : "$" + v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const pct = (v: number | null | undefined, digits = 0) =>
  v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export const prob = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(2));

export function shortDate(s: string | null | undefined) {
  if (!s) return "—";
  const d = new Date(s.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function shortTime(s: string | null | undefined) {
  if (!s) return "";
  const m = /(\d{2}:\d{2})/.exec(s);
  return m ? m[1] : "";
}

const ACTION_LABELS: Record<string, string> = {
  ALLOW_TRANSACTION: "Allow transaction",
  DECLINE_TRANSACTION: "Decline transaction",
  MONITOR_CARD: "Monitor card",
  MONITOR_CONNECTED_CARDS: "Monitor connected cards",
  WARN_CUSTOMER: "Warn customer",
  VERIFY_WITH_CUSTOMER: "Verify with customer",
  STEP_UP_AUTH: "Step-up authentication",
  BLOCK_CARD: "Block card",
  BLOCK_ALL_CARDS: "Block all cards",
  GENERATE_REPORT: "Generate report",
  CREATE_CASE: "Create case",
  FILE_REPORT: "File SAR",
  ESCALATE_TO_ANALYST: "Escalate to analyst",
  CLOSE_NO_FRAUD: "Close, no fraud",
};

export const actionLabel = (a: string) =>
  ACTION_LABELS[a] || a.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

const PATTERN_LABELS: Record<string, string> = {
  card_testing: "Card testing",
  card_not_present_fraud: "Card-not-present",
  card_not_present_new_device: "CNP, new device",
  out_of_region_use: "Out-of-region use",
  account_takeover: "Account takeover",
  undocumented: "Undocumented",
  none: "None",
};

export const patternLabel = (p: string | null | undefined) => (p ? PATTERN_LABELS[p] || p.replace(/_/g, " ") : "—");

const TRIGGER_LABELS: Record<string, string> = {
  risk_score: "Risk score",
  customer_report: "Customer report",
  analyst_request: "Analyst",
  autonomous: "Autonomous",
};
export const triggerLabel = (t: string) => TRIGGER_LABELS[t] || t.replace(/_/g, " ");

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  closed_fraud: "Closed · fraud",
  closed_legitimate: "Closed · legitimate",
  escalated: "Escalated",
  new: "New",
};
export const statusLabel = (s: string) => STATUS_LABELS[s] || s.replace(/_/g, " ");

export function normVerdict(v: unknown): "fraud" | "legitimate" | "uncertain" | null {
  if (v === "fraud" || v === "legitimate" || v === "uncertain") return v;
  return null;
}

export const ROUTE_META: Record<string, { label: string; who: string; cls: string }> = {
  auto: { label: "Auto", who: "Agent executes", cls: "border-ink-500/60 bg-ink-700/60 text-ink-200" },
  L1: { label: "Team lead", who: "L1 approval", cls: "border-unsure-line bg-unsure-soft text-unsure" },
  L2: { label: "Fraud manager", who: "L2 approval", cls: "border-fraud-line bg-fraud-soft text-fraud" },
};

export function titleCase(s: string) {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function downloadJson(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

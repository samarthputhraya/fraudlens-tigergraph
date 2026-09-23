// Recognise the IDs the agent cites so the live graph can place them.
export type EntityType =
  | "Transaction" | "Card" | "Customer" | "DeviceProfile" | "ClosedCase" | "InvestigationCase" | "BillingRegion" | "Account" | "Other";

export function entityType(id: string): EntityType {
  const s = id.trim();
  if (/^3\d{6}$/.test(s)) return "Transaction";
  if (/^C\d{3,6}-K\d+$/i.test(s)) return "Card";
  if (/^C\d{3,6}$/i.test(s)) return "Customer";
  if (/^CC-\d+$/i.test(s)) return "ClosedCase";
  if (/^(HHG|ADHOC|AUTO|CASE|INV)-/i.test(s)) return "InvestigationCase";
  if (/\|/.test(s) || /Build\//.test(s)) return "DeviceProfile";
  if (/^\d{2,3}(\.0)?$/.test(s)) return "BillingRegion";
  if (/^C\d+-K\d+\|/.test(s)) return "Account";
  return "Other";
}

const PREFIX: Record<string, string> = {
  Transaction: "txn", Card: "card", Customer: "cust", DeviceProfile: "dev", ClosedCase: "cc", InvestigationCase: "case",
  BillingRegion: "region", Account: "acct", EmailDomain: "email",
};

export function nodeKey(type: string, raw: string) {
  return `${PREFIX[type] || type.toLowerCase()}:${raw}`;
}

export function rawFromServerId(id: string) {
  const i = id.indexOf(":");
  return i >= 0 ? id.slice(i + 1) : id;
}

export function deviceLabel(d: string) {
  const parts = d.split("|").map((x) => x.trim()).filter(Boolean);
  return parts.slice(0, 2).join(" · ") || d;
}

export function shortEntity(id: string) {
  return entityType(id) === "DeviceProfile" ? deviceLabel(id) : id;
}

// Parse `query:name(k=v, k=[a, b], ...)` into its name and parameters.
export function parseRef(ref: string): { name: string; params: Record<string, string | string[]> } | null {
  const m = /^query:([\w.]+)\((.*)\)$/s.exec(ref.trim());
  if (!m) return null;
  const params: Record<string, string | string[]> = {};
  const body = m[2];
  let depth = 0;
  let cur = "";
  const parts: string[] = [];
  for (const ch of body) {
    if (ch === "[" || ch === "(") depth++;
    if (ch === "]" || ch === ")") depth--;
    if (ch === "," && depth === 0) {
      parts.push(cur);
      cur = "";
    } else cur += ch;
  }
  if (cur.trim()) parts.push(cur);
  for (const p of parts) {
    const i = p.indexOf("=");
    if (i < 0) continue;
    const k = p.slice(0, i).trim();
    const v = p.slice(i + 1).trim();
    if (v.startsWith("[")) {
      params[k] = v
        .slice(1, -1)
        .split(",")
        .map((x) => x.trim().replace(/^['"]|['"]$/g, ""))
        .filter(Boolean);
    } else params[k] = v.replace(/^['"]|['"]$/g, "");
  }
  return { name: m[1], params };
}

// Which entities does a query touch? Used to flash the node a tool call is probing.
export function refEntities(ref: string): { type: EntityType; id: string }[] {
  const p = parseRef(ref);
  if (!p) return [];
  const out: { type: EntityType; id: string }[] = [];
  const push = (type: EntityType, id: string) => id && out.push({ type, id });
  for (const [k, v] of Object.entries(p.params)) {
    const vals = Array.isArray(v) ? v : [v];
    if (k === "txn") vals.forEach((x) => push("Transaction", x));
    else if (k === "card" || k === "cards") vals.forEach((x) => push("Card", x));
    else if (k === "dev" || k === "device" || k === "devices") vals.forEach((x) => push("DeviceProfile", x));
    else if (k === "region" || k === "addr1") vals.forEach((x) => push("BillingRegion", x));
    else if (k === "customer") vals.forEach((x) => push("Customer", x));
  }
  return out;
}

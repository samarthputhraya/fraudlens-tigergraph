// Grows the investigation graph from the event stream, then merges the server's neighbourhood when the run ends.
import type { CaseRow, GraphPayload } from "../api/types";
import type { RunState } from "./investigation";
import { deviceLabel, entityType, nodeKey, parseRef, rawFromServerId, refEntities } from "./entities";

export interface LNode {
  id: string;
  raw: string;
  label: string;
  type: string;
  flagged?: boolean;
  affected?: boolean;
  fraud?: boolean;
  ring?: boolean;
  origin?: string; // what put it on the canvas
}

export interface LEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  ring?: boolean;
}

export interface LGraph {
  nodes: Map<string, LNode>;
  edges: Map<string, LEdge>;
}

function labelFor(type: string, raw: string) {
  if (type === "DeviceProfile") return deviceLabel(raw);
  if (type === "BillingRegion") return `region ${raw.replace(/\.0$/, "")}`;
  return raw;
}

export function emptyGraph(): LGraph {
  return { nodes: new Map(), edges: new Map() };
}

export function buildLiveGraph(row: CaseRow | null | undefined, s: RunState, server: GraphPayload | null): LGraph {
  const g = emptyGraph();
  const node = (type: string, raw: string, extra: Partial<LNode> = {}, label?: string) => {
    if (!raw) return "";
    const id = nodeKey(type, raw);
    const cur = g.nodes.get(id);
    const merged: LNode = { ...(cur || { id, raw, type, label: label || labelFor(type, raw) }), ...stripUndef(extra) };
    // flags only ever turn on
    if (cur) for (const f of ["flagged", "affected", "fraud", "ring"] as const) merged[f] = !!(cur[f] || extra[f]);
    if (cur && label) merged.label = label;
    g.nodes.set(id, merged);
    return id;
  };
  const edge = (source: string, target: string, type: string, ring = false) => {
    if (!source || !target || source === target) return;
    const a = `${source}|${target}`;
    const b = `${target}|${source}`;
    if (g.edges.has(a) || g.edges.has(b)) {
      if (ring) g.edges.get(a) && (g.edges.get(a)!.ring = true);
      return;
    }
    g.edges.set(a, { id: a, source, target, type, ring });
  };

  // 1. The alert: flagged transaction, its card and customer.
  let txn = row?.flagged_txn_id || "";
  if (!txn && s.trigger?.text) txn = /\b(3\d{6})\b/.exec(s.trigger.text)?.[1] || "";
  let card = row?.card_id || "";
  if (!card && s.trigger?.text) card = /\b(C\d{3,6}-K\d+)\b/.exec(s.trigger.text)?.[1] || "";
  const cust = row?.customer_id || (card ? card.split("-")[0] : "");
  const T = node("Transaction", txn, { flagged: true, origin: "alert" });
  const C = node("Card", card, { origin: "alert" });
  const U = node("Customer", cust, { origin: "alert" });
  edge(C, T, "MADE");
  edge(U, C, "OWNS");

  const devices: string[] = [];
  const addDevice = (d: string) => {
    const id = node("DeviceProfile", d, { origin: "query" });
    edge(T, id, "FROM_DEVICE");
    if (!devices.includes(id)) devices.push(id);
    return id;
  };

  // 2. Every query the agents ran: place the device / region nodes they probe.
  for (const c of s.toolCalls) {
    for (const e of refEntities(c.ref)) {
      if (e.type === "DeviceProfile") addDevice(e.id);
      else if (e.type === "BillingRegion") edge(T, node("BillingRegion", e.id, { origin: "query" }), "BILLED_IN");
      else if (e.type === "Transaction" && e.id !== txn) edge(C, node("Transaction", e.id, { origin: "query" }), "MADE");
    }
  }

  // 3. Findings: the entities each claim rests on.
  for (const f of s.findings) {
    const p = parseRef(f.ref || "");
    const dev = p && typeof p.params.dev === "string" ? addDevice(p.params.dev) : "";
    const isNetwork = f.family === "network" || /shared|ring|device_neighbors/.test(`${f.key} ${f.ref}`);
    for (const raw of (f.entity_ids || []) as string[]) {
      const t = entityType(raw);
      if (t === "Transaction") {
        if (raw !== txn) edge(C, node("Transaction", raw, { origin: "finding" }), "MADE");
      } else if (t === "Card") {
        if (raw === card) continue;
        const id = node("Card", raw, { ring: isNetwork, origin: "finding" });
        if (dev) edge(id, dev, "CARD_DEVICE", isNetwork);
        else edge(C, id, "RING_LINK", isNetwork);
      } else if (t === "Customer") edge(node("Customer", raw, { origin: "finding" }), C, "OWNS");
      else if (t === "DeviceProfile") addDevice(raw);
      else if (t === "ClosedCase") edge(node("ClosedCase", raw, { origin: "finding" }), C, "ON_CARD");
      else if (t === "BillingRegion") edge(T, node("BillingRegion", raw, { origin: "finding" }), "BILLED_IN");
    }
  }

  // 4. Decision: the fraud episode, and the case the agent opens.
  const verdict = s.decision?.verdict || s.answer?.case.verdict;
  const caseId = s.trigger?.case_id || row?.case_id || "";
  const caseLabel = s.answer?.case.graph_case_id || caseId;
  let K = "";
  if (s.decision) {
    for (const t of (s.decision.episode || []) as string[]) {
      const id = node("Transaction", t, { affected: true, fraud: verdict === "fraud", origin: "decision" });
      if (t !== txn) edge(C, id, "MADE");
    }
    if (verdict === "fraud" && txn) node("Transaction", txn, { affected: true, fraud: true });
    K = node("InvestigationCase", caseId, { origin: "decision" }, caseLabel);
    edge(K, T, "CASE_TXN");
  }

  // 5. Case memory: similar closed cases the precedent analyst retrieved.
  for (const cc of (s.memory?.similar || []) as string[]) {
    const id = node("ClosedCase", cc, { origin: "memory" });
    edge(K || C, id, "CASE_CITES");
  }

  // 6. Final answer: the ring and the episode, exactly as written in the case file.
  const a = s.answer;
  if (a) {
    for (const d of a.case.connected_device_profiles || []) addDevice(d);
    for (const c of a.case.connected_card_ids || []) {
      const id = node("Card", c, { ring: true, origin: "answer" });
      if (devices.length) edge(id, devices[0], "CARD_DEVICE", true);
      else edge(C, id, "RING_LINK", true);
    }
    for (const t of a.case.affected_txn_ids || []) {
      const id = node("Transaction", t, { affected: true, fraud: a.case.verdict === "fraud", origin: "answer" });
      if (t !== txn) edge(C, id, "MADE");
    }
  }

  // 7. Server neighbourhood (GET /api/graph/{id}) after the run.
  if (server) {
    const map = new Map<string, string>();
    for (const n of server.nodes || []) {
      const raw = rawFromServerId(n.id);
      const type = n.type || entityType(raw);
      const id = node(
        type,
        raw,
        { flagged: !!n.flagged, affected: !!n.affected, fraud: !!n.fraud, ring: !!n.ring, origin: "graph" },
        type === "DeviceProfile"
          ? deviceLabel(raw)
          : type === "Transaction" && n.label && n.label !== raw
            ? `${raw}\n${n.label}`
            : n.label || raw,
      );
      map.set(n.id, id);
    }
    for (const e of server.edges || []) {
      const s1 = map.get(e.source);
      const t1 = map.get(e.target);
      if (s1 && t1) {
        const ring = !!(g.nodes.get(s1)?.ring || g.nodes.get(t1)?.ring) && /DEVICE|RING/.test(e.type);
        edge(s1, t1, e.type, ring);
      }
    }
  }
  return g;
}

function stripUndef<T extends object>(o: T): Partial<T> {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== false) (out as any)[k] = v;
  return out;
}

// Node ids a tool call touches (for the probe flash).
export function probeTargets(ref: string): string[] {
  return refEntities(ref).map((e) => nodeKey(e.type, e.id));
}

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import { Maximize2, Tag } from "lucide-react";
import type { LGraph, LNode } from "../lib/liveGraph";
import { cx } from "./ui";

export const NODE_STYLE: Record<string, { color: string; shape: string; w: number; h: number; label: string }> = {
  Transaction: { color: "#5EA8FF", shape: "round-rectangle", w: 16, h: 16, label: "Transaction" },
  Card: { color: "#D7DEE8", shape: "round-rectangle", w: 26, h: 17, label: "Card" },
  Customer: { color: "#A48BFA", shape: "ellipse", w: 22, h: 22, label: "Customer" },
  DeviceProfile: { color: "#2FD3BE", shape: "hexagon", w: 34, h: 30, label: "Device profile" },
  ClosedCase: { color: "#F277B5", shape: "diamond", w: 22, h: 22, label: "Closed case" },
  InvestigationCase: { color: "#F58025", shape: "star", w: 30, h: 30, label: "This investigation" },
  BillingRegion: { color: "#96A1B3", shape: "triangle", w: 20, h: 18, label: "Billing region" },
  Account: { color: "#7C8AA0", shape: "barrel", w: 20, h: 18, label: "Account" },
  EmailDomain: { color: "#B6C27A", shape: "vee", w: 18, h: 18, label: "Email domain" },
  Other: { color: "#6A7688", shape: "ellipse", w: 14, h: 14, label: "Other" },
};

let registered = false;
function ensureFcose() {
  if (!registered) {
    cytoscape.use(fcose);
    registered = true;
  }
}

const styleFor = (t: string) => NODE_STYLE[t] || NODE_STYLE.Other;

function toElements(g: LGraph): ElementDefinition[] {
  const els: ElementDefinition[] = [];
  for (const n of g.nodes.values()) {
    const s = styleFor(n.type);
    const cls = [n.type, n.flagged && "flagged", n.affected && "affected", n.fraud && "fraud", n.ring && "ring"].filter(Boolean).join(" ");
    els.push({
      group: "nodes",
      data: { id: n.id, label: n.label, type: n.type, raw: n.raw, color: s.color, w: s.w, h: s.h, shape: s.shape, origin: n.origin },
      classes: cls,
    });
  }
  for (const e of g.edges.values()) {
    els.push({ group: "edges", data: { id: e.id, source: e.source, target: e.target, type: e.type }, classes: e.ring ? "ring" : "" });
  }
  return els;
}

const STYLESHEET: any[] = [
  {
    selector: "node",
    style: {
      "background-color": "data(color)",
      "background-opacity": 0.92,
      shape: "data(shape)",
      width: "data(w)",
      height: "data(h)",
      label: "data(label)",
      color: "#AEB8C7",
      "font-family": "Inter Variable, Inter, sans-serif",
      "font-size": 8.5,
      "font-weight": 500,
      "text-valign": "bottom",
      "text-halign": "center",
      "text-margin-y": 4,
      "text-wrap": "wrap",
      "text-max-width": "120px",
      "text-outline-color": "#080B0F",
      "text-outline-width": 2,
      "border-width": 1.5,
      "border-color": "#080B0F",
      "underlay-color": "#F58025",
      "underlay-opacity": 0,
      "underlay-padding": 0,
      "underlay-shape": "ellipse",
      "transition-property": "underlay-opacity, underlay-padding, width, height",
      "transition-duration": 450,
    },
  },
  { selector: "node.Card", style: { "font-family": "JetBrains Mono Variable, monospace", "font-size": 7.5 } },
  { selector: "node.Transaction", style: { "font-family": "JetBrains Mono Variable, monospace", "font-size": 8 } },
  { selector: "node.ClosedCase", style: { "font-family": "JetBrains Mono Variable, monospace", "font-size": 8, color: "#F7A8D0" } },
  { selector: "node.DeviceProfile", style: { "font-size": 9, color: "#8DEBDD", "font-weight": 600 } },
  { selector: "node.InvestigationCase", style: { "font-size": 10, color: "#FBB27A", "font-weight": 700, "font-family": "JetBrains Mono Variable, monospace" } },
  {
    selector: "node.ring",
    style: {
      "border-color": "#EF5A50",
      "border-width": 2,
      "underlay-color": "#EF5A50",
      "underlay-opacity": 0.32,
      "underlay-padding": 3.5,
      color: "#FFB4AD",
    },
  },
  { selector: "node.Card.ring", style: { "background-color": "#F2A7A1" } },
  { selector: "node.affected", style: { "background-color": "#EF5A50", "border-color": "#FFB4AD", "border-width": 1.5 } },
  {
    selector: "node.flagged",
    style: {
      width: 26,
      height: 26,
      "background-color": "#F58025",
      "border-color": "#FFE2CC",
      "border-width": 2.5,
      color: "#FFD2AE",
      "font-size": 10,
      "font-weight": 700,
      "underlay-color": "#F58025",
      "underlay-opacity": 0.3,
      "underlay-padding": 8,
    },
  },
  { selector: "node.flagged.fraud", style: { "background-color": "#EF5A50", "border-color": "#FFD2AE" } },
  { selector: "node.flagged.pulse", style: { "underlay-opacity": 0.08, "underlay-padding": 17 } },
  { selector: "node.probe", style: { "underlay-color": "#FFFFFF", "underlay-opacity": 0.35, "underlay-padding": 12 } },
  { selector: "node.fresh", style: { "underlay-opacity": 0.5, "underlay-padding": 9 } },
  { selector: "node:selected", style: { "border-color": "#F58025", "border-width": 3 } },
  { selector: "node.dim", style: { opacity: 0.25 } },
  { selector: ".hide-label", style: { label: "" } },
  {
    selector: "edge",
    style: {
      width: 1.2,
      "line-color": "#344052",
      "curve-style": "straight",
      opacity: 0.85,
      "transition-property": "line-color, width, opacity",
      "transition-duration": 450,
    },
  },
  { selector: "edge.ring", style: { "line-color": "#8A3B35", width: 1.4 } },
  { selector: "edge.probe", style: { "line-color": "#F58025", width: 2.4 } },
  { selector: "edge.dim", style: { opacity: 0.15 } },
];

export function GraphLegend({ types }: { types: string[] }) {
  const shown = Object.entries(NODE_STYLE).filter(([t]) => types.includes(t));
  return (
    <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-[11px] text-ink-300">
      {shown.map(([t, s]) => (
        <span key={t} className="inline-flex items-center gap-1.5">
          <Swatch shape={s.shape} color={s.color} />
          {s.label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full border-2 border-fraud bg-[#F2A7A1] shadow-[0_0_8px_#EF5A50]" />
        Ring member
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-fraud" />
        Fraud episode
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm border-2 border-[#FFE2CC] bg-tg-500" />
        Flagged
      </span>
    </div>
  );
}

function Swatch({ shape, color }: { shape: string; color: string }) {
  const p: Record<string, string> = {
    hexagon: "polygon(25% 5%, 75% 5%, 100% 50%, 75% 95%, 25% 95%, 0% 50%)",
    diamond: "polygon(50% 0, 100% 50%, 50% 100%, 0 50%)",
    triangle: "polygon(50% 0, 100% 100%, 0 100%)",
    star: "polygon(50% 0,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%)",
    vee: "polygon(0 0, 50% 40%, 100% 0, 50% 100%)",
  };
  return (
    <span
      className={cx("inline-block h-2.5 w-2.5", shape === "ellipse" ? "rounded-full" : shape.includes("rect") ? "rounded-[2px]" : "")}
      style={{ background: color, clipPath: p[shape] }}
    />
  );
}

interface Props {
  graph: LGraph;
  probe?: { ids: string[]; n: number } | null;
  className?: string;
  layoutName?: "cose" | "concentric";
  onSelect?: (n: LNode | null) => void;
}

export function GraphCanvas({ graph, probe, className, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const layoutTimer = useRef<ReturnType<typeof setTimeout>>();
  const [hover, setHover] = useState<{ x: number; y: number; n: LNode } | null>(null);
  const [labels, setLabels] = useState(true);
  const graphRef = useRef(graph);
  graphRef.current = graph;

  const elements = useMemo(() => toElements(graph), [graph]);

  // mount
  useEffect(() => {
    if (!host.current) return;
    ensureFcose();
    const cy = cytoscape({
      container: host.current,
      elements: [],
      style: STYLESHEET,
      minZoom: 0.25,
      maxZoom: 3,
      wheelSensitivity: 0.25,
      boxSelectionEnabled: false,
    });
    cyRef.current = cy;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let on = false;
    const pulse = reduce
      ? undefined
      : setInterval(() => {
          on = !on;
          cy.nodes(".flagged").toggleClass("pulse", on);
        }, 900);
    cy.on("mouseover", "node", (e) => {
      const n = graphRef.current.nodes.get(e.target.id());
      const p = e.target.renderedPosition();
      if (n) setHover({ x: p.x, y: p.y, n });
      const nb = e.target.closedNeighborhood();
      cy.elements().not(nb).addClass("dim");
    });
    cy.on("mouseout", "node", () => {
      setHover(null);
      cy.elements().removeClass("dim");
    });
    cy.on("tap", "node", (e) => onSelect?.(graphRef.current.nodes.get(e.target.id()) || null));
    cy.on("tap", (e) => e.target === cy && onSelect?.(null));
    cy.on("pan zoom", () => setHover(null));
    const ro = new ResizeObserver(() => {
      cy.resize();
    });
    ro.observe(host.current);
    return () => {
      if (pulse) clearInterval(pulse);
      ro.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // sync elements (add new, update classes/data, remove stale)
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const want = new Set(elements.map((e) => e.data.id as string));
    const added: string[] = [];
    cy.batch(() => {
      cy.elements().forEach((el) => {
        if (!want.has(el.id())) el.remove();
      });
      const center = { x: cy.width() / 2, y: cy.height() / 2 };
      for (const el of elements) {
        const id = el.data.id as string;
        const cur = cy.getElementById(id);
        if (cur.nonempty()) {
          cur.data(el.data);
          const keep = ["pulse", "probe", "fresh", "dim"].filter((c) => cur.hasClass(c));
          cur.classes([el.classes || "", ...keep].join(" "));
          continue;
        }
        if (el.group === "nodes") {
          // place new nodes next to a neighbour already on the canvas so growth reads as branching
          const nb = elements.find(
            (e) => e.group === "edges" && (e.data.source === id || e.data.target === id) && cy.getElementById(e.data.source === id ? e.data.target : e.data.source).nonempty(),
          );
          const anchorId = nb ? (nb.data.source === id ? nb.data.target : nb.data.source) : null;
          const anchor = anchorId ? cy.getElementById(anchorId).position() : cy.nodes().length ? cy.nodes()[0].position() : null;
          const base = anchor || { x: 0, y: 0 };
          const pos = cy.nodes().length ? { x: base.x + (Math.random() - 0.5) * 60, y: base.y + (Math.random() - 0.5) * 60 } : { x: 0, y: 0 };
          cy.add({ ...el, position: pos });
          added.push(id);
          void center;
        }
      }
      for (const el of elements) {
        if (el.group !== "edges") continue;
        if (cy.getElementById(el.data.id as string).nonempty()) continue;
        if (cy.getElementById(el.data.source as string).empty() || cy.getElementById(el.data.target as string).empty()) continue;
        cy.add(el);
      }
    });
    cy.nodes().toggleClass("hide-label", !labels && cy.nodes().length > 0);
    cy.nodes(".flagged, .DeviceProfile, .InvestigationCase").removeClass("hide-label");
    if (added.length) {
      const fresh = byIds(cy, added);
      fresh.style("opacity", 0);
      fresh.animate({ style: { opacity: 1 } } as any, { duration: 500, complete: () => fresh.removeStyle("opacity") } as any);
      fresh.addClass("fresh");
      setTimeout(() => fresh.removeClass("fresh"), 900);
      clearTimeout(layoutTimer.current);
      layoutTimer.current = setTimeout(() => runLayout(cy, added.length > 6 || cy.nodes().length === added.length), 120);
    }
  }, [elements, labels]);

  // flash the node(s) a query is probing
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !probe?.ids.length) return;
    const hit = byIds(cy, probe.ids);
    if (!hit.length) return;
    hit.addClass("probe");
    const edges = hit.connectedEdges();
    edges.addClass("probe");
    // never cancelled: queries arrive faster than the flash, and every flash must clear itself
    setTimeout(() => {
      if (cy.destroyed()) return;
      hit.removeClass("probe");
      edges.removeClass("probe");
    }, 650);
  }, [probe?.n]);

  return (
    <div className={cx("relative h-full w-full overflow-hidden canvas-grid", className)}>
      <div ref={host} className="absolute inset-0" aria-label="Investigation graph" role="img" />
      <div className="absolute right-3 top-3 flex gap-1.5">
        <button
          onClick={() => setLabels((l) => !l)}
          className={cx(
            "rounded-md border px-2 py-1 text-[11px] transition-colors",
            labels ? "border-ink-600 bg-ink-800/90 text-ink-200" : "border-ink-700 bg-ink-900/80 text-ink-400",
          )}
          title="Show or hide node labels"
        >
          <Tag size={12} className="mr-1 inline" />
          Labels
        </button>
        <button
          onClick={() => cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: 40 } } as any, { duration: 400 })}
          className="rounded-md border border-ink-600 bg-ink-800/90 px-2 py-1 text-[11px] text-ink-200"
          title="Fit graph to view"
        >
          <Maximize2 size={12} className="mr-1 inline" />
          Fit
        </button>
      </div>
      {hover && (
        <div
          className="pointer-events-none absolute z-10 w-max max-w-[320px] -translate-x-1/2 rounded-lg border border-ink-600 bg-ink-800/95 px-3 py-2 text-xs shadow-panel"
          style={{ left: hover.x, top: hover.y + 22 }}
        >
          <div className="text-ink-400">{styleFor(hover.n.type).label}</div>
          <div className="mt-0.5 break-all font-mono text-[11.5px] text-ink-100">{hover.n.raw}</div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[10.5px]">
            {hover.n.flagged && <span className="text-tg-400">flagged by the alert</span>}
            {hover.n.affected && <span className="text-fraud">in the fraud episode</span>}
            {hover.n.ring && <span className="text-fraud">shares the device ring</span>}
            {hover.n.origin && <span className="text-ink-400">added from {hover.n.origin}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function byIds(cy: Core, ids: string[]) {
  let c = cy.collection();
  for (const id of ids) {
    const el = cy.getElementById(id);
    if (el.nonempty()) c = c.union(el);
  }
  return c;
}

function runLayout(cy: Core, global: boolean) {
  const n = cy.nodes().length;
  if (!n) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const big = n > 18;
  cy.layout({
    name: "fcose",
    quality: "proof",
    randomize: global,
    animate: !reduce,
    animationDuration: 750,
    animationEasing: "ease-out-cubic",
    fit: true,
    padding: 56,
    nodeDimensionsIncludeLabels: true,
    uniformNodeDimensions: false,
    packComponents: true,
    nodeRepulsion: () => (big ? 7500 : 12000),
    idealEdgeLength: (e: any) => (e.hasClass("ring") ? 95 : big ? 70 : 95),
    edgeElasticity: () => 0.45,
    nestingFactor: 0.1,
    gravity: 0.3,
    gravityRange: 3.8,
    numIter: 2500,
    tile: true,
    nodeSeparation: 80,
  } as any).run();
}

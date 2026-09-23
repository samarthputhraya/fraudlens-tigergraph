import { NavLink, useLocation } from "react-router-dom";
import { Inbox, Radar, FileText, Stamp, LineChart } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useApiState } from "../api";
import { cx, Tooltip } from "./ui";
import { LensMark } from "./LensMark";

const NAV = [
  { to: "/", label: "Queue", full: "Alert queue", icon: Inbox, end: true },
  { to: "/live", label: "Live", full: "Live investigation", icon: Radar },
  { to: "/case", label: "Case file", full: "Case file", icon: FileText },
  { to: "/approvals", label: "Approvals", full: "Approval inbox", icon: Stamp },
  { to: "/insights", label: "Insights", full: "Backtest and portfolio insights", icon: LineChart },
];

function ConnectionPill() {
  const { health, mockReason, online, api } = useApiState();
  const savanna = !!health && /savanna/i.test(health.graph) && api?.mode === "live";
  const mcp = !!health?.mcp && api?.mode === "live";
  const tone = !online && api?.mode === "live" ? "down" : savanna ? "live" : "mirror";
  const text =
    api?.mode === "mock"
      ? "offline mirror"
      : tone === "down"
        ? "API unreachable"
        : savanna
          ? `TigerGraph Savanna${mcp ? " · MCP" : " · REST++"}`
          : health?.graph || "offline mirror";
  const dot = tone === "live" ? "#3CC585" : tone === "down" ? "#EF5A50" : "#EDB341";
  const detail = (
    <div className="space-y-0.5">
      <div>
        <span className="text-ink-400">Graph </span>
        {health?.graph_name || "Fraud"} on {health?.host || "unknown host"}
      </div>
      <div>
        <span className="text-ink-400">Access </span>
        {mcp ? "TigerGraph MCP server" : api?.mode === "mock" ? "bundled fixtures (UI mock)" : "REST++ / local mirror"}
      </div>
      {health?.llm && (
        <div>
          <span className="text-ink-400">Model </span>
          {health.llm}
        </div>
      )}
      {mockReason === "fallback" && <div className="pt-1 text-unsure">/api/health did not answer, so the UI is replaying saved runs.</div>}
      {mockReason === "forced" && <div className="pt-1 text-unsure">VITE_USE_MOCK is set, so the UI is replaying saved runs.</div>}
    </div>
  );
  return (
    <Tooltip content={detail} side="bottom">
      <span
        tabIndex={0}
        className="inline-flex h-8 items-center gap-2 rounded-full border border-ink-700 bg-ink-850 pl-2.5 pr-3 text-xs font-medium text-ink-200"
      >
        <span className="relative flex h-2 w-2">
          {tone === "live" && <span className="absolute inset-0 rounded-full animate-pulsering" style={{ boxShadow: `0 0 0 2px ${dot}` }} />}
          <span className="relative h-2 w-2 rounded-full" style={{ background: dot }} />
        </span>
        {text}
      </span>
    </Tooltip>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { api } = useApiState();
  const loc = useLocation();
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    if (!api) return;
    api
      .approvals()
      .then((xs) => setPending(xs.filter((x) => x.status.startsWith("pending")).length))
      .catch(() => setPending(null));
  }, [api, loc.pathname]);

  const full = /^\/live\//.test(loc.pathname);

  return (
    <div className="flex h-full min-w-[1200px] bg-ink-900">
      {/* Nav rail */}
      <nav className="no-print flex w-[76px] shrink-0 flex-col items-center border-r border-ink-700/80 bg-ink-950 py-3" aria-label="Main">
        <NavLink to="/" className="mb-5 mt-0.5 rounded-lg p-1" aria-label="FraudLens home">
          <LensMark size={34} />
        </NavLink>
        <div className="flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              title={n.full}
              className={({ isActive }) =>
                cx(
                  "group relative flex w-[64px] flex-col items-center gap-1 rounded-lg py-2 text-[10.5px] font-medium transition-colors",
                  isActive ? "bg-ink-800 text-ink-100" : "text-ink-400 hover:bg-ink-850 hover:text-ink-200",
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && <span className="absolute -left-[6px] top-2 bottom-2 w-[3px] rounded-r bg-tg-500" />}
                  <n.icon size={19} strokeWidth={isActive ? 2.2 : 1.8} className={isActive ? "text-tg-500" : undefined} />
                  {n.label}
                  {n.to === "/approvals" && !!pending && (
                    <span className="absolute right-2 top-1 min-w-[16px] rounded-full bg-tg-500 px-1 text-center font-mono text-[9.5px] font-bold leading-4 text-ink-950">
                      {pending}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print flex h-[58px] shrink-0 items-center justify-between gap-6 border-b border-ink-700/80 bg-ink-900/95 px-6">
          <div className="flex min-w-0 items-baseline gap-4">
            <h1 className="whitespace-nowrap text-[17px] font-semibold tracking-[-0.01em] text-ink-100">
              FraudLens <span className="font-normal text-ink-300">Command Center</span>
            </h1>
            <p className="hidden truncate text-[12.5px] text-ink-400 lg:block">
              Powered by <span className="font-medium text-tg-400">TigerGraph</span> · The model predicts. TigerGraph proves.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {api?.mode === "mock" && (
              <span className="rounded-md border border-dashed border-ink-600 px-2 py-1 text-[11px] text-ink-300">Replaying saved runs</span>
            )}
            <ConnectionPill />
          </div>
        </header>
        <main className={cx("min-h-0 flex-1", full ? "overflow-hidden" : "overflow-y-auto scroll-thin")}>{children}</main>
      </div>
    </div>
  );
}

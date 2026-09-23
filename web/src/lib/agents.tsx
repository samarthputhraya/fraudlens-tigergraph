import { Briefcase, CreditCard, Fingerprint, Network, History, ShieldCheck, Radio } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface AgentMeta {
  id: string;
  name: string;
  role: string;
  color: string;
  icon: LucideIcon;
}

export const AGENTS: Record<string, AgentMeta> = {
  lead: { id: "lead", name: "Lead Investigator", role: "Plans the case and decides", color: "#F58025", icon: Briefcase },
  transaction: { id: "transaction", name: "Transaction Analyst", role: "Card history and amounts", color: "#5EA8FF", icon: CreditCard },
  identity: { id: "identity", name: "Identity & Device Analyst", role: "Accounts, devices, proxies", color: "#A48BFA", icon: Fingerprint },
  network: { id: "network", name: "Network & Ring Analyst", role: "Shared devices and rings", color: "#2FD3BE", icon: Network },
  precedent: { id: "precedent", name: "Precedent Analyst", role: "Closed cases and policy memory", color: "#F277B5", icon: History },
  compliance: { id: "compliance", name: "Compliance Reviewer", role: "Checks the decision against policy", color: "#C3CCD8", icon: ShieldCheck },
  system: { id: "system", name: "Alert intake", role: "", color: "#96A1B3", icon: Radio },
};

export const agentOf = (id: string | undefined) => AGENTS[id || "lead"] || AGENTS.lead;

export function AgentAvatar({ id, size = 28, active = false }: { id: string; size?: number; active?: boolean }) {
  const a = agentOf(id);
  const Icon = a.icon;
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center rounded-full"
      style={{
        width: size,
        height: size,
        background: `${a.color}1F`,
        boxShadow: `inset 0 0 0 1px ${a.color}66`,
        color: a.color,
      }}
      aria-label={a.name}
      title={a.name}
    >
      <Icon size={Math.round(size * 0.5)} strokeWidth={2} />
      {active && (
        <span
          className="absolute inset-0 rounded-full animate-pulsering"
          style={{ boxShadow: `0 0 0 2px ${a.color}` }}
        />
      )}
    </span>
  );
}

import { AnimatePresence, motion } from "framer-motion";
import { X, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import {
  createContext, forwardRef, useCallback, useContext, useEffect, useRef, useState,
  type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode,
} from "react";
import { normVerdict, ROUTE_META, statusLabel } from "../../lib/format";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

// ---------- Panel ----------
export function Panel({
  title, aside, children, className, bodyClass, ...rest
}: { title?: ReactNode; aside?: ReactNode; bodyClass?: string } & HTMLAttributes<HTMLDivElement>) {
  return (
    <section className={cx("rounded-xl border border-ink-700 bg-ink-850 shadow-panel", className)} {...rest}>
      {(title || aside) && (
        <header className="flex items-center justify-between gap-3 border-b border-ink-700/70 px-4 py-2.5">
          <h3 className="text-[13px] font-semibold text-ink-100">{title}</h3>
          {aside && <div className="flex items-center gap-2 text-xs text-ink-300">{aside}</div>}
        </header>
      )}
      <div className={cx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

// ---------- Button ----------
type BtnVariant = "primary" | "ghost" | "outline" | "danger" | "success" | "subtle";
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md" }>(
  function Button({ variant = "outline", size = "md", className, ...rest }, ref) {
    const v: Record<BtnVariant, string> = {
      primary: "bg-tg-500 text-ink-950 hover:bg-tg-400 font-semibold",
      outline: "border border-ink-600 bg-ink-800 text-ink-100 hover:border-ink-500 hover:bg-ink-750",
      ghost: "text-ink-200 hover:bg-ink-750 hover:text-ink-100",
      subtle: "bg-ink-750 text-ink-200 hover:bg-ink-700 hover:text-ink-100",
      danger: "border border-fraud-line bg-fraud-soft text-fraud hover:bg-[#4a1c1a]",
      success: "border border-legit-line bg-legit-soft text-legit hover:bg-[#123626]",
    };
    const s = size === "sm" ? "h-7 px-2.5 text-xs gap-1.5" : "h-9 px-3.5 text-[13px] gap-2";
    return (
      <button
        ref={ref}
        className={cx(
          "inline-flex select-none items-center justify-center whitespace-nowrap rounded-lg transition-colors",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-tg-500",
          "disabled:cursor-not-allowed disabled:opacity-40",
          v[variant], s, className,
        )}
        {...rest}
      />
    );
  },
);

// ---------- Badges ----------
export function Badge({ className, children, title }: { className?: string; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4", className)}
    >
      {children}
    </span>
  );
}

const VERDICT_CLS = {
  fraud: "border-fraud-line bg-fraud-soft text-fraud",
  legitimate: "border-legit-line bg-legit-soft text-legit",
  uncertain: "border-unsure-line bg-unsure-soft text-unsure",
};

export function VerdictBadge({ verdict, p, size = "sm" }: { verdict: unknown; p?: number | null; size?: "sm" | "lg" }) {
  const v = normVerdict(verdict);
  if (!v) return <span className="text-xs text-ink-400">Not investigated</span>;
  const label = v === "fraud" ? "Fraud" : v === "legitimate" ? "Legitimate" : "Uncertain";
  return (
    <Badge className={cx(VERDICT_CLS[v], size === "lg" && "px-2.5 py-1 text-sm")}>
      <span className={cx("inline-block rounded-full", size === "lg" ? "h-2 w-2" : "h-1.5 w-1.5")} style={{ background: "currentColor" }} />
      {label}
      {p != null && <span className="ml-0.5 font-mono tabular-nums opacity-80">{p.toFixed(2)}</span>}
    </Badge>
  );
}

const STATUS_CLS: Record<string, string> = {
  escalated: "border-tg-700 bg-[#2a1708] text-tg-300",
  open: "border-[#23466e] bg-[#0f1e30] text-[#8cc2ff]",
  closed_fraud: "border-ink-600 bg-ink-750 text-ink-200",
  closed_legitimate: "border-ink-600 bg-ink-750 text-ink-200",
  new: "border-ink-600 bg-transparent text-ink-300",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge className={STATUS_CLS[status] || "border-ink-600 text-ink-300"}>{statusLabel(status)}</Badge>;
}

export function RouteBadge({ route }: { route: string }) {
  const m = ROUTE_META[route] || ROUTE_META.auto;
  return (
    <Badge className={m.cls} title={`${route}: ${m.who}`}>
      {route !== "auto" && <span className="font-mono text-[10px] opacity-80">{route}</span>}
      {m.label}
    </Badge>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const cls =
    risk === "high" ? VERDICT_CLS.fraud : risk === "medium" ? VERDICT_CLS.uncertain : risk === "low" ? VERDICT_CLS.legitimate : "border-ink-600 text-ink-300";
  return <Badge className={cls}>{risk ? `${risk} risk` : "risk n/a"}</Badge>;
}

export function Mono({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("font-mono text-[12px] tracking-tight text-ink-100", className)}>
      {children}
    </span>
  );
}

export function IdChip({ id, tone = "default", onClick }: { id: string; tone?: "default" | "ring" | "case" | "fraud"; onClick?: () => void }) {
  const t = {
    default: "border-ink-600 bg-ink-800 text-ink-200",
    ring: "border-fraud-line/80 bg-fraud-soft/60 text-[#ffb4ad]",
    case: "border-[#6b2d52] bg-[#2a1222] text-[#f7a8d0]",
    fraud: "border-fraud-line bg-fraud-soft text-fraud",
  }[tone];
  const El = onClick ? "button" : "span";
  return (
    <El
      onClick={onClick}
      title={id}
      className={cx("inline-flex max-w-[22rem] items-center truncate rounded border px-1.5 py-px font-mono text-[11px] leading-4", t, onClick && "hover:border-tg-500")}
    >
      {id}
    </El>
  );
}

// Highlight policy citations like "R2", "R6/R9" and "Section 6" inside reasons.
export function RuleText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/(\bR\d{1,2}\b|\b[Ss]ection \d[a-z]?\b)/g);
  return (
    <span className={className}>
      {parts.map((p, i) =>
        /^(R\d{1,2}|[Ss]ection \d[a-z]?)$/.test(p) ? (
          <span key={i} className="mx-px rounded bg-tg-500/15 px-1 font-mono text-[0.92em] font-semibold text-tg-400">
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </span>
  );
}

// ---------- Segmented control ----------
export function Segmented<T extends string>({
  value, onChange, options, size = "md",
}: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; count?: number }[]; size?: "sm" | "md" }) {
  return (
    <div role="tablist" className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "relative inline-flex items-center gap-1.5 rounded-md font-medium transition-colors",
            size === "sm" ? "h-6 px-2 text-[11px]" : "h-7 px-2.5 text-xs",
            value === o.value ? "bg-ink-700 text-ink-100" : "text-ink-300 hover:text-ink-100",
          )}
        >
          {o.label}
          {o.count != null && <span className="font-mono text-[10px] tabular-nums text-ink-400">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

// ---------- Tooltip ----------
export function Tooltip({ content, children, side = "top", className }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom"; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className={cx("relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      <AnimatePresence>
        {open && (
          <motion.span
            initial={{ opacity: 0, y: side === "top" ? 4 : -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className={cx(
              "pointer-events-none absolute left-1/2 z-50 w-max max-w-xs -translate-x-1/2 rounded-lg border border-ink-600 bg-ink-750 px-2.5 py-1.5 text-xs leading-5 text-ink-100 shadow-panel",
              side === "top" ? "bottom-full mb-2" : "top-full mt-2",
            )}
          >
            {content}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

// ---------- Dialog ----------
export function Dialog({ open, onClose, title, children, width = 520 }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[80] flex items-start justify-center bg-black/60 px-4 pt-[12vh] backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            style={{ width }}
            className="max-w-full rounded-2xl border border-ink-600 bg-ink-800 shadow-panel"
          >
            <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3.5">
              <h2 className="text-[15px] font-semibold text-ink-100">{title}</h2>
              <button onClick={onClose} className="rounded-md p-1 text-ink-300 hover:bg-ink-700 hover:text-ink-100" aria-label="Close">
                <X size={16} />
              </button>
            </div>
            <div className="p-5">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ---------- Popover ----------
export function Popover({ open, onClose, children, className }: { open: boolean; onClose: () => void; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    setTimeout(() => window.addEventListener("mousedown", h), 0);
    window.addEventListener("keydown", k);
    return () => {
      window.removeEventListener("mousedown", h);
      window.removeEventListener("keydown", k);
    };
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          ref={ref}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.14 }}
          className={cx("absolute right-0 top-full z-40 mt-2 rounded-xl border border-ink-600 bg-ink-800 shadow-panel", className)}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ---------- Toasts ----------
type Toast = { id: number; tone: "error" | "success" | "info"; title: string; body?: string };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), t.tone === "error" ? 7000 : 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[90] flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-2">
        <AnimatePresence>
          {items.map((t) => {
            const Icon = t.tone === "error" ? AlertTriangle : t.tone === "success" ? CheckCircle2 : Info;
            const tone = t.tone === "error" ? "border-fraud-line text-fraud" : t.tone === "success" ? "border-legit-line text-legit" : "border-ink-600 text-tg-400";
            return (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 24 }}
                role={t.tone === "error" ? "alert" : "status"}
                className={cx("pointer-events-auto flex gap-3 rounded-xl border bg-ink-800 px-4 py-3 shadow-panel", tone)}
              >
                <Icon size={18} className="mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-ink-100">{t.title}</div>
                  {t.body && <div className="mt-0.5 text-xs leading-5 text-ink-300">{t.body}</div>}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

// ---------- Misc ----------
export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="text-ink-400">{icon}</div>}
      <div className="text-sm font-medium text-ink-200">{title}</div>
      {children && <div className="max-w-md text-xs leading-5 text-ink-400">{children}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cx("animate-shimmer rounded-md", className)}
      style={{ backgroundImage: "linear-gradient(90deg,#12171F 0%,#1B222D 50%,#12171F 100%)", backgroundSize: "200% 100%" }}
    />
  );
}

export function Stat({ label, value, sub, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cx("min-w-0", className)}>
      <div className="text-xs text-ink-400">{label}</div>
      <div className="mt-0.5 truncate text-[15px] font-semibold text-ink-100">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-ink-400">{sub}</div>}
    </div>
  );
}

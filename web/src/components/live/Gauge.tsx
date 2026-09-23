import { animate } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { STOP_HI, STOP_LO } from "../../lib/ledger";

export function useAnimatedNumber(target: number | null, duration = 0.9) {
  const [v, setV] = useState(target ?? 0);
  const prev = useRef(target ?? 0);
  useEffect(() => {
    if (target == null) return;
    const c = animate(prev.current, target, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (x) => {
        prev.current = x;
        setV(x);
      },
    });
    return () => c.stop();
  }, [target, duration]);
  return v;
}

export const bandColor = (p: number) => (p >= STOP_HI ? "#EF5A50" : p <= STOP_LO ? "#3CC585" : "#EDB341");

const W = 280;
const H = 160;
const CX = W / 2;
const CY = 142;
const R = 112;

const pt = (p: number, r = R) => {
  const a = Math.PI * (1 - p);
  return { x: CX + r * Math.cos(a), y: CY - r * Math.sin(a) };
};

function arc(p0: number, p1: number, r = R) {
  const a = pt(p0, r);
  const b = pt(p1, r);
  const large = p1 - p0 > 0.5 ? 1 : 0;
  return `M ${a.x} ${a.y} A ${r} ${r} 0 ${large} 1 ${b.x} ${b.y}`;
}

export function ProbabilityGauge({ p, prior, state }: { p: number | null; prior: number | null; state: string }) {
  const v = useAnimatedNumber(p);
  const shown = p == null ? null : v;
  const color = shown == null ? "#465265" : bandColor(shown);
  return (
    <div className="relative mx-auto" style={{ width: W, height: H }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Fraud probability ${p == null ? "pending" : p.toFixed(2)}`}>
        <defs>
          <filter id="gglow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {/* track + the two stop-rule zones */}
        <path d={arc(0, 1)} stroke="#1F2733" strokeWidth={14} fill="none" strokeLinecap="butt" />
        <path d={arc(0, STOP_LO)} stroke="#3CC585" strokeOpacity={0.22} strokeWidth={14} fill="none" />
        <path d={arc(STOP_HI, 1)} stroke="#EF5A50" strokeOpacity={0.22} strokeWidth={14} fill="none" />
        {shown != null && shown > 0.001 && (
          <path d={arc(0, Math.min(shown, 0.999))} stroke={color} strokeWidth={14} fill="none" filter="url(#gglow)" />
        )}
        {/* ticks */}
        {[STOP_LO, 0.5, STOP_HI].map((t) => {
          const a = pt(t, R + 11);
          const b = pt(t, R - 11);
          const l = pt(t, R + 22);
          return (
            <g key={t}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={t === 0.5 ? "#465265" : "#96A1B3"} strokeWidth={1.5} />
              <text x={l.x} y={l.y + 3} textAnchor="middle" className="fill-ink-400 font-mono" fontSize="9.5">
                {t.toFixed(2)}
              </text>
            </g>
          );
        })}
        {/* prior marker */}
        {prior != null && (
          <g>
            {(() => {
              const a = pt(prior, R - 9);
              const b = pt(prior, R - 20);
              return <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#E7EBF1" strokeWidth={2} strokeLinecap="round" />;
            })()}
          </g>
        )}
        {shown != null && (
          <circle cx={pt(Math.min(Math.max(shown, 0.001), 0.999)).x} cy={pt(Math.min(Math.max(shown, 0.001), 0.999)).y} r={6} fill="#0A0D12" stroke={color} strokeWidth={3} />
        )}
      </svg>
      <div className="absolute inset-x-0 bottom-1 flex flex-col items-center">
        <div className="text-[44px] font-semibold leading-none tracking-[-0.03em]" style={{ color: shown == null ? "#6A7688" : "#E7EBF1" }}>
          {shown == null ? "—" : shown.toFixed(2)}
        </div>
        <div className="mt-1.5 text-[11.5px] text-ink-400">fraud probability · {state}</div>
      </div>
    </div>
  );
}

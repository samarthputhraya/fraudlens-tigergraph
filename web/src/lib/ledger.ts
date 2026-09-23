// Client mirror of agent/assess.py: lets the gauge move as each finding arrives, before the official assessment.
export const logit = (p: number) => Math.log(p / (1 - p));
export const sigmoid = (x: number) => 1 / (1 + Math.exp(-x));

const BASE_RATE = 0.034;
const SCORE_LR: [number, number][] = [[0.1, 0.14], [0.3, 0.6], [0.5, 2.52], [0.7, 6.04], [0.85, 9.59], [1.01, 24.99]];
const PRIORS: Record<string, number> = { customer_report: 0.6, analyst_request: 0.45 };
const FAMILY_CAP = Math.log(60);
export const P_MIN = 0.03;
export const P_MAX = 0.97;
export const STOP_HI = 0.85;
export const STOP_LO = 0.15;

export function priorFor(trigger: string, score: number | null | undefined) {
  if (trigger === "risk_score") {
    const s = score == null || Number.isNaN(score) ? 0.5 : score;
    const lr = (SCORE_LR.find(([hi]) => s < hi) || SCORE_LR[SCORE_LR.length - 1])[1];
    return sigmoid(logit(BASE_RATE) + Math.log(lr));
  }
  return PRIORS[trigger] ?? 0.4;
}

export function runningP(prior: number, findings: { lr: number; family: string }[]) {
  const fam: Record<string, number> = {};
  for (const f of findings) {
    const w = Math.log(Math.max(f.lr, 1e-6));
    fam[f.family] = (fam[f.family] || 0) + w;
  }
  let total = logit(prior);
  for (const w of Object.values(fam)) total += Math.max(-FAMILY_CAP, Math.min(FAMILY_CAP, w));
  return Math.min(P_MAX, Math.max(P_MIN, sigmoid(total)));
}

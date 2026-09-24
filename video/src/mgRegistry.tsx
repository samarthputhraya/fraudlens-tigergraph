import type React from "react";
import { Architecture } from "./scenes/Architecture";
import { ColdOpen } from "./scenes/ColdOpen";
import { Metrics } from "./scenes/Metrics";
import { Outro } from "./scenes/Outro";

// Motion-graphics scenes, keyed by timeline scene id; the master timeline passes each one `beats`
// (frame offsets of its narration lines) and sizes it through its Sequence.
export type MgProps = { beats: number[] };

export const MG: Record<"cold_open" | "architecture" | "metrics" | "outro", React.FC<MgProps>> = {
  cold_open: ColdOpen,
  architecture: Architecture,
  metrics: Metrics,
  outro: Outro,
};

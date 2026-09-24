import React from "react";
import { Composition, Folder } from "remotion";
import { Architecture } from "./scenes/Architecture";
import { ColdOpen } from "./scenes/ColdOpen";
import { Metrics } from "./scenes/Metrics";
import { Outro } from "./scenes/Outro";

// Preview compositions for the motion-graphics scenes (owned by the motion-graphics work; registered from Root).
// Durations and beats are the final narration timings (src/timeline.ts); the master timeline passes its own.
export const Previews: React.FC = () => (
  <Folder name="MotionGraphics">
    <Composition id="ColdOpen" component={ColdOpen} durationInFrames={913} fps={30} width={1920} height={1080} defaultProps={{ beats: [24, 282, 578] }} />
    <Composition id="Architecture" component={Architecture} durationInFrames={988} fps={30} width={1920} height={1080} defaultProps={{ beats: [14, 328, 647] }} />
    <Composition id="Metrics" component={Metrics} durationInFrames={481} fps={30} width={1920} height={1080} defaultProps={{ beats: [16] }} />
    <Composition id="Outro" component={Outro} durationInFrames={471} fps={30} width={1920} height={1080} defaultProps={{ beats: [20] }} />
  </Folder>
);

import React from "react";
import { Composition } from "remotion";
import { calculateFilmMetadata, Film, filmDefaults } from "./Film";
import "./fonts";
import { Previews } from "./previews";
import { FPS, H, W } from "./theme";

export const Root: React.FC = () => (
  <>
    <Composition
      id="FraudLensDemo"
      component={Film}
      durationInFrames={FPS * 60}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={filmDefaults}
      calculateMetadata={calculateFilmMetadata}
    />
    <Previews />
  </>
);

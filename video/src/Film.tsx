import { Audio } from "@remotion/media";
import React from "react";
import { AbsoluteFill, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig, type CalculateMetadataFunction } from "remotion";
import type { Capture } from "./camera/types";
import { Captions } from "./components/Captions";
import { MG } from "./mgRegistry";
import { directAutonomy, directGovernance, directInvestigate, directProof, directUncertain, ScreenScene } from "./scenes/ScreenScenes";
import { C, FPS } from "./theme";
import { placeScenes, XFADE, type PlacedScene } from "./timeline";

type ScreenId = "investigate" | "proof" | "uncertain" | "governance" | "autonomy";
export type FilmProps = { takes: Record<ScreenId, string>; captures?: Record<string, Capture> };

export const filmDefaults: FilmProps = {
  takes: { investigate: "final3", proof: "final", uncertain: "final", governance: "final", autonomy: "final3" },
};

/** Load every capture log the film needs before rendering, and size the composition from the narration. */
export const calculateFilmMetadata: CalculateMetadataFunction<FilmProps> = async ({ props }) => {
  const captures: Record<string, Capture> = {};
  for (const take of new Set(Object.values(props.takes))) {
    const res = await fetch(staticFile(`capture/${take}/events.json`));
    captures[take] = (await res.json()) as Capture;
  }
  return { durationInFrames: placeScenes().total, props: { ...props, captures } };
};

const DIRECT = { investigate: directInvestigate, proof: directProof, uncertain: directUncertain, governance: directGovernance, autonomy: directAutonomy };

/** Crossfade wrapper for scenes that do not fade themselves. */
const Fade: React.FC<{ children: React.ReactNode; first?: boolean }> = ({ children, first }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const o = interpolate(frame, [0, first ? 1 : XFADE, durationInFrames - XFADE, durationInFrames], [first ? 1 : 0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <AbsoluteFill style={{ opacity: o }}>{children}</AbsoluteFill>;
};

const SceneBody: React.FC<{ sc: PlacedScene; props: FilmProps; first: boolean }> = ({ sc, props, first }) => {
  if (sc.id === "cold_open" || sc.id === "architecture" || sc.id === "metrics" || sc.id === "outro") {
    const Mg = MG[sc.id];
    return (
      <Fade first={first}>
        <Mg beats={sc.beats} />
      </Fade>
    );
  }
  const take = props.takes[sc.id];
  const cap = props.captures?.[take];
  if (!cap) return <AbsoluteFill style={{ background: C.bg }} />;
  return <ScreenScene capture={cap} dir={DIRECT[sc.id](cap, sc)} />;
};

export const Film: React.FC<FilmProps> = (props) => {
  const { scenes, total } = placeScenes();
  const lines = scenes.flatMap((s) => s.lines);
  const voiced = (f: number) => lines.some((l) => f >= l.from - 6 && f <= l.from + l.dur + 4);
  // music: a quiet bed that ducks under the narration and swells slightly in the gaps
  const bed = (f: number) => {
    const fadeIn = interpolate(f, [0, 45], [0, 1], { extrapolateRight: "clamp" });
    const fadeOut = interpolate(f, [total - 110, total - 5], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    let near = 99;
    for (const l of lines) {
      if (f >= l.from && f <= l.from + l.dur) {
        near = 0;
        break;
      }
      near = Math.min(near, Math.abs(f - l.from), Math.abs(f - (l.from + l.dur)));
    }
    const duck = interpolate(near, [0, 14], [0.1, 0.26], { extrapolateRight: "clamp" }); // ~2 dB under the voice vs the draft
    return (voiced(f) ? duck : Math.max(duck, 0.26)) * fadeIn * fadeOut;
  };
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      {scenes.map((sc, i) => (
        <Sequence key={sc.id} from={sc.from} durationInFrames={sc.dur} name={sc.id}>
          <SceneBody sc={sc} props={props} first={i === 0} />
        </Sequence>
      ))}
      {/* the outro says what the lockup already shows on screen, so it has no caption */}
      <Captions lines={lines.filter((l) => l.id !== "out2").map((l) => ({ id: l.id, text: l.text, from: l.from, dur: l.dur }))} />
      {lines.map((l) => (
        <Sequence key={l.id} from={l.from} durationInFrames={l.dur + 10} name={`voice ${l.id}`} layout="none">
          <Audio src={staticFile(l.file)} volume={1} />
        </Sequence>
      ))}
      <Audio src={staticFile("music/bed.wav")} volume={bed} />
    </AbsoluteFill>
  );
};

export const FILM_FPS = FPS;

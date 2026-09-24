/**
 * Finishing pass for the rendered film: loudness to YouTube's -14 LUFS, an SRT caption file for the upload, and a
 * poster frame. Run after `npx remotion render FraudLensDemo out/fraudlens-demo.mp4`.
 *
 * Usage:  node finish.mjs [out/fraudlens-demo.mp4]
 */
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const src = process.argv[2] || "out/fraudlens-demo.mp4";
const base = src.replace(/\.mp4$/, "");
const FPS = 30;

// 1) loudness: two-pass loudnorm (measure, then apply) so the voice sits at a consistent, platform-standard level.
//    ffmpeg prints the measurement as JSON on stderr.
const probe = spawnSync("ffmpeg", ["-hide_banner", "-nostats", "-i", src, "-af", "deesser=i=0.35:m=0.5:f=0.5,loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], { encoding: "utf8" });
const err = probe.stderr || "";
const stats = JSON.parse(err.slice(err.lastIndexOf("{"), err.lastIndexOf("}") + 1));
const af = `deesser=i=0.35:m=0.5:f=0.5,loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=${stats.input_i}:measured_TP=${stats.input_tp}:measured_LRA=${stats.input_lra}:measured_thresh=${stats.input_thresh}:offset=${stats.target_offset}:linear=true`;
execFileSync("ffmpeg", ["-v", "error", "-y", "-i", src, "-c:v", "copy", "-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", `${base}-final.mp4`], { stdio: "inherit" });

// 2) captions for the upload, from the same placement the film uses
const manifest = JSON.parse(fs.readFileSync("public/voice/manifest.json", "utf8"));
const byId = Object.fromEntries(manifest.lines.map((l) => [l.id, l]));
const spec = JSON.parse(fs.readFileSync("src/timeline-spec.json", "utf8"));
const SCENES = spec.scenes;
const XFADE = spec.xfade;
let t = 0;
const cues = [];
for (const sc of SCENES) {
  let local = sc.lead;
  sc.lines.forEach((id, i) => {
    const dur = Math.ceil(byId[id].seconds * FPS);
    cues.push({ from: t + local, to: t + local + dur, text: byId[id].text });
    local += dur;
    if (i < sc.lines.length - 1) local += Array.isArray(sc.gaps) ? sc.gaps[i] ?? 16 : sc.gaps;
  });
  t += local + sc.tail - XFADE;
}
const stamp = (f) => {
  const ms = Math.round((f / FPS) * 1000);
  const h = String(Math.floor(ms / 3600000)).padStart(2, "0");
  const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
  const s = String(Math.floor((ms % 60000) / 1000)).padStart(2, "0");
  return `${h}:${m}:${s},${String(ms % 1000).padStart(3, "0")}`;
};
fs.writeFileSync(`${base}-final.srt`, cues.map((c, i) => `${i + 1}\n${stamp(c.from)} --> ${stamp(c.to)}\n${c.text}\n`).join("\n"));

// 3) poster frame (the lockup at the end of the cold open reads well as a thumbnail)
execFileSync("ffmpeg", ["-v", "error", "-y", "-ss", "26", "-i", `${base}-final.mp4`, "-frames:v", "1", `${base}-poster.jpg`], { stdio: "inherit" });
const dur = execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", `${base}-final.mp4`], { encoding: "utf8" }).trim();
console.log(`final: ${path.resolve(`${base}-final.mp4`)} (${(+dur).toFixed(1)} s, loudness -14 LUFS), captions ${base}-final.srt, poster ${base}-poster.jpg`);

/**
 * Records the real Command Center for the demo film, and remembers exactly where everything was.
 *
 * Playwright drives the app like an analyst would (queue -> live investigation -> case file -> re-prove ->
 * an uncertain case -> approval inbox -> insights) while Chrome's own screencast captures every repaint at
 * 2560x1440 (a 1600x900 layout at device scale 1.6, so a 2x zoom in the edit is still sharp). Every step logs
 * wall-clock time, the click position and the on-screen box of each element the film needs to look at, so the
 * edit (video/src/camera) can zoom to exactly that box, for exactly as long as the narration talks about it.
 *
 * Output (outside OneDrive; frames are large):  %USERPROFILE%\fraudlens-capture\<take>\
 *   frames/fNNNNNN.jpg   frames.json   events.json   screen.mp4 (assembled, constant 30 fps)
 * The assembled screen.mp4 and events.json are copied to video/public/capture/<take>/ for Remotion.
 *
 * Usage:  node capture/record.mjs [--base http://localhost:8000] [--take name] [--only queue,live,...]
 */
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const arg = (k, d) => (process.argv.includes(k) ? process.argv[process.argv.indexOf(k) + 1] : d);
const BASE = arg("--base", "http://localhost:8000").replace(/\/$/, "");
const TAKE = arg("--take", "take-" + new Date().toISOString().slice(0, 16).replace(/[:T]/g, ""));
const ONLY = arg("--only", "") ? arg("--only").split(",") : null;
const CSS = { width: 1600, height: 900 };
const DSF = 1.6;
const RAW = path.join(os.homedir(), "fraudlens-capture", TAKE);
const PUB = path.resolve("public", "capture", TAKE);
fs.mkdirSync(path.join(RAW, "frames"), { recursive: true });
fs.mkdirSync(PUB, { recursive: true });

const events = [];
const frames = [];
const now = () => Date.now() / 1000;
const log = (m) => console.log(`[${(now() - T0).toFixed(1).padStart(6)}s] ${m}`);
const ev = (type, id, extra = {}) => events.push({ t: now(), type, id, ...extra });
let T0 = now();

const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--hide-scrollbars", "--force-color-profile=srgb", "--disable-features=OverlayScrollbar", `--force-device-scale-factor=${DSF}`],
});
const context = await browser.newContext({ viewport: CSS, deviceScaleFactor: DSF, colorScheme: "dark", reducedMotion: "no-preference" });
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
let fi = 0;
cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
  const file = `f${String(fi).padStart(6, "0")}.jpg`;
  fi += 1;
  fs.writeFileSync(path.join(RAW, "frames", file), Buffer.from(data, "base64"));
  frames.push({ t: metadata.timestamp, file, sx: metadata.scrollOffsetX, sy: metadata.scrollOffsetY });
  cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});

// ---- helpers -------------------------------------------------------------------------------------------
const px = (b) => (b ? { x: Math.round(b.x * DSF), y: Math.round(b.y * DSF), w: Math.round(b.width * DSF), h: Math.round(b.height * DSF) } : null);
async function box(loc) {
  try {
    await loc.first().waitFor({ state: "visible", timeout: 15000 });
    return px(await loc.first().boundingBox());
  } catch {
    return null;
  }
}
/** Remember where something is on screen right now (the edit may zoom to it). */
async function focus(id, loc, note = "") {
  const b = await box(loc);
  ev("focus", id, { box: b, note });
  log(`focus ${id} ${b ? `${b.x},${b.y} ${b.w}x${b.h}` : "(not found)"}`);
  return b;
}
let mouse = { x: CSS.width / 2, y: CSS.height / 2 };
/** Glide the real mouse to an element (so hover states show), then click it; log both for the synthetic cursor. */
async function click(id, loc, { dx = 0.5, dy = 0.5 } = {}) {
  await loc.first().waitFor({ state: "visible", timeout: 20000 });
  await loc.first().scrollIntoViewIfNeeded();
  const b = await loc.first().boundingBox();
  const to = { x: b.x + b.width * dx, y: b.y + b.height * dy };
  ev("move", id, { from: { x: mouse.x * DSF, y: mouse.y * DSF }, to: { x: to.x * DSF, y: to.y * DSF } });
  await page.mouse.move(to.x, to.y, { steps: 18 });
  mouse = to;
  await page.waitForTimeout(250);
  ev("click", id, { x: Math.round(to.x * DSF), y: Math.round(to.y * DSF), box: px(b) });
  log(`click ${id}`);
  await page.mouse.click(to.x, to.y);
}
async function hover(id, loc) {
  const b = await loc.first().boundingBox();
  if (!b) return;
  const to = { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  ev("move", id, { from: { x: mouse.x * DSF, y: mouse.y * DSF }, to: { x: to.x * DSF, y: to.y * DSF } });
  await page.mouse.move(to.x, to.y, { steps: 18 });
  mouse = to;
}
const mark = (id, note = "") => {
  ev("mark", id, { note });
  log(`mark ${id} ${note}`);
};
const wait = (ms) => page.waitForTimeout(ms);
const panel = (title) => page.locator("section", { has: page.locator("h3", { hasText: title }) });
async function go(hash) {
  await page.goto(`${BASE}/#${hash}`, { waitUntil: "networkidle" });
  await wait(900);
}

// ---- the shot list ------------------------------------------------------------------------------------
const SCENES = {
  async queue() {
    await go("/");
    await page.locator("tr", { hasText: "HHG-014" }).first().waitFor({ timeout: 30000 });
    mark("queue.ready");
    await focus("queue.table", page.locator("table").first());
    await wait(1800);
    const row = page.locator("tr", { hasText: "HHG-014" }).first();
    await hover("queue.row014", row);
    await focus("queue.row014", row);
    await wait(2200);
    await click("queue.investigate014", row.getByRole("button", { name: /Investigate live|Live/ }));
  },

  async live() {
    await page.waitForURL(/#\/live\/HHG-014/, { timeout: 20000 });
    mark("live.open");
    // A fresh live run (not the saved replay) when the API is live.
    const runLive = page.getByRole("button", { name: "Run live" });
    if (await runLive.count()) await runLive.click().catch(() => {});
    const rerun = page.getByRole("button", { name: /Re-run|Replay/ });
    await focus("live.strip", page.locator("h2", { hasText: "HHG-014" }).locator("xpath=ancestor::div[contains(@class,'border-b')][1]"));
    if (await rerun.count()) await click("live.rerun", rerun);
    mark("live.start");
    const tl = panel("Agent timeline");
    const graph = page.locator('[aria-label="Investigation graph"]');
    const gauge = panel("Fraud probability");
    const nba = panel("Next best action");
    const seen = new Set();
    const deadline = now() + 240;
    // Poll the page and log what the agent has shown so far; the edit keys the camera to these moments.
    while (now() < deadline) {
      const txt = (await page.locator("body").innerText().catch(() => "")) || "";
      const probes = [
        ["tool.device_neighbors", /device_neighbors/],
        ["tool.account_history", /account_history/],
        ["tool.similar_cases", /similar_cases/],
        ["ring.cards", /\d+ ring cards/],
        ["assessment", /Initial and final|Initial\b/],
        ["complete", /Investigation complete/],
      ];
      for (const [id, re] of probes) {
        if (!seen.has(id) && re.test(txt)) {
          seen.add(id);
          mark(`live.${id}`);
          if (id.startsWith("tool.")) await focus(`live.timeline.${id}`, tl);
          if (id === "ring.cards") await focus("live.graph", graph);
          if (id === "assessment") {
            await focus("live.gauge", gauge);
            await focus("live.nba", nba);
          }
        }
      }
      const stats = await page.locator("text=/\\d+ vertices · \\d+ edges/").first().innerText().catch(() => "");
      ev("state", "live.graphsize", { text: stats });
      if (seen.has("complete")) break;
      await wait(500);
    }
    await wait(1500);
    await focus("live.graph.final", graph);
    await focus("live.timeline.final", tl);
    // The UI scrolls the right column to the recommendation when the lead decides; bring the gauge back for the
    // decision beat (0.97 + stop rule), then glide down to the next best action.
    const col = page.locator("div.overflow-y-auto").filter({ has: panel("Fraud probability") }).first();
    await col.evaluate((el) => el.scrollTo({ top: 0, behavior: "smooth" }));
    await wait(1400);
    mark("live.decide.top");
    await focus("live.gauge.final", gauge);
    await focus("live.stoprule", gauge.locator("text=/Stop rule/").first().locator("xpath=.."));
    await focus("live.waterfall", panel("Evidence waterfall"));
    await wait(6500);
    await col.evaluate((el) => el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }));
    await wait(1600);
    mark("live.decide.nba");
    await focus("live.nba.final", nba);
    await wait(7000);
    mark("live.end");
  },

  async proof() {
    await go("/case/HHG-014");
    mark("proof.open");
    await focus("proof.summary", panel("Summary"));
    await wait(1500);
    const ev_ = panel("Evidence");
    await focus("proof.evidence", ev_);
    const row = ev_.locator("tr, li, div", { hasText: /device_neighbors/ }).filter({ has: page.getByRole("button", { name: /Re-prove/ }) }).last();
    await row.scrollIntoViewIfNeeded().catch(() => {});
    await wait(600);
    await focus("proof.evidence.row", row);
    await wait(1500);
    await click("proof.reprove", row.getByRole("button", { name: /Re-prove/ }));
    await page.locator("text=/Latency/").first().waitFor({ timeout: 60000 }).catch(() => {});
    await wait(600);
    await focus("proof.result", page.locator("text=/Latency/").first().locator("xpath=ancestor::div[contains(@class,'w-[460px]')][1]"));
    await wait(4500);
    await page.keyboard.press("Escape");
    await wait(500);
    const sarHead = page.locator("h3", { hasText: "Suspicious activity report" }).first();
    if (await sarHead.count()) {
      await sarHead.scrollIntoViewIfNeeded();
      await page.mouse.wheel(0, 260);
      await wait(1000);
      await focus("proof.sar", sarHead.locator("xpath=ancestor::div[2]"));
      await focus("proof.sar.narrative", page.locator("section", { has: page.locator("h4", { hasText: "Part II. Narrative" }) }).first());
      await wait(6000);
    }
    mark("proof.end");
  },

  async uncertain() {
    await go("/case/HHG-010");
    mark("unc.open");
    await focus("unc.summary", panel("Summary"));
    await wait(1500);
    const model = panel("Evidence").locator("tr, li, div", { hasText: /transaction model/ }).last();
    await model.scrollIntoViewIfNeeded().catch(() => {});
    await wait(700);
    await focus("unc.model", model);
    await wait(3500);
    const nba = panel("Next best action");
    await nba.first().scrollIntoViewIfNeeded();
    await wait(900);
    await focus("unc.nba", nba);
    await wait(5000);
    mark("unc.end");
  },

  async governance() {
    await go("/approvals");
    mark("gov.open");
    const card = page.locator("section", { hasText: "HHG-014" }).first();
    await focus("gov.card", card);
    await click("gov.role.lead", page.getByRole("tab", { name: /Team lead/ }).first());
    await wait(900);
    const sarRow = card.locator("li", { hasText: "FILE_REPORT" }).first();
    await focus("gov.sar.row", sarRow);
    await click("gov.approve.denied", sarRow.getByRole("button", { name: /Approve/ }));
    await wait(700);
    await focus("gov.toast.denied", page.locator("text=/Permission denied|cannot decide/").first());
    await wait(2600);
    await click("gov.role.manager", page.getByRole("tab", { name: /Fraud manager/ }).first());
    await wait(900);
    await click("gov.approve.ok", sarRow.getByRole("button", { name: /Approve/ }));
    await wait(700);
    await focus("gov.toast.ok", page.locator("text=/Approved:/").first());
    await wait(3000);
    mark("gov.end");
  },

  async autonomy() {
    await go("/insights");
    mark("auto.open");
    await focus("auto.page", page.locator("main").first());
    await wait(2500);
    const rings = panel("Fraud rings");
    await rings.scrollIntoViewIfNeeded().catch(() => {});
    await wait(800);
    await focus("auto.rings", rings);
    await wait(3500);
    mark("auto.end");
  },
};

// ---- run ----------------------------------------------------------------------------------------------
await page.goto(`${BASE}/#/`, { waitUntil: "networkidle" });
await wait(1500);
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: CSS.width * DSF, maxHeight: CSS.height * DSF, everyNthFrame: 1 });
T0 = now();
mark("start", `${BASE} ${CSS.width}x${CSS.height}@${DSF}`);
for (const [name, fn] of Object.entries(SCENES)) {
  if (ONLY && !ONLY.includes(name)) continue;
  mark(`scene.${name}`);
  try {
    await fn();
  } catch (e) {
    log(`!! scene ${name} failed: ${e.message.split("\n")[0]}`);
    ev("error", name, { message: String(e.message).slice(0, 300) });
  }
}
mark("end");
await wait(500);
await cdp.send("Page.stopScreencast");
await wait(500);
await browser.close();

// ---- assemble a constant-30fps master for the edit ------------------------------------------------------
fs.writeFileSync(path.join(RAW, "frames.json"), JSON.stringify(frames));
const t0 = frames[0].t;
const lines = ["ffconcat version 1.0"];
frames.forEach((f, i) => {
  const next = i + 1 < frames.length ? frames[i + 1].t : f.t + 0.5;
  lines.push(`file 'frames/${f.file}'`, `duration ${Math.max(0.001, next - f.t).toFixed(4)}`);
});
lines.push(`file 'frames/${frames[frames.length - 1].file}'`);
fs.writeFileSync(path.join(RAW, "frames.ffconcat"), lines.join("\n"));
execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "frames.ffconcat", "-vf", "fps=30,format=yuv420p",
  "-c:v", "libx264", "-preset", "slow", "-crf", "12", "-movflags", "+faststart", path.join(PUB, "screen.mp4")], { cwd: RAW, stdio: "inherit" });
const meta = { take: TAKE, base: BASE, css: CSS, dsf: DSF, width: CSS.width * DSF, height: CSS.height * DSF, t0, fps: 30,
  frames: frames.length, seconds: frames[frames.length - 1].t - t0 };
fs.writeFileSync(path.join(PUB, "events.json"), JSON.stringify({ meta, events: events.map((e) => ({ ...e, t: +(e.t - t0).toFixed(3) })) }, null, 1));
console.log(`\ncaptured ${frames.length} frames over ${meta.seconds.toFixed(1)} s -> ${path.join(PUB, "screen.mp4")}`);
console.log(`events: ${events.length} -> ${path.join(PUB, "events.json")}`);

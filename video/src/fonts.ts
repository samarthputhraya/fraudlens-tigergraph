import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Variable fonts copied from the web app (web/node_modules/@fontsource-variable), loaded before first frame.
export const fontsReady = Promise.all([
  loadFont({ family: "Inter", url: staticFile("fonts/Inter.woff2"), weight: "100 900" }),
  loadFont({ family: "JetBrains Mono", url: staticFile("fonts/JetBrainsMono.woff2"), weight: "100 800" }),
]);

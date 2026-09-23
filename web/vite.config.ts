import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes straight into the FastAPI static folder so `uvicorn` serves the app at `/`.
// The dev server proxies /api to the FastAPI backend; SSE responses are streamed through untouched.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../api/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            // Keep Server-Sent Events unbuffered through the dev proxy.
            if (String(proxyRes.headers["content-type"] || "").includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["x-accel-buffering"] = "no";
              delete proxyRes.headers["content-length"];
            }
          });
        },
      },
    },
  },
});

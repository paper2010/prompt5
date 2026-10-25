import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const webRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    fs: {
      strict: true,
      allow: [webRoot],
      deny: ["**/hidden/**", "**/config.yaml", "**/.env", "**/.env.*"],
    },
    proxy: {
      "/v1": "http://127.0.0.1:8765",
      "/healthz": "http://127.0.0.1:8765",
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});

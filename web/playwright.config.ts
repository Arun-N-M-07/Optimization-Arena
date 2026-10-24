import path from "node:path";
import { loadEnvConfig } from "@next/env";
import { defineConfig } from "@playwright/test";

loadEnvConfig(path.resolve(__dirname, ".."));

// REAL end-to-end: real Next.js, real FastAPI, real Supabase project.
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    {
      command: "../.venv/bin/python -m uvicorn app.main:app --port 8010",
      cwd: "../backend",
      url: "http://127.0.0.1:8010/api/health",
      reuseExistingServer: true,
    },
    { command: "npm run dev", url: "http://localhost:3000", reuseExistingServer: true, timeout: 120_000 },
  ],
});

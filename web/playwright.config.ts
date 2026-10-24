import path from "node:path";
import { loadEnvConfig } from "@next/env";
import { defineConfig } from "@playwright/test";

loadEnvConfig(path.resolve(__dirname, ".."));

// REAL end-to-end: real Next.js, real FastAPI, real Supabase project.
export default defineConfig({
  testDir: "./e2e",
  timeout: 900_000,
  expect: { timeout: 20_000 },   // the database is remote (~1s per round trip)
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    {
      command: "../.venv/bin/python -m uvicorn app.main:app --port 8010",
      env: { JUDGE_PROVIDER: "mock" },   // fake, clearly-labelled judge: nothing is ever executed
      cwd: "../backend",
      url: "http://127.0.0.1:8010/api/health",
      reuseExistingServer: true,
    },
    // Production build, not the dev server: the real CSP and optimisations are what get tested.
    { command: "npm run build && npm run start", url: "http://localhost:3000", reuseExistingServer: true, timeout: 300_000 },
  ],
});

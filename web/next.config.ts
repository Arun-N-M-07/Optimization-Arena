import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// Single source of truth: the repo-root .env (also read by the FastAPI backend).
// forceReload: Next has already loaded (and cached) web/ by now, so a plain call would be a no-op.
loadEnvConfig(path.resolve(__dirname, ".."), process.env.NODE_ENV !== "production", console, true);

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  turbopack: { root: __dirname },
  // Public values only. Inlined so the proxy and client bundles see the repo-root .env too.
  env: {
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "",
  },
  // Same-origin /api/* -> FastAPI. No CORS, one auth path (Supabase bearer token).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;

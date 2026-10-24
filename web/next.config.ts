import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// Single source of truth: the repo-root .env (also read by the FastAPI backend).
loadEnvConfig(path.resolve(__dirname, ".."));

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  turbopack: { root: __dirname },
  // Same-origin /api/* -> FastAPI. No CORS, one auth path (Supabase bearer token).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;

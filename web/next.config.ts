import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// Single source of truth: the repo-root .env (also read by the FastAPI backend).
// forceReload: Next has already loaded (and cached) web/ by now, so a plain call would be a no-op.
loadEnvConfig(path.resolve(__dirname, ".."), process.env.NODE_ENV !== "production", console, true);

const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8010";

const isProd = process.env.NODE_ENV === "production";
const supabase = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseWs = supabase.replace(/^https:/, "wss:");
// Monaco is loaded from jsDelivr by @monaco-editor/react (it falls back to a plain textarea if unreachable).
const CDN = "https://cdn.jsdelivr.net";
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' ${CDN}${isProd ? "" : " 'unsafe-eval'"}`,   // Next injects inline bootstrap scripts; eval only for dev tooling
  `style-src 'self' 'unsafe-inline' ${CDN}`,
  "img-src 'self' data: blob:",
  `font-src 'self' data: ${CDN}`,
  `connect-src 'self' ${supabase} ${supabaseWs} ${CDN}`,
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: csp },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
        ...(isProd ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }] : []),
      ],
    }];
  },
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

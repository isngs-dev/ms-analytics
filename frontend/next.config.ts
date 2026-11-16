import type { NextConfig } from "next";

// The browser only talks to this origin; /api/* is proxied to the FastAPI service so the
// httpOnly session cookie stays same-origin (no CORS, no token in JS).
const API = process.env.API_INTERNAL_URL ?? "http://localhost:8020";

const config: NextConfig = {
  reactStrictMode: true,
  output: "standalone", // small self-contained server for the Docker image
  poweredByHeader: false,
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default config;

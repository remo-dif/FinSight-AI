import type { NextConfig } from "next";

function apiOrigin() {
  const value = process.env.NEXT_PUBLIC_API_URL;
  if (!value) return "";

  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}

const allowedApiOrigin = apiOrigin();
const connectSources = [
  "'self'",
  ...(allowedApiOrigin ? [allowedApiOrigin] : []),
  ...(process.env.NODE_ENV === "development" ? ["http://localhost:8000", "ws:"] : [])
].join(" ");
const scriptSources = [
  "'self'",
  "'unsafe-inline'",
  ...(process.env.NODE_ENV === "development" ? ["'unsafe-eval'"] : [])
].join(" ");

const nextConfig: NextConfig = {
  output: "standalone",
  typedRoutes: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "X-Content-Type-Options",
            value: "nosniff"
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin"
          },
          {
            key: "X-Frame-Options",
            value: "DENY"
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()"
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains"
          },
          {
            key: "Content-Security-Policy",
            value: `default-src 'self'; script-src ${scriptSources}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src ${connectSources}; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`
          }
        ]
      }
    ];
  }
};

export default nextConfig;

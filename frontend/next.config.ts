import type { NextConfig } from "next";

/**
 * The browser never talks to the Python API directly and never sees its token:
 * every call goes through this app's own route handlers (the backend-for-frontend),
 * which attach the token from an httpOnly cookie.
 */
const config: NextConfig = {
  // Build a self-contained server for the runtime container.
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: false,
  experimental: { typedEnv: false },
  async redirects() {
    // The root is not a screen of its own: signed-in users land on the dashboard,
    // and the middleware sends everybody else to /login.
    return [{ source: "/", destination: "/dashboard", permanent: false }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "x-content-type-options", value: "nosniff" },
          { key: "x-frame-options", value: "DENY" },
          { key: "referrer-policy", value: "no-referrer" },
          {
            key: "content-security-policy",
            value: [
              "default-src 'self'",
              "img-src 'self' data:",
              "style-src 'self' 'unsafe-inline'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "frame-ancestors 'none'",
              "object-src 'none'",
              "base-uri 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default config;

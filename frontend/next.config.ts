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
  experimental: {
    typedEnv: false,
    // Server Actions compare the request's Origin against the forwarded host and
    // reject a mismatch as a CSRF precaution. Behind nginx on a non-default port
    // (8543), with the proxy forwarding the full host:port, the two already agree
    // -- this is a defensive backstop for that same origin should any proxy in
    // front of it ever send a bare host without the port.
    serverActions: {
      allowedOrigins: ["172.17.0.100:8543"],
      // Without a fixed key, Next.js generates a random one per server start,
      // which invalidates every Server Action reference a browser tab is still
      // holding as soon as the container restarts -- surfaced as a flood of
      // "Failed to find Server Action" errors. Pinning it via env keeps action
      // IDs valid across restarts and redeploys.
      encryptionKey: process.env.NEXT_SERVER_ACTIONS_ENCRYPTION_KEY,
    },
  },
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

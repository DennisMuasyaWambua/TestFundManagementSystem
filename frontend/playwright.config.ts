import { defineConfig, devices } from "@playwright/test";

/**
 * The end-to-end suite runs against a real API and a real database.
 *
 * It starts the built Next.js server rather than the dev server, so what is tested
 * is what ships. The API is expected to be running already (CI starts it; locally,
 * `docker compose up api` does).
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false, // The scenarios share one database and build on each other.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",

  use: {
    baseURL: process.env.FMS_WEB_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: {
    // The standalone server, the same way the production Docker image runs it --
    // `next start` warns it does not work with `output: standalone` and falls
    // back to a slower, less representative path.
    command: "npm run build && npm run start:standalone",
    url: "http://127.0.0.1:3000/login",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      FMS_API_URL: process.env.FMS_API_URL ?? "http://127.0.0.1:8000/api/v1",
      NODE_ENV: "production",
      PORT: "3000",
    },
  },
});

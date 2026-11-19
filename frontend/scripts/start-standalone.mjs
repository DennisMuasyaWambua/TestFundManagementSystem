#!/usr/bin/env node
// Runs the app the same way the production Docker image does: the standalone
// server built by `output: "standalone"`, not `next start` (which next itself
// warns is the wrong thing to use with that output mode). The e2e suite is
// supposed to test what ships -- this makes that true outside Docker too.
//
// The build's static assets and public files sit next to .next/standalone,
// not inside it; the Dockerfile copies them in on top before starting the
// server, and this does the same thing without a container.
import { cpSync, existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const standalone = join(root, ".next", "standalone");

if (!existsSync(standalone)) {
  console.error(`${standalone} does not exist -- run "npm run build" first.`);
  process.exit(1);
}

cpSync(join(root, ".next", "static"), join(standalone, ".next", "static"), { recursive: true });
cpSync(join(root, "public"), join(standalone, "public"), { recursive: true });

const server = spawn(process.execPath, ["server.js"], {
  cwd: standalone,
  stdio: "inherit",
  env: { ...process.env, PORT: process.env.PORT ?? "3000" },
});
server.on("exit", (code) => process.exit(code ?? 1));

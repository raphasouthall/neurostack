#!/usr/bin/env node
"use strict";

const { execFileSync } = require("child_process");
const path = require("path");
const os = require("os");

const INSTALL_DIR = path.join(os.homedir(), ".local", "share", "neurostack", "repo");

try {
  execFileSync("uv", ["run", "--project", INSTALL_DIR, "python", "-m", "neurostack.cli", ...process.argv.slice(2)], {
    stdio: "inherit",
    env: { ...process.env }
  });
} catch (e) {
  if (e.status != null) process.exit(e.status);
  console.error("Failed to run neurostack. Is it installed? Try: npm rebuild neurostack");
  process.exit(1);
}

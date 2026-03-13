#!/usr/bin/env node
"use strict";

const { execFileSync, execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const INSTALL_DIR = path.join(os.homedir(), ".local", "share", "neurostack", "repo");
const UV_BIN = path.join(os.homedir(), ".local", "bin", "uv");

function which(cmd) {
  try {
    return execSync(`command -v ${cmd}`, { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
  } catch { return null; }
}

// Resolve uv — check PATH first, then common install location
const uv = which("uv") || (fs.existsSync(UV_BIN) ? UV_BIN : null);

if (!uv) {
  console.error(
    "\x1b[31mError:\x1b[0m uv is not installed or not on PATH.\n" +
    "  Fix: npm rebuild neurostack   (will auto-install uv)\n" +
    "  Or:  https://docs.astral.sh/uv/getting-started/installation/"
  );
  process.exit(1);
}

if (!fs.existsSync(path.join(INSTALL_DIR, "pyproject.toml"))) {
  console.error(
    "\x1b[31mError:\x1b[0m NeuroStack not found at " + INSTALL_DIR + "\n" +
    "  Fix: npm rebuild neurostack   (will re-download and set up)"
  );
  process.exit(1);
}

try {
  execFileSync(uv, ["run", "--python", "3.12", "--project", INSTALL_DIR, "python", "-m", "neurostack.cli", ...process.argv.slice(2)], {
    stdio: "inherit",
    env: { ...process.env }
  });
} catch (e) {
  if (e.status != null) process.exit(e.status);
  console.error(
    "\x1b[31mError:\x1b[0m Failed to launch neurostack.\n" +
    "  Try: npm rebuild neurostack\n" +
    "  Debug: " + uv + " run --python 3.12 --project " + INSTALL_DIR + " python -m neurostack.cli --help"
  );
  process.exit(1);
}

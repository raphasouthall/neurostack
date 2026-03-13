#!/usr/bin/env node
"use strict";

const { execSync, execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const INSTALL_DIR = path.join(os.homedir(), ".local", "share", "neurostack", "repo");
const REPO = "https://github.com/raphasouthall/neurostack.git";

function info(msg) { console.log(`  [*] ${msg}`); }
function warn(msg) { console.error(`  [!] ${msg}`); }
function die(msg) { console.error(`  [X] ${msg}`); process.exit(1); }

function which(cmd) {
  try {
    return execSync(`command -v ${cmd}`, { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
  } catch { return null; }
}

function run(cmd, opts = {}) {
  return execSync(cmd, { encoding: "utf8", stdio: "inherit", ...opts });
}

// --- Python check ---
let python = null;
for (const cmd of ["python3.13", "python3.12", "python3.11", "python3"]) {
  if (!which(cmd)) continue;
  try {
    const ver = execSync(`${cmd} -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"`,
      { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
    const [major, minor] = ver.split(".").map(Number);
    if (major >= 3 && minor >= 11) { python = cmd; break; }
  } catch { /* skip */ }
}
if (!python) die("Python 3.11+ is required. Install it and try again.");
info(`Python: ${execSync(`${python} --version`, { encoding: "utf8" }).trim()}`);

// --- FTS5 check ---
try {
  execSync(`${python} -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(c)'); c.close()"`,
    { stdio: ["pipe", "pipe", "pipe"] });
  info("FTS5: available");
} catch {
  die("SQLite FTS5 extension required but not available in your Python build");
}

// --- git check ---
if (!which("git")) die("git is required. Install it and try again.");

// --- uv check/install ---
if (!which("uv")) {
  info("Installing uv...");
  run("curl -LsSf https://astral.sh/uv/install.sh | sh");
  process.env.PATH = `${path.join(os.homedir(), ".local", "bin")}:${process.env.PATH}`;
}
info(`uv: ${execSync("uv --version", { encoding: "utf8" }).trim()}`);

// --- Clone/update ---
if (fs.existsSync(path.join(INSTALL_DIR, ".git"))) {
  info("Updating existing installation...");
  run(`git -C ${INSTALL_DIR} pull --ff-only`);
} else {
  info("Cloning NeuroStack...");
  fs.mkdirSync(path.dirname(INSTALL_DIR), { recursive: true });
  run(`git clone ${REPO} ${INSTALL_DIR}`);
}

// --- Install with uv ---
const mode = process.env.NEUROSTACK_MODE || "lite";
const extraArgs = mode === "community" ? "--extra full --extra community"
               : mode === "full" ? "--extra full"
               : "";
info(`Installing in ${mode} mode...`);
run(`uv sync ${extraArgs}`.trim(), { cwd: INSTALL_DIR });

// --- Config ---
const configDir = path.join(os.homedir(), ".config", "neurostack");
const configFile = path.join(configDir, "config.toml");
if (!fs.existsSync(configFile)) {
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(configFile, `# NeuroStack Configuration
# See: https://github.com/raphasouthall/neurostack#configuration

vault_root = "${os.homedir()}/brain"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "phi3.5"
`);
  info(`Config written: ${configFile}`);
} else {
  info(`Config exists: ${configFile}`);
}

info("NeuroStack installed successfully via npm!");

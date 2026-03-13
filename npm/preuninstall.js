#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const INSTALL_DIR = path.join(os.homedir(), ".local", "share", "neurostack");
const CONFIG_DIR = path.join(os.homedir(), ".config", "neurostack");
const DB_FILE = path.join(INSTALL_DIR, "neurostack.db");

function info(msg) { console.log(`  \x1b[36m▸\x1b[0m ${msg}`); }
function warn(msg) { console.error(`  \x1b[33m▸\x1b[0m ${msg}`); }

console.log("\n  \x1b[1mUninstalling NeuroStack\x1b[0m\n");

// Remove source repo + venv (~/.local/share/neurostack/repo)
const repoDir = path.join(INSTALL_DIR, "repo");
if (fs.existsSync(repoDir)) {
  fs.rmSync(repoDir, { recursive: true, force: true });
  info("Removed source and venv: " + repoDir);
} else {
  info("Source directory not found (already clean)");
}

// Remove database if present
if (fs.existsSync(DB_FILE)) {
  fs.rmSync(DB_FILE, { force: true });
  // Also clean up WAL/SHM journal files
  for (const suffix of ["-wal", "-shm"]) {
    const f = DB_FILE + suffix;
    if (fs.existsSync(f)) fs.rmSync(f, { force: true });
  }
  info("Removed database: " + DB_FILE);
}

// Remove parent dir if empty
if (fs.existsSync(INSTALL_DIR)) {
  try {
    fs.rmdirSync(INSTALL_DIR);
    info("Removed empty directory: " + INSTALL_DIR);
  } catch {
    // Not empty — user may have other files there
    warn("Directory not empty, kept: " + INSTALL_DIR);
  }
}

// Preserve config — user may want to reinstall later
if (fs.existsSync(CONFIG_DIR)) {
  warn("Config preserved: " + CONFIG_DIR);
  warn("To remove manually: rm -rf " + CONFIG_DIR);
}

console.log("\n  \x1b[32m✓ NeuroStack uninstalled.\x1b[0m\n");

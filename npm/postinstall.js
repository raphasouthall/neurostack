#!/usr/bin/env node
"use strict";

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");
const https = require("https");
const { createWriteStream } = require("fs");
const { createGunzip } = require("zlib");

const INSTALL_DIR = path.join(os.homedir(), ".local", "share", "neurostack", "repo");
const TARBALL_URL = "https://github.com/raphasouthall/neurostack/archive/refs/heads/main.tar.gz";
const UV_INSTALL_URL = "https://astral.sh/uv/install.sh";
const UV_BIN_DIR = path.join(os.homedir(), ".local", "bin");
const PYTHON_VERSION = "3.12";

/** Build the direct uv binary download URL for this platform */
function uvDirectUrl() {
  const arch = os.arch();
  const platform = os.platform();
  const archMap = { x64: "x86_64", arm64: "aarch64" };
  const platMap = { linux: "unknown-linux-gnu", darwin: "apple-darwin" };
  const a = archMap[arch];
  const p = platMap[platform];
  if (!a || !p) return null;
  // Use musl on Linux for maximum compatibility (static binary)
  const target = platform === "linux" ? `${a}-unknown-linux-musl` : `${a}-${p}`;
  return `https://github.com/astral-sh/uv/releases/latest/download/uv-${target}.tar.gz`;
}

function info(msg) { console.log(`  \x1b[36m▸\x1b[0m ${msg}`); }
function warn(msg) { console.error(`  \x1b[33m▸\x1b[0m ${msg}`); }
function die(msg) {
  console.error(`\n  \x1b[31m✗\x1b[0m ${msg}\n`);
  process.exit(1);
}

function which(cmd) {
  try {
    return execSync(`command -v ${cmd}`, { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
  } catch { return null; }
}

function run(cmd, opts = {}) {
  return execSync(cmd, { encoding: "utf8", stdio: "inherit", ...opts });
}

function uvCmd() {
  return which("uv") || (fs.existsSync(path.join(UV_BIN_DIR, "uv")) ? path.join(UV_BIN_DIR, "uv") : null);
}

/** Download a URL to a file or string using Node built-in https (follows redirects) */
function download(url, destPath) {
  return new Promise((resolve, reject) => {
    const get = (u) => {
      https.get(u, { headers: { "User-Agent": "neurostack-installer" } }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          return get(res.headers.location);
        }
        if (res.statusCode !== 200) {
          return reject(new Error(`HTTP ${res.statusCode} from ${u}`));
        }
        if (destPath) {
          const ws = createWriteStream(destPath);
          res.pipe(ws);
          ws.on("finish", () => resolve(destPath));
          ws.on("error", reject);
        } else {
          const chunks = [];
          res.on("data", (c) => chunks.push(c));
          res.on("end", () => resolve(Buffer.concat(chunks).toString()));
        }
        res.on("error", reject);
      }).on("error", reject);
    };
    get(url);
  });
}

async function main() {
  console.log("\n  \x1b[1mNeuroStack installer\x1b[0m\n");

  // ── Step 1: Install uv (the only external dependency) ──
  if (!uvCmd()) {
    info("Installing uv (Python package manager)...");
    let installed = false;

    // Try direct binary download first (no curl/wget needed)
    const directUrl = uvDirectUrl();
    if (directUrl) {
      try {
        const tarFile = path.join(os.tmpdir(), `uv-${Date.now()}.tar.gz`);
        await download(directUrl, tarFile);
        fs.mkdirSync(UV_BIN_DIR, { recursive: true });
        run(`tar xzf "${tarFile}" --strip-components=1 -C "${UV_BIN_DIR}"`);
        fs.unlinkSync(tarFile);
        // Ensure executable
        for (const bin of ["uv", "uvx"]) {
          const p = path.join(UV_BIN_DIR, bin);
          if (fs.existsSync(p)) fs.chmodSync(p, 0o755);
        }
        process.env.PATH = `${UV_BIN_DIR}:${process.env.PATH}`;
        installed = true;
      } catch (e) {
        warn(`Direct download failed (${e.message}), trying install script...`);
      }
    }

    // Fallback: official install script (needs curl or wget)
    if (!installed) {
      try {
        const script = await download(UV_INSTALL_URL);
        const tmpFile = path.join(os.tmpdir(), `uv-install-${Date.now()}.sh`);
        fs.writeFileSync(tmpFile, script, { mode: 0o755 });
        run(`sh "${tmpFile}"`, { env: { ...process.env, UV_UNMANAGED_INSTALL: UV_BIN_DIR } });
        fs.unlinkSync(tmpFile);
        process.env.PATH = `${UV_BIN_DIR}:${process.env.PATH}`;
      } catch (e) {
        die(
          `Failed to install uv: ${e.message}\n` +
          `      Install manually: https://docs.astral.sh/uv/getting-started/installation/\n` +
          `      Then re-run: npm rebuild neurostack`
        );
      }
    }
  }
  const uv = uvCmd();
  if (!uv) die("uv installed but not found on PATH. Run: npm rebuild neurostack");
  info(`uv: ${execSync(`"${uv}" --version`, { encoding: "utf8" }).trim()}`);

  // ── Step 2: Install Python via uv (no system Python needed) ──
  info(`Ensuring Python ${PYTHON_VERSION} is available...`);
  try {
    run(`"${uv}" python install ${PYTHON_VERSION}`);
  } catch (e) {
    die(`Failed to install Python ${PYTHON_VERSION} via uv: ${e.message}`);
  }

  // Verify FTS5 in the uv-managed Python
  try {
    run(
      `"${uv}" run --python ${PYTHON_VERSION} python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(c)'); c.close()"`,
      { stdio: ["pipe", "pipe", "pipe"] }
    );
    info("SQLite FTS5: ok");
  } catch {
    warn("FTS5 check skipped — will verify at first run");
  }

  // ── Step 3: Download source tarball (no git needed) ──
  if (fs.existsSync(path.join(INSTALL_DIR, "pyproject.toml"))) {
    // Existing install — try git pull if available, otherwise re-download
    if (fs.existsSync(path.join(INSTALL_DIR, ".git")) && which("git")) {
      info("Updating existing installation...");
      try {
        run(`git -C "${INSTALL_DIR}" pull --ff-only`);
      } catch {
        warn("git pull failed — re-downloading...");
        fs.rmSync(INSTALL_DIR, { recursive: true, force: true });
      }
    } else {
      info("Re-downloading source...");
      fs.rmSync(INSTALL_DIR, { recursive: true, force: true });
    }
  }

  if (!fs.existsSync(path.join(INSTALL_DIR, "pyproject.toml"))) {
    info("Downloading NeuroStack...");
    const tarFile = path.join(os.tmpdir(), `neurostack-${Date.now()}.tar.gz`);
    try {
      await download(TARBALL_URL, tarFile);
      fs.mkdirSync(INSTALL_DIR, { recursive: true });
      // GitHub tarballs extract to neurostack-main/ — strip that prefix
      run(`tar xzf "${tarFile}" --strip-components=1 -C "${INSTALL_DIR}"`);
      fs.unlinkSync(tarFile);
    } catch (e) {
      die(
        `Failed to download source: ${e.message}\n` +
        `      Check your internet connection and try: npm rebuild neurostack`
      );
    }
  }
  info("Source: ok");

  // ── Step 4: Install Python dependencies ──
  const mode = process.env.NEUROSTACK_MODE || "full";
  const extraArgs = mode === "community" ? "--extra full --extra community"
                 : mode === "full" ? "--extra full"
                 : "";
  info(`Installing Python dependencies (${mode} mode)...`);
  run(`"${uv}" sync --python ${PYTHON_VERSION} ${extraArgs}`.trim(), { cwd: INSTALL_DIR });

  // ── Step 5: Default config ──
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
    info(`Config: ${configFile}`);
  } else {
    info(`Config exists: ${configFile}`);
  }

  // ── Done ──
  console.log(`
  \x1b[32m✓ NeuroStack installed!\x1b[0m (${mode} mode)

  Get started:
    neurostack init          Set up vault structure
    neurostack index         Index your vault
    neurostack search 'q'    Search
    neurostack doctor        Health check
`);
}

main().catch((e) => {
  die(`Unexpected error: ${e.message}\n      Please report: https://github.com/raphasouthall/neurostack/issues`);
});

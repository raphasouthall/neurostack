#!/usr/bin/env node
"use strict";

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");
const https = require("https");
const { createWriteStream } = require("fs");
const { createGunzip } = require("zlib");

const IS_WIN = os.platform() === "win32";
const PATH_SEP = IS_WIN ? ";" : ":";
const INSTALL_DIR = IS_WIN
  ? path.join(os.homedir(), "AppData", "Local", "neurostack", "repo")
  : path.join(os.homedir(), ".local", "share", "neurostack", "repo");
const TARBALL_URL = "https://github.com/raphasouthall/neurostack/archive/refs/heads/main.tar.gz";
const UV_INSTALL_URL = "https://astral.sh/uv/install.sh";
const UV_BIN_DIR = IS_WIN
  ? path.join(os.homedir(), "AppData", "Local", "neurostack", "bin")
  : path.join(os.homedir(), ".local", "bin");
const PYTHON_VERSION = "3.12";

/** Build the direct uv binary download URL for this platform */
function uvDirectUrl() {
  const arch = os.arch();
  const platform = os.platform();
  const archMap = { x64: "x86_64", arm64: "aarch64" };
  const platMap = { linux: "unknown-linux-gnu", darwin: "apple-darwin", win32: "pc-windows-msvc" };
  const a = archMap[arch];
  const p = platMap[platform];
  if (!a || !p) return null;
  // Use musl on Linux for maximum compatibility (static binary)
  const target = platform === "linux" ? `${a}-unknown-linux-musl` : `${a}-${p}`;
  const ext = platform === "win32" ? ".zip" : ".tar.gz";
  return `https://github.com/astral-sh/uv/releases/latest/download/uv-${target}${ext}`;
}

function info(msg) { console.log(`  \x1b[36m▸\x1b[0m ${msg}`); }
function warn(msg) { console.error(`  \x1b[33m▸\x1b[0m ${msg}`); }
function die(msg) {
  console.error(`\n  \x1b[31m✗\x1b[0m ${msg}\n`);
  process.exit(1);
}

function which(cmd) {
  try {
    const lookup = IS_WIN ? `where ${cmd}` : `command -v ${cmd}`;
    const result = execSync(lookup, { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
    // `where` on Windows may return multiple lines; use the first
    return result.split(/\r?\n/)[0];
  } catch { return null; }
}

function run(cmd, opts = {}) {
  return execSync(cmd, { encoding: "utf8", stdio: "inherit", ...opts });
}

function uvCmd() {
  const bin = IS_WIN ? "uv.exe" : "uv";
  return which("uv") || (fs.existsSync(path.join(UV_BIN_DIR, bin)) ? path.join(UV_BIN_DIR, bin) : null);
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
        const ext = IS_WIN ? ".zip" : ".tar.gz";
        const archiveFile = path.join(os.tmpdir(), `uv-${Date.now()}${ext}`);
        await download(directUrl, archiveFile);
        fs.mkdirSync(UV_BIN_DIR, { recursive: true });
        if (IS_WIN) {
          // Windows: use PowerShell to extract zip
          run(`powershell -NoProfile -Command "Expand-Archive -Path '${archiveFile}' -DestinationPath '${UV_BIN_DIR}' -Force"`);
          // uv zips contain a nested directory — move binaries up
          for (const entry of fs.readdirSync(UV_BIN_DIR)) {
            const nested = path.join(UV_BIN_DIR, entry);
            if (fs.statSync(nested).isDirectory() && entry.startsWith("uv-")) {
              for (const f of fs.readdirSync(nested)) {
                fs.renameSync(path.join(nested, f), path.join(UV_BIN_DIR, f));
              }
              fs.rmSync(nested, { recursive: true });
              break;
            }
          }
        } else {
          run(`tar xzf "${archiveFile}" --strip-components=1 -C "${UV_BIN_DIR}"`);
          // Ensure executable
          for (const bin of ["uv", "uvx"]) {
            const p = path.join(UV_BIN_DIR, bin);
            if (fs.existsSync(p)) fs.chmodSync(p, 0o755);
          }
        }
        fs.unlinkSync(archiveFile);
        process.env.PATH = `${UV_BIN_DIR}${PATH_SEP}${process.env.PATH}`;
        installed = true;
      } catch (e) {
        warn(`Direct download failed (${e.message}), trying install script...`);
      }
    }

    // Fallback: official install script (needs curl or wget on Unix, PowerShell on Windows)
    if (!installed) {
      try {
        if (IS_WIN) {
          run(`powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"`, {
            env: { ...process.env, UV_UNMANAGED_INSTALL: UV_BIN_DIR },
          });
        } else {
          const script = await download(UV_INSTALL_URL);
          const tmpFile = path.join(os.tmpdir(), `uv-install-${Date.now()}.sh`);
          fs.writeFileSync(tmpFile, script, { mode: 0o755 });
          run(`sh "${tmpFile}"`, { env: { ...process.env, UV_UNMANAGED_INSTALL: UV_BIN_DIR } });
          fs.unlinkSync(tmpFile);
        }
        process.env.PATH = `${UV_BIN_DIR}${PATH_SEP}${process.env.PATH}`;
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
      if (IS_WIN) {
        // Windows 10+ has tar; use it with forward-slash paths
        run(`tar xzf "${tarFile}" --strip-components=1 -C "${INSTALL_DIR.replace(/\\/g, "/")}"`);
      } else {
        run(`tar xzf "${tarFile}" --strip-components=1 -C "${INSTALL_DIR}"`);
      }
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
  const mode = process.env.NEUROSTACK_MODE || "lite";
  const extraArgs = mode === "community" ? "--extra full --extra community"
                 : mode === "full" ? "--extra full"
                 : "";
  info(`Installing Python dependencies (${mode} mode)...`);
  run(`"${uv}" sync --python ${PYTHON_VERSION} ${extraArgs}`.trim(), { cwd: INSTALL_DIR });

  // ── Step 5: Create CLI wrapper ──
  const wrapperDir = UV_BIN_DIR;
  fs.mkdirSync(wrapperDir, { recursive: true });
  if (IS_WIN) {
    const wrapperContent = `@echo off\r\n"${uv}" run --project "${INSTALL_DIR}" python -m neurostack.cli %*\r\n`;
    const wrapperPath = path.join(wrapperDir, "neurostack.cmd");
    const aliasPath = path.join(wrapperDir, "ns.cmd");
    fs.writeFileSync(wrapperPath, wrapperContent);
    fs.writeFileSync(aliasPath, wrapperContent);
    info(`CLI wrapper: ${wrapperPath} (alias: ns.cmd)`);
  } else {
    const wrapperContent = `#!/usr/bin/env bash\nexec uv run --project "${INSTALL_DIR}" python -m neurostack.cli "$@"\n`;
    const wrapperPath = path.join(wrapperDir, "neurostack");
    const aliasPath = path.join(wrapperDir, "ns");
    fs.writeFileSync(wrapperPath, wrapperContent);
    fs.chmodSync(wrapperPath, 0o755);
    fs.writeFileSync(aliasPath, wrapperContent);
    fs.chmodSync(aliasPath, 0o755);
    info(`CLI wrapper: ${wrapperPath} (alias: ns)`);
  }

  // ── Step 6: Default config ──
  const configDir = IS_WIN
    ? path.join(os.homedir(), "AppData", "Local", "neurostack")
    : path.join(os.homedir(), ".config", "neurostack");
  const configFile = path.join(configDir, "config.toml");
  if (!fs.existsSync(configFile)) {
    fs.mkdirSync(configDir, { recursive: true });
    fs.writeFileSync(configFile, `# NeuroStack Configuration
# See: https://github.com/raphasouthall/neurostack#configuration
# Run 'neurostack init' to set your vault path and preferences.

embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "phi3.5"
`);
    info(`Config: ${configFile}`);
  } else {
    info(`Config exists: ${configFile}`);
  }

  // ── Step 7: Check PATH ──
  const pathDirs = (process.env.PATH || "").split(PATH_SEP);
  const onPath = pathDirs.some(d => path.resolve(d) === path.resolve(wrapperDir));

  // ── Done ──
  console.log(`
  \x1b[32m✓ NeuroStack installed!\x1b[0m (${mode} mode)
`);
  if (!onPath) {
    if (IS_WIN) {
      console.log(`  \x1b[33m!\x1b[0m Add to PATH (run in PowerShell as admin, or use System Properties > Environment Variables):
    [Environment]::SetEnvironmentVariable("Path", $env:Path + ";${wrapperDir}", "User")
`);
    } else {
      console.log(`  \x1b[33m!\x1b[0m Add to PATH (add to ~/.bashrc or ~/.zshrc):
    export PATH="$HOME/.local/bin:$PATH"
`);
    }
  }
  console.log(`  Get started:
    neurostack init          Set up vault structure
    neurostack index         Index your vault
    neurostack search 'q'    Search
    neurostack doctor        Health check
`);
}

main().catch((e) => {
  die(`Unexpected error: ${e.message}\n      Please report: https://github.com/raphasouthall/neurostack/issues`);
});

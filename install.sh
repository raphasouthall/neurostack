#!/usr/bin/env bash
set -euo pipefail

# NeuroStack Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | bash
# Options: NEUROSTACK_MODE=full (default: lite)

REPO="https://github.com/raphasouthall/neurostack.git"
INSTALL_DIR="${NEUROSTACK_INSTALL_DIR:-$HOME/.local/share/neurostack/repo}"
CONFIG_DIR="$HOME/.config/neurostack"
MODE="${NEUROSTACK_MODE:-lite}"

info()  { echo "  [*] $*"; }
warn()  { echo "  [!] $*" >&2; }
error() { echo "  [X] $*" >&2; exit 1; }

# --- OS Check ---
case "$(uname -s)" in
    Linux)  info "Linux detected" ;;
    Darwin) warn "macOS support is experimental" ;;
    *)      error "Unsupported OS: $(uname -s). NeuroStack requires Linux." ;;
esac

# --- Python Check ---
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major="${ver%%.*}"
        minor="${ver#*.}"
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done
[ -z "$PYTHON" ] && error "Python 3.11+ required. Found: $(python3 --version 2>/dev/null || echo 'none')"
info "Python: $($PYTHON --version)"

# --- FTS5 Check ---
$PYTHON -c "
import sqlite3
conn = sqlite3.connect(':memory:')
conn.execute('CREATE VIRTUAL TABLE t USING fts5(c)')
conn.close()
" 2>/dev/null || error "SQLite FTS5 extension required but not available in your Python build"
info "FTS5: available"

# --- uv Check/Install ---
if ! command -v uv &>/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
info "uv: $(uv --version)"

# --- Clone/Update ---
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning NeuroStack..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO" "$INSTALL_DIR"
fi

# --- Install ---
cd "$INSTALL_DIR"

case "$MODE" in
    lite)
        info "Installing in lite mode (FTS5 only, no ML)..."
        uv sync
        ;;
    full)
        info "Installing in full mode (embeddings + summaries)..."
        uv sync --extra full
        ;;
    community)
        info "Installing with community detection..."
        uv sync --extra full --extra community
        ;;
    *)
        error "Unknown mode: $MODE. Use: lite, full, or community"
        ;;
esac

# --- Create symlink ---
mkdir -p "$HOME/.local/bin"
NEUROSTACK_BIN="$HOME/.local/bin/neurostack"
cat > "$NEUROSTACK_BIN" << WRAPPER
#!/usr/bin/env bash
exec uv run --project "$INSTALL_DIR" python -m neurostack.cli "\$@"
WRAPPER
chmod +x "$NEUROSTACK_BIN"
info "CLI installed: $NEUROSTACK_BIN"

# --- Default Config ---
if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_DIR/config.toml" << TOML
# NeuroStack Configuration
# See: https://github.com/raphasouthall/neurostack#configuration

vault_root = "$HOME/brain"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "qwen2.5:3b"
TOML
    info "Config written: $CONFIG_DIR/config.toml"
else
    info "Config exists: $CONFIG_DIR/config.toml"
fi

# --- Summary ---
echo ""
echo "  NeuroStack installed! ($MODE mode)"
echo ""
echo "  Quick start:"
echo "    neurostack init          # Set up vault structure"
echo "    neurostack index         # Index your vault"
echo "    neurostack search 'q'    # Search"
echo "    neurostack doctor        # Health check"
echo ""
if [ "$MODE" = "lite" ]; then
    echo "  Upgrade to full mode:"
    echo "    NEUROSTACK_MODE=full bash install.sh"
    echo ""
fi

# Check PATH
if ! echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin"; then
    warn "Add ~/.local/bin to your PATH:"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

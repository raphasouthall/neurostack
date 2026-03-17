#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_PORT="${BRIDGE_PORT:-8100}"

cleanup() {
    if [ -n "${BRIDGE_PID:-}" ]; then
        kill "$BRIDGE_PID" 2>/dev/null || true
        wait "$BRIDGE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

cd "$SCRIPT_DIR"

if [ -f .env ]; then
    set -a; source .env; set +a
fi

echo "Starting NeuroStack bridge on port $BRIDGE_PORT ..."
BRIDGE_PORT="$BRIDGE_PORT" python3 bridge/api.py &
BRIDGE_PID=$!

until curl -sf "http://127.0.0.1:${BRIDGE_PORT}/health" >/dev/null 2>&1; do
    if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
        echo "Bridge failed to start" >&2
        exit 1
    fi
    sleep 0.3
done
echo "Bridge ready."

echo "Starting Hyperterse MCP server ..."
exec hyperterse start

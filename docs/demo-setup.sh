#!/usr/bin/env bash
# Pre-seeds a demo vault for VHS recording.
# Run BEFORE the VHS tape: bash docs/demo-setup.sh
set -euo pipefail

DEMO_DIR="/tmp/neurostack-demo-vhs"
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR/vault" "$DEMO_DIR/db"

# Copy the vault-template (84 notes with all profession packs)
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cp -r "$REPO_DIR/vault-template/"* "$DEMO_DIR/vault/"

# Index in lite mode (FTS5 + graph only — fast, no Ollama needed)
export NEUROSTACK_VAULT_ROOT="$DEMO_DIR/vault"
export NEUROSTACK_DB_DIR="$DEMO_DIR/db"
neurostack index --skip-summary --skip-triples 2>&1

echo ""
echo "Demo vault ready. To use:"
echo "  export NEUROSTACK_VAULT_ROOT=$DEMO_DIR/vault"
echo "  export NEUROSTACK_DB_DIR=$DEMO_DIR/db"

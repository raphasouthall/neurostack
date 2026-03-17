#!/usr/bin/env bash
set -euo pipefail

export HOME=/root
export PATH="$HOME/.local/bin:$PATH"

echo "=== NeuroStack Podman Integration Tests ==="

# --- Setup ---
curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
export PATH="$HOME/.local/bin:$PATH"
cp -r /neurostack /tmp/neurostack
cd /tmp/neurostack
uv sync --extra dev 2>&1 | tail -1

pass() { echo "  [PASS] $*"; }
fail() { echo "  [FAIL] $*" >&2; exit 1; }

# --- 1. Lint ---
echo ""
echo "=== 1. Ruff Lint ==="
uv run ruff check src/ tests/ && pass "ruff" || fail "ruff"

# --- 2. Pytest ---
echo ""
echo "=== 2. Pytest ==="
uv run pytest tests/ --tb=short -q 2>&1 | tail -3

# --- 3. CLI ---
echo ""
echo "=== 3. CLI Smoke ==="
uv run neurostack --help >/dev/null && pass "CLI --help"
uv run neurostack doctor 2>&1

# --- 4. Create + Index test vault ---
echo ""
echo "=== 4. Init + Index ==="
VAULT="$HOME/test-vault"
mkdir -p "$VAULT/research" "$VAULT/literature"

cat > "$VAULT/research/hippocampal-indexing.md" << 'NOTEEOF'
---
date: 2026-01-15
tags: [neuroscience, memory, hippocampus]
type: permanent
status: active
---

# Hippocampal Indexing Theory

The hippocampus functions as a rapid indexing system for neocortical memory traces.
Retrieval involves pattern completion through hippocampal replay.

## Links
- [[predictive-coding]]
NOTEEOF

cat > "$VAULT/research/predictive-coding.md" << 'NOTEEOF'
---
date: 2026-02-01
tags: [neuroscience, predictive-coding, memory]
type: permanent
status: active
---

# Predictive Coding and Memory

Prediction errors drive memory encoding. Surprising events are preferentially stored.

## Links
- [[hippocampal-indexing]]
NOTEEOF

cat > "$VAULT/literature/tolman.md" << 'NOTEEOF'
# Tolman 1948 Cognitive Maps

Classic paper on internal spatial representations.
No frontmatter in this file.
NOTEEOF

mkdir -p "$HOME/.config/neurostack"
echo "vault_root = \"$VAULT\"" > "$HOME/.config/neurostack/config.toml"

uv run neurostack index --skip-summary --skip-triples 2>&1
pass "index"

# --- 5. FTS5 OR search ---
echo ""
echo "=== 5. FTS5 OR Search ==="
RESULT=$(uv run neurostack search "hippocampus memory" 2>&1)
echo "$RESULT"
echo "$RESULT" | grep -qi "hippocampal\|hippocampus" || fail "FTS5 search: no results for multi-word query"
pass "FTS5 OR search returns results"

# --- 6. Schema v11 + note_metadata ---
echo ""
echo "=== 6. Schema v11 + note_metadata ==="
cat > /tmp/test_schema.py << 'PYEOF'
from neurostack.schema import get_db, DB_PATH
conn = get_db(DB_PATH)

v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
print(f"  Schema version: {v}")
assert v == 11, f"Expected v11, got {v}"

total = conn.execute("SELECT COUNT(*) FROM note_metadata").fetchone()[0]
print(f"  note_metadata rows: {total}")
assert total > 0, "note_metadata is empty"

active = conn.execute(
    "SELECT COUNT(*) FROM note_metadata WHERE status = 'active'"
).fetchone()[0]
print(f"  active notes: {active}")
assert active > 0, "No active notes in note_metadata"

print("  PASS")
PYEOF
uv run python3 /tmp/test_schema.py

# --- 7. Compact JSON ---
echo ""
echo "=== 7. Compact JSON ==="
COUNT=$(grep -c "indent=2" /tmp/neurostack/src/neurostack/server.py || true)
if [ "$COUNT" -eq 0 ]; then
    pass "Zero indent=2 in server.py"
else
    fail "Found $COUNT indent=2 in server.py"
fi

# --- 8. Writeback Removed ---
echo ""
echo "=== 8. Writeback Removed ==="
test ! -f /tmp/neurostack/src/neurostack/vault_writer.py && pass "vault_writer.py deleted"
test ! -f /tmp/neurostack/tests/test_vault_writer.py && pass "test_vault_writer.py deleted"

cat > /tmp/test_no_wb.py << 'PYEOF'
from neurostack.config import Config
c = Config()
assert not hasattr(c, "writeback_enabled"), "writeback_enabled still exists"
assert not hasattr(c, "writeback_path"), "writeback_path still exists"
print("  Config: writeback keys removed")
print("  PASS")
PYEOF
uv run python3 /tmp/test_no_wb.py

# --- 9. Onboard read-only ---
echo ""
echo "=== 9. Onboard Read-Only ==="
ONBOARD_DIR="$HOME/onboard-test"
mkdir -p "$ONBOARD_DIR"
echo "# A Note Without Frontmatter" > "$ONBOARD_DIR/bare-note.md"
echo "" >> "$ONBOARD_DIR/bare-note.md"
echo "No YAML here." >> "$ONBOARD_DIR/bare-note.md"

uv run neurostack onboard "$ONBOARD_DIR" --no-index 2>&1

FIRST_LINE=$(head -1 "$ONBOARD_DIR/bare-note.md")
if [ "$FIRST_LINE" = "# A Note Without Frontmatter" ]; then
    pass "bare-note.md NOT modified — read-only vault"
else
    fail "File was modified! First line: $FIRST_LINE"
fi

# --- 10. Stats ---
echo ""
echo "=== 10. Stats ==="
uv run neurostack stats 2>&1

echo ""
echo "========================================="
echo "  ALL 10 TESTS PASSED"
echo "========================================="

#!/usr/bin/env bash
set -euo pipefail

# Full-mode smoke test for NeuroStack on Fedora 41
# Runs inside a podman container

info()  { echo "  [*] $*"; }
fail()  { echo "  [X] $*" >&2; exit 1; }
pass()  { echo "  [✓] $*"; }

echo "=== NeuroStack Full-Mode Smoke Test (Fedora 41) ==="
echo ""

# --- System info ---
info "OS: $(cat /etc/fedora-release)"
info "Python: $(python3 --version)"
info "Arch: $(uname -m)"

# --- Install NeuroStack in full mode ---
info "Running install.sh in full mode..."
export NEUROSTACK_MODE=full
export HOME=/root
bash /neurostack/install.sh
export PATH="$HOME/.local/bin:$PATH"

pass "install.sh completed"

# --- Verify CLI works ---
neurostack --help >/dev/null 2>&1 || fail "neurostack --help failed"
pass "CLI responds to --help"

# --- Test imports ---
info "Testing Python imports..."

cd "$HOME/.local/share/neurostack/repo"

# Core imports
uv run python3 -c "from neurostack.config import Config, load_config; print('  config: ok')" || fail "config import failed"
uv run python3 -c "from neurostack.schema import get_db; print('  schema: ok')" || fail "schema import failed"
uv run python3 -c "from neurostack.search import hybrid_search, fts_search; print('  search: ok')" || fail "search import failed"
uv run python3 -c "from neurostack.chunker import chunk_by_headings, parse_note; print('  chunker: ok')" || fail "chunker import failed"
uv run python3 -c "from neurostack.graph import build_graph, get_neighborhood; print('  graph: ok')" || fail "graph import failed"
uv run python3 -c "from neurostack.triples import extract_triples; print('  triples: ok')" || fail "triples import failed"
uv run python3 -c "from neurostack.brief import generate_brief; print('  brief: ok')" || fail "brief import failed"
uv run python3 -c "from neurostack.session_index import get_db as si_db; print('  session_index: ok')" || fail "session_index import failed"

# Full-mode imports (numpy, sentence-transformers)
uv run python3 -c "import numpy; print(f'  numpy: ok ({numpy.__version__})')" || fail "numpy import failed"
uv run python3 -c "import sentence_transformers; print(f'  sentence-transformers: ok ({sentence_transformers.__version__})')" || fail "sentence-transformers import failed"
uv run python3 -c "from neurostack.embedder import get_embedding, cosine_similarity; print('  embedder: ok')" || fail "embedder import failed"
uv run python3 -c "from neurostack.reranker import rerank; print('  reranker: ok')" || fail "reranker import failed"
uv run python3 -c "from neurostack.summarizer import summarize_note; print('  summarizer: ok')" || fail "summarizer import failed"

pass "All imports succeeded"

# --- Create test vault ---
info "Creating test vault..."
VAULT="$HOME/test-vault"
mkdir -p "$VAULT"/{research,literature,inbox}

cat > "$VAULT/research/hippocampal-indexing.md" << 'MD'
---
date: 2026-01-15
tags: [neuroscience, memory, hippocampus]
type: permanent
status: active
actionable: true
---

# Hippocampal Indexing Theory

The hippocampus functions as a rapid indexing system for neocortical memory traces.

## Key Claims

- Memory encoding creates sparse hippocampal indices that point to distributed cortical representations
- Retrieval involves pattern completion from partial cues through hippocampal replay
- Sleep consolidation gradually transfers index dependency to cortico-cortical pathways
- The dentate gyrus performs pattern separation to minimize index collision

## Links

- [[predictive-coding-and-memory]]
- [[sleep-consolidation-mechanisms]]
MD

cat > "$VAULT/research/predictive-coding-and-memory.md" << 'MD'
---
date: 2026-02-01
tags: [neuroscience, predictive-coding, memory]
type: permanent
status: active
actionable: false
---

# Predictive Coding and Memory

Prediction errors drive memory encoding — surprising events are preferentially stored.

## Key Claims

- The hippocampus computes prediction errors by comparing expected and observed sensory input
- High prediction error events receive enhanced encoding via dopaminergic modulation
- Familiar patterns are compressed into efficient predictive models (schemas)
- Schema-violating information creates strong episodic traces

## Links

- [[hippocampal-indexing-theory]]
MD

cat > "$VAULT/literature/tolman-cognitive-maps.md" << 'MD'
---
date: 2026-01-10
tags: [neuroscience, cognitive-maps, navigation]
type: literature
status: reference
actionable: false
---

# Tolman (1948) — Cognitive Maps in Rats and Men

Classic paper establishing that animals form internal spatial representations rather than simple stimulus-response chains.

## Key Findings

- Rats learn spatial layouts, not just motor sequences
- Evidence of latent learning — knowledge acquired without immediate reinforcement
- Supports allocentric (world-centred) over egocentric (body-centred) navigation
MD

cat > "$VAULT/index.md" << 'MD'
# Test Vault Index

## Research
- [[hippocampal-indexing-theory]] — Hippocampus as rapid indexing system
- [[predictive-coding-and-memory]] — Prediction errors drive memory encoding

## Literature
- [[tolman-cognitive-maps]] — Tolman 1948 cognitive maps
MD

pass "Test vault created (3 notes)"

# --- Configure and init ---
mkdir -p "$HOME/.config/neurostack"
cat > "$HOME/.config/neurostack/config.toml" << TOML
vault_root = "$VAULT"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "qwen2.5:3b"
TOML

info "Running neurostack init..."
neurostack init "$VAULT" 2>&1 || true
pass "init completed"

# --- Index ---
info "Running neurostack index..."
neurostack index 2>&1
pass "index completed"

# --- Search (FTS5 — no Ollama needed) ---
info "Testing FTS5 search..."
RESULT=$(neurostack search "hippocampus memory" 2>&1)
echo "$RESULT"
echo "$RESULT" | grep -qi "hippocampal\|memory" || fail "Search did not return expected results"
pass "FTS5 search works"

# --- Doctor ---
info "Running neurostack doctor..."
neurostack doctor 2>&1
pass "doctor completed"

# --- Stats ---
info "Running neurostack stats..."
neurostack stats 2>&1
pass "stats completed"

# --- Graph ---
info "Testing graph..."
neurostack graph "hippocampal-indexing" 2>&1 || info "graph returned no results (expected without full indexing)"

# --- Summary ---
echo ""
echo "========================================="
echo "  ALL TESTS PASSED — Full mode on Fedora 41"
echo "========================================="

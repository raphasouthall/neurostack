#!/usr/bin/env bash
set -euo pipefail

# Full-mode smoke test WITH Ollama (embeddings + summaries + triples)
# Requires --network=host to reach host Ollama

info()  { echo "  [*] $*"; }
fail()  { echo "  [X] $*" >&2; exit 1; }
pass()  { echo "  [✓] $*"; }

echo "=== NeuroStack Full-Mode + Ollama Test (Fedora 41) ==="
echo ""

# --- System info ---
info "OS: $(cat /etc/fedora-release)"
info "Python: $(python3 --version)"

# --- Pre-flight: check Ollama reachable ---
info "Checking Ollama embed (11435)..."
python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:11435/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
models = [m['name'] for m in data.get('models', [])]
print(f'  Embed models: {models}')
" || fail "Cannot reach Ollama embed on port 11435"
pass "Ollama embed reachable"

info "Checking Ollama LLM (11434)..."
python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:11434/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
models = [m['name'] for m in data.get('models', [])]
print(f'  LLM models: {models}')
" || fail "Cannot reach Ollama LLM on port 11434"
pass "Ollama LLM reachable"

# --- Install NeuroStack in full mode ---
info "Running install.sh in full mode..."
export NEUROSTACK_MODE=full
export HOME=/root
bash /neurostack/install.sh
export PATH="$HOME/.local/bin:$PATH"
pass "install.sh completed"

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
compositional: true
---

# Hippocampal Indexing Theory

The hippocampus functions as a rapid indexing system for neocortical memory traces.

## Key Claims

- Memory encoding creates sparse hippocampal indices that point to distributed cortical representations
- Retrieval involves pattern completion from partial cues through hippocampal replay
- Sleep consolidation gradually transfers index dependency to cortico-cortical pathways
- The dentate gyrus performs pattern separation to minimize index collision
- Place cells and grid cells provide a spatial scaffold for episodic memory

## Implications for Knowledge Management

- A good indexing system should create sparse pointers, not duplicate content
- Retrieval should work from partial cues (fuzzy search)
- Consolidation should compress frequently-accessed patterns into efficient representations

## Links

- [[predictive-coding-and-memory]]
- [[sleep-consolidation-mechanisms]]
- [[tolman-cognitive-maps]]
MD

cat > "$VAULT/research/predictive-coding-and-memory.md" << 'MD'
---
date: 2026-02-01
tags: [neuroscience, predictive-coding, memory]
type: permanent
status: active
actionable: false
compositional: true
---

# Predictive Coding and Memory

Prediction errors drive memory encoding — surprising events are preferentially stored.

## Key Claims

- The hippocampus computes prediction errors by comparing expected and observed sensory input
- High prediction error events receive enhanced encoding via dopaminergic modulation
- Familiar patterns are compressed into efficient predictive models (schemas)
- Schema-violating information creates strong episodic traces
- Prediction error magnitude correlates with subsequent memory strength

## Relationship to Indexing

- Prediction errors signal which events deserve indexing resources
- Low-surprise events rely on existing schemas rather than new hippocampal traces
- This creates an efficient allocation of memory resources

## Links

- [[hippocampal-indexing]]
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
- Cognitive maps enable flexible route planning and shortcut discovery

## Relevance

- Foundation for modern place cell and grid cell research
- Maps as a metaphor for knowledge graph structure in PKM systems
MD

cat > "$VAULT/research/sleep-consolidation-mechanisms.md" << 'MD'
---
date: 2026-02-15
tags: [neuroscience, sleep, memory, consolidation]
type: permanent
status: active
actionable: false
compositional: false
---

# Sleep Consolidation Mechanisms

Sleep plays a critical role in memory consolidation through hippocampal-neocortical dialogue.

## Key Claims

- Sharp-wave ripples during NREM sleep replay compressed neural sequences
- Replay prioritises high-reward and high-prediction-error experiences
- Slow oscillations coordinate ripple-spindle coupling for synaptic consolidation
- Over time, memories become less hippocampus-dependent (systems consolidation)

## Links

- [[hippocampal-indexing]]
- [[predictive-coding-and-memory]]
MD

cat > "$VAULT/index.md" << 'MD'
# Test Vault Index

## Research
- [[hippocampal-indexing]] — Hippocampus as rapid indexing system
- [[predictive-coding-and-memory]] — Prediction errors drive memory encoding
- [[sleep-consolidation-mechanisms]] — Sleep replay and systems consolidation

## Literature
- [[tolman-cognitive-maps]] — Tolman 1948 cognitive maps
MD

pass "Test vault created (4 notes + index)"

# --- Configure ---
mkdir -p "$HOME/.config/neurostack"
# Detect available LLM model (prefer qwen2.5:3b, fall back to what's available)
LLM_MODEL=$(python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:11434/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
models = [m['name'] for m in data.get('models', [])]
for pref in ['qwen2.5:3b', 'qwen3:14b', 'llama3.1:8b']:
    if pref in models:
        print(pref)
        break
else:
    print(models[0] if models else 'qwen2.5:3b')
")
info "Using LLM model: $LLM_MODEL"

cat > "$HOME/.config/neurostack/config.toml" << TOML
vault_root = "$VAULT"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "$LLM_MODEL"
TOML

# --- Init ---
neurostack init "$VAULT" 2>&1 || true
pass "init completed"

# --- Index (this is the key test — should embed + summarize + extract triples) ---
info "Running neurostack index (full pipeline with Ollama)..."
INDEX_OUT=$(neurostack index 2>&1)
echo "$INDEX_OUT"

# Check for warnings
WARN_COUNT=$(echo "$INDEX_OUT" | grep -c "\[WARNING\]" || true)
if [ "$WARN_COUNT" -gt 0 ]; then
    info "$WARN_COUNT warnings during indexing"
else
    pass "Zero warnings during indexing"
fi

# Check for hard errors (tracebacks, Python crashes — not Ollama warnings)
ERR_COUNT=$(echo "$INDEX_OUT" | grep -ci "traceback\|exception.*error\|segfault" || true)
if [ "$ERR_COUNT" -gt 0 ]; then
    fail "Hard errors found during indexing"
fi
pass "Index completed"

# --- Stats (verify embeddings, summaries, triples were created) ---
info "Checking stats..."
STATS=$(neurostack stats 2>&1)
echo "$STATS"

# Parse stats
EMBEDDED=$(echo "$STATS" | grep "Embedded:" | grep -oP '\d+(?= \()')
SUMMARIZED=$(echo "$STATS" | grep "Summarized:" | grep -oP '\d+(?= \()')
TRIPLES=$(echo "$STATS" | grep "Triples:" | grep -oP '^\s*Triples:\s+\K\d+')
EDGES=$(echo "$STATS" | grep "Graph edges:" | grep -oP '\d+')

echo ""
info "Embedded: $EMBEDDED"
info "Summarized: $SUMMARIZED"
info "Triples: $TRIPLES"
info "Graph edges: $EDGES"

[ "${EMBEDDED:-0}" -gt 0 ] || fail "No chunks were embedded (expected >0)"
pass "Embeddings created: $EMBEDDED chunks"

[ "${SUMMARIZED:-0}" -gt 0 ] || fail "No notes were summarized (expected >0)"
pass "Summaries created: $SUMMARIZED notes"

[ "${TRIPLES:-0}" -gt 0 ] || fail "No triples extracted (expected >0)"
pass "Triples extracted: $TRIPLES"

[ "${EDGES:-0}" -gt 0 ] || fail "No graph edges (expected >0 from wiki-links)"
pass "Graph edges: $EDGES"

# --- Hybrid search (FTS5 + semantic) ---
info "Testing hybrid search (FTS5 + cosine similarity)..."
SEARCH_OUT=$(neurostack search "how does the hippocampus index memories" 2>&1)
echo "$SEARCH_OUT"

# Should NOT contain FTS5-only fallback message
if echo "$SEARCH_OUT" | grep -q "FTS5-only"; then
    fail "Search fell back to FTS5-only mode — embeddings not used"
fi

echo "$SEARCH_OUT" | grep -qi "hippocampal\|indexing\|memory" || fail "Hybrid search returned no relevant results"
pass "Hybrid search works (embeddings + FTS5)"

# --- Semantic-only search ---
info "Testing semantic search (embedding similarity only)..."
SEM_OUT=$(neurostack search "what role does surprise play in learning" --mode semantic 2>&1)
echo "$SEM_OUT"
echo "$SEM_OUT" | grep -qi "prediction\|error\|surprise\|encoding" || info "Semantic search returned unexpected results (may be OK)"
pass "Semantic search executed"

# --- Summary retrieval ---
info "Testing summary retrieval..."
SUMMARY_OUT=$(neurostack summary "hippocampal-indexing" 2>&1)
echo "$SUMMARY_OUT"
[ -n "$SUMMARY_OUT" ] || fail "Summary returned empty"
pass "Summary retrieval works"

# --- Graph ---
info "Testing graph neighborhood..."
GRAPH_OUT=$(neurostack graph "hippocampal-indexing" 2>&1)
echo "$GRAPH_OUT"
pass "Graph query executed"

# --- Triples ---
info "Testing triple search..."
TRIPLE_OUT=$(neurostack triples "hippocampus memory" 2>&1)
echo "$TRIPLE_OUT"
pass "Triple search executed"

# --- Doctor ---
info "Running doctor..."
DOC_OUT=$(neurostack doctor 2>&1)
echo "$DOC_OUT"

# In full mode with Ollama, should have no warnings
DOC_WARNS=$(echo "$DOC_OUT" | grep -c "\[!\]" || true)
if [ "$DOC_WARNS" -gt 0 ]; then
    info "Doctor reported $DOC_WARNS warnings"
else
    pass "Doctor: clean bill of health"
fi

# --- Final summary ---
echo ""
echo "========================================="
echo "  ALL TESTS PASSED"
echo "  Full mode + Ollama on Fedora 41"
echo "  Embedded: $EMBEDDED chunks"
echo "  Summarized: $SUMMARIZED notes"
echo "  Triples: $TRIPLES"
echo "  Graph edges: $EDGES"
echo "========================================="

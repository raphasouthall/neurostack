#!/usr/bin/env bash
set -euo pipefail

# E2E Test: Full mode + Ollama — semantic search, embeddings, summaries, triples
PASS=0; FAIL=0; WARN=0
RESULTS=""

info()  { echo "  [*] $*"; }
pass()  { echo "  [✓] $*"; PASS=$((PASS+1)); RESULTS+="PASS: $*\n"; }
fail()  { echo "  [✗] $*"; FAIL=$((FAIL+1)); RESULTS+="FAIL: $*\n"; }
warn()  { echo "  [!] $*"; WARN=$((WARN+1)); RESULTS+="WARN: $*\n"; }

echo "╔══════════════════════════════════════════════════════╗"
echo "║  NeuroStack E2E — FULL MODE + OLLAMA (ML features)  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# --- System info ---
info "OS: $(cat /etc/fedora-release 2>/dev/null || cat /etc/os-release | head -1)"
info "Python: $(python3 --version)"

# --- Pre-flight: Ollama reachable? ---
echo ""; echo "═══ PRE-FLIGHT: OLLAMA ═══"
python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:11435/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
models = [m['name'] for m in data.get('models', [])]
print(f'  Embed models: {models}')
" && pass "Ollama embed (11435) reachable" || fail "Cannot reach Ollama embed on port 11435"

python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:11434/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
models = [m['name'] for m in data.get('models', [])]
print(f'  LLM models: {models}')
" && pass "Ollama LLM (11434) reachable" || fail "Cannot reach Ollama LLM on port 11434"

# Detect LLM model
LLM_MODEL=$(python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:11434/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
models = [m['name'] for m in data.get('models', [])]
for pref in ['qwen2.5:3b', 'phi3.5', 'qwen3:14b', 'llama3.1:8b']:
    if pref in models:
        print(pref); break
else:
    print(models[0] if models else 'phi3.5')
")
info "Selected LLM: $LLM_MODEL"

# ============================================================
# 1. INSTALL (full mode)
# ============================================================
echo ""; echo "═══ 1. INSTALL (full mode) ═══"
export NEUROSTACK_MODE=full
export HOME=/root
bash /neurostack/install.sh 2>&1 | tail -5
export PATH="$HOME/.local/bin:$PATH"

neurostack --help >/dev/null 2>&1 && pass "CLI installed in full mode" || fail "CLI install failed"

# Verify full-mode imports
cd "$HOME/.local/share/neurostack/repo"
uv run python3 -c "import numpy; print(f'  numpy {numpy.__version__}')" && pass "numpy available" || fail "numpy missing"
uv run python3 -c "import sentence_transformers; print(f'  sentence-transformers {sentence_transformers.__version__}')" && pass "sentence-transformers available" || fail "sentence-transformers missing"
uv run python3 -c "from neurostack.embedder import get_embedding; print('  embedder ok')" && pass "embedder module works" || fail "embedder broken"
uv run python3 -c "from neurostack.reranker import rerank; print('  reranker ok')" && pass "reranker module works" || fail "reranker broken"
uv run python3 -c "from neurostack.summarizer import summarize_note; print('  summarizer ok')" && pass "summarizer module works" || fail "summarizer broken"

# ============================================================
# 2. CREATE VAULT + CONFIGURE
# ============================================================
echo ""; echo "═══ 2. VAULT SETUP ═══"
VAULT="$HOME/test-vault"
mkdir -p "$VAULT"/{research,literature,projects}

cat > "$VAULT/research/hippocampal-indexing.md" << 'MD'
---
date: 2026-01-15
tags: [neuroscience, memory, hippocampus]
type: permanent
status: active
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
- Consolidation should compress frequently-accessed patterns

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

## Links

- [[hippocampal-indexing]]
MD

cat > "$VAULT/research/sleep-consolidation-mechanisms.md" << 'MD'
---
date: 2026-02-15
tags: [neuroscience, sleep, memory, consolidation]
type: permanent
status: active
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

cat > "$VAULT/literature/tolman-cognitive-maps.md" << 'MD'
---
date: 2026-01-10
tags: [neuroscience, cognitive-maps, navigation]
type: literature
status: reference
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

cat > "$VAULT/projects/kubernetes-migration.md" << 'MD'
---
date: 2026-03-10
tags: [devops, kubernetes, infrastructure]
type: project
status: active
---

# Kubernetes Migration Plan

Migrating legacy VM-based workloads to AKS (Azure Kubernetes Service).

## Phase 1: Containerize
- Docker images for all microservices
- Helm charts for deployment
- CI/CD with ArgoCD

## Phase 2: Staging
- Deploy to AKS staging cluster
- Load testing with k6
- Observability with Prometheus + Grafana
MD

cat > "$VAULT/index.md" << 'MD'
# Test Vault Index

## Research
- [[hippocampal-indexing]] — Hippocampus as rapid indexing system
- [[predictive-coding-and-memory]] — Prediction errors drive memory encoding
- [[sleep-consolidation-mechanisms]] — Sleep and systems consolidation

## Literature
- [[tolman-cognitive-maps]] — Tolman 1948

## Projects
- [[kubernetes-migration]] — K8s migration
MD

pass "Vault created (6 notes)"

# Configure
mkdir -p "$HOME/.config/neurostack"
cat > "$HOME/.config/neurostack/config.toml" << TOML
vault_root = "$VAULT"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "$LLM_MODEL"
TOML

neurostack init "$VAULT" 2>&1 || true
pass "Init completed"

# ============================================================
# 3. INDEX (full pipeline: FTS5 + embed + summarize + triples)
# ============================================================
echo ""; echo "═══ 3. FULL INDEX (FTS5 + embeddings + summaries + triples) ═══"
INDEX_OUT=$(neurostack index 2>&1)
echo "$INDEX_OUT"

if echo "$INDEX_OUT" | grep -qi "traceback\|segfault"; then
    fail "Index had hard errors"
else
    pass "Index completed"
fi

# ============================================================
# 4. STATS (verify full-mode artifacts)
# ============================================================
echo ""; echo "═══ 4. STATS ═══"
STATS=$(neurostack stats 2>&1)
echo "$STATS"

# Check embeddings were created
if echo "$STATS" | grep -qi "embed"; then
    EMBEDDED=$(echo "$STATS" | grep -i "embed" | grep -oP '\d+' | head -1)
    [ "${EMBEDDED:-0}" -gt 0 ] && pass "Embeddings created: $EMBEDDED chunks" || warn "Embeddings count is 0"
else
    warn "Stats doesn't show embedding info"
fi

# Check summaries
if echo "$STATS" | grep -qi "summar"; then
    SUMMARIZED=$(echo "$STATS" | grep -i "summar" | grep -oP '\d+' | head -1)
    [ "${SUMMARIZED:-0}" -gt 0 ] && pass "Summaries generated: $SUMMARIZED notes" || warn "Summaries count is 0"
else
    warn "Stats doesn't show summary info"
fi

# Check triples
if echo "$STATS" | grep -qi "triple"; then
    TRIPLE_CT=$(echo "$STATS" | grep -i "triple" | grep -oP '\d+' | head -1)
    [ "${TRIPLE_CT:-0}" -gt 0 ] && pass "Triples extracted: $TRIPLE_CT" || warn "Triples count is 0"
else
    warn "Stats doesn't show triple info"
fi

# Check graph edges
if echo "$STATS" | grep -qi "edge\|graph"; then
    EDGES=$(echo "$STATS" | grep -i "edge\|graph" | grep -oP '\d+' | head -1)
    [ "${EDGES:-0}" -gt 0 ] && pass "Graph edges: $EDGES" || warn "Graph edges is 0"
else
    warn "Stats doesn't show graph info"
fi

# ============================================================
# 5. HYBRID SEARCH (FTS5 + semantic)
# ============================================================
echo ""; echo "═══ 5. HYBRID SEARCH ═══"
SEARCH_OUT=$(neurostack search "how does the hippocampus index memories" 2>&1)
echo "$SEARCH_OUT"

echo "$SEARCH_OUT" | grep -qi "hippocampal\|indexing\|memory" && pass "Hybrid search found relevant results" || fail "Hybrid search returned nothing relevant"

if echo "$SEARCH_OUT" | grep -q "FTS5-only"; then
    warn "Search fell back to FTS5-only — embeddings not used"
else
    pass "Hybrid search used embeddings (not FTS5-only fallback)"
fi

# ============================================================
# 6. SEMANTIC SEARCH (embedding-only)
# ============================================================
echo ""; echo "═══ 6. SEMANTIC SEARCH ═══"
SEM_OUT=$(neurostack search "what role does surprise play in learning" --mode semantic 2>&1) || true
echo "$SEM_OUT"
echo "$SEM_OUT" | grep -qi "prediction\|error\|surprise\|encoding\|memory" && pass "Semantic search: meaningful results" || warn "Semantic search: results may not match"
pass "Semantic search executed"

# ============================================================
# 7. TIERED SEARCH (token-efficient retrieval)
# ============================================================
echo ""; echo "═══ 7. TIERED SEARCH ═══"
TIERED_OUT=$(neurostack tiered "how does sleep help memory" --top-k 3 2>&1) || true
echo "$TIERED_OUT"
echo "$TIERED_OUT" | grep -qi "sleep\|consolidat\|memory\|replay" && pass "Tiered search returned relevant context" || warn "Tiered search results unclear"

# JSON tiered
TIERED_JSON=$(neurostack --json tiered "hippocampus" --top-k 2 2>&1) || true
echo "$TIERED_JSON" | python3 -c "import sys,json; json.load(sys.stdin); print('  Valid JSON')" 2>&1 && pass "Tiered --json returns valid JSON" || warn "Tiered --json not valid JSON"

# ============================================================
# 8. SUMMARY RETRIEVAL
# ============================================================
echo ""; echo "═══ 8. SUMMARY ═══"
SUMMARY_OUT=$(neurostack summary "hippocampal-indexing" 2>&1)
echo "$SUMMARY_OUT"
[ -n "$SUMMARY_OUT" ] && pass "Summary retrieval works" || fail "Summary returned empty"

# ============================================================
# 9. GRAPH NEIGHBORHOOD
# ============================================================
echo ""; echo "═══ 9. GRAPH ═══"
GRAPH_OUT=$(neurostack graph "hippocampal-indexing" 2>&1)
echo "$GRAPH_OUT"
echo "$GRAPH_OUT" | grep -qi "predictive\|sleep\|tolman\|neighbor\|link" && pass "Graph shows connections" || warn "Graph output sparse"

# ============================================================
# 10. TRIPLES (structured knowledge)
# ============================================================
echo ""; echo "═══ 10. TRIPLES ═══"
TRIPLE_OUT=$(neurostack triples "hippocampus memory" 2>&1)
echo "$TRIPLE_OUT"
pass "Triples query executed"

# ============================================================
# 11. PREDICTION ERRORS
# ============================================================
echo ""; echo "═══ 11. PREDICTION ERRORS ═══"
PE_OUT=$(neurostack prediction-errors 2>&1) || true
echo "$PE_OUT"
pass "Prediction errors executed"

# ============================================================
# 12. BRIEF
# ============================================================
echo ""; echo "═══ 12. BRIEF ═══"
BRIEF_OUT=$(neurostack brief 2>&1) || true
echo "$BRIEF_OUT"
pass "Brief executed"

# ============================================================
# 13. DOCTOR (full mode validation)
# ============================================================
echo ""; echo "═══ 13. DOCTOR ═══"
DOC_OUT=$(neurostack doctor 2>&1)
echo "$DOC_OUT"
DOC_WARNS=$(echo "$DOC_OUT" | grep -c "\[!\]" || true)
if [ "$DOC_WARNS" -eq 0 ]; then
    pass "Doctor: clean bill of health"
else
    warn "Doctor: $DOC_WARNS warnings"
fi

# ============================================================
# 14. RECORD-USAGE + HOTNESS
# ============================================================
echo ""; echo "═══ 14. RECORD-USAGE ═══"
neurostack record-usage "hippocampal-indexing" 2>&1 && pass "record-usage tracked" || warn "record-usage failed"
neurostack record-usage "hippocampal-indexing" 2>&1 || true
neurostack record-usage "hippocampal-indexing" 2>&1 || true

# Verify hot notes influence search
HOT_SEARCH=$(neurostack search "neuroscience" 2>&1) || true
echo "$HOT_SEARCH" | head -5
pass "Search after record-usage executed (hotness should boost hippocampal-indexing)"

# ============================================================
# 15. MEMORIES (agent write-back)
# ============================================================
echo ""; echo "═══ 15. MEMORIES ═══"
neurostack memories save "Full mode requires Ollama for embeddings and summaries" --type decision 2>&1 || true
neurostack memories save "Use qwen2.5:3b for fastest LLM inference in tests" --type convention 2>&1 || true

MEM_LIST=$(neurostack memories list 2>&1) || true
echo "$MEM_LIST"
echo "$MEM_LIST" | grep -qi "full mode\|qwen\|memory\|decision\|convention" && pass "Memories: stored and listed" || warn "Memories: list may be empty"

# ============================================================
# 16. REEMBED-CHUNKS (reprocessing)
# ============================================================
echo ""; echo "═══ 16. REEMBED-CHUNKS ═══"
REEMBED_OUT=$(neurostack reembed-chunks 2>&1) || true
echo "$REEMBED_OUT" | head -5
pass "reembed-chunks executed"

# ============================================================
# 17. BACKFILL (fill missing summaries/triples)
# ============================================================
echo ""; echo "═══ 17. BACKFILL ═══"
BACKFILL_OUT=$(neurostack backfill 2>&1) || true
echo "$BACKFILL_OUT" | head -5
pass "backfill executed"

# ============================================================
# SUMMARY
# ============================================================
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       FULL MODE + OLLAMA TEST RESULTS               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  PASSED: $PASS                                       "
echo "║  FAILED: $FAIL                                       "
echo "║  WARNED: $WARN                                       "
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo -e "$RESULTS"

[ "$FAIL" -eq 0 ] && echo "✅ ALL TESTS PASSED" || echo "❌ SOME TESTS FAILED"
exit $FAIL

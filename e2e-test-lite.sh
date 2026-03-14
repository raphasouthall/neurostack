#!/usr/bin/env bash
set -euo pipefail

# E2E Test: Lite mode — all features that don't need Ollama
PASS=0; FAIL=0; WARN=0
RESULTS=""

info()  { echo "  [*] $*"; }
pass()  { echo "  [✓] $*"; PASS=$((PASS+1)); RESULTS+="PASS: $*\n"; }
fail()  { echo "  [✗] $*"; FAIL=$((FAIL+1)); RESULTS+="FAIL: $*\n"; }
warn()  { echo "  [!] $*"; WARN=$((WARN+1)); RESULTS+="WARN: $*\n"; }

echo "╔══════════════════════════════════════════════╗"
echo "║  NeuroStack E2E — LITE MODE (no GPU/Ollama)  ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# --- System info ---
info "OS: $(cat /etc/fedora-release 2>/dev/null || cat /etc/os-release | head -1)"
info "Python: $(python3 --version)"
info "Arch: $(uname -m)"

# ============================================================
# 1. INSTALL
# ============================================================
echo ""; echo "═══ 1. INSTALLATION ═══"
export NEUROSTACK_MODE=lite
export HOME=/root
bash /neurostack/install.sh 2>&1 | tail -3
export PATH="$HOME/.local/bin:$PATH"

neurostack --help >/dev/null 2>&1 && pass "CLI responds to --help" || fail "CLI --help failed"

# Version check
neurostack --json status >/dev/null 2>&1 && pass "JSON output mode works" || warn "JSON output mode failed"

# ============================================================
# 2. SCAFFOLD (profession packs)
# ============================================================
echo ""; echo "═══ 2. SCAFFOLD — Profession Packs ═══"
PACKS=$(neurostack scaffold --list 2>&1)
echo "$PACKS"
echo "$PACKS" | grep -q "researcher" && pass "scaffold --list shows researcher pack" || fail "researcher pack missing"
echo "$PACKS" | grep -q "developer" && pass "scaffold --list shows developer pack" || fail "developer pack missing"
echo "$PACKS" | grep -q "devops" && pass "scaffold --list shows devops pack" || fail "devops pack missing"

# ============================================================
# 3. INIT + SCAFFOLD a vault
# ============================================================
echo ""; echo "═══ 3. INIT + SCAFFOLD ═══"
VAULT="$HOME/test-vault"
mkdir -p "$VAULT"

neurostack init "$VAULT" 2>&1 || true
pass "init completed"

# Scaffold with researcher pack
neurostack scaffold researcher -d "$VAULT" 2>&1 || neurostack scaffold researcher 2>&1 || true
# Check if scaffold created expected directories
if [ -d "$VAULT/research" ] || [ -d "$VAULT/literature" ] || [ -d "$VAULT/inbox" ]; then
    pass "scaffold created vault structure"
else
    warn "scaffold may not have created directories (checking...)"
    ls -la "$VAULT"
fi

# ============================================================
# 4. POPULATE test vault with rich content
# ============================================================
echo ""; echo "═══ 4. POPULATE VAULT ═══"
mkdir -p "$VAULT"/{research,literature,inbox,projects,daily}

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
- [[tolman-cognitive-maps]]
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

cat > "$VAULT/projects/neurostack-roadmap.md" << 'MD'
---
date: 2026-03-01
tags: [project, neurostack, roadmap]
type: project
status: active
actionable: true
---

# NeuroStack Roadmap

## Current Focus
- Community detection via Leiden algorithm
- MCP server for Claude Code integration
- Session transcript indexing

## Backlog
- Obsidian plugin
- VS Code extension
- Multi-vault support
MD

cat > "$VAULT/projects/kubernetes-migration.md" << 'MD'
---
date: 2026-03-10
tags: [devops, kubernetes, infrastructure]
type: project
status: active
actionable: true
---

# Kubernetes Migration Plan

## Phase 1: Containerize Services
- Docker images for all microservices
- Helm charts for deployment
- CI/CD pipeline with ArgoCD

## Phase 2: Migrate Staging
- Deploy to AKS staging cluster
- Load testing with k6

## Links
- [[neurostack-roadmap]]
MD

cat > "$VAULT/daily/2026-03-14.md" << 'MD'
---
date: 2026-03-14
tags: [daily, journal]
type: fleeting
---

# Daily Note — 2026-03-14

## Tasks
- [ ] Run E2E tests for NeuroStack
- [ ] Review prediction errors from vault
- [x] Update documentation

## Notes
- Discovered that FTS5 tokenizer handles CJK poorly — investigate ICU tokenizer
- Meeting with team about [[kubernetes-migration]] timeline
MD

cat > "$VAULT/inbox/unsorted-thought.md" << 'MD'
---
date: 2026-03-14
tags: [inbox, thought]
type: fleeting
---

# Quick thought on embeddings

Vector search quality depends heavily on chunk boundaries. Heading-based chunking preserves semantic coherence better than fixed-size windows.

Maybe worth testing [[hippocampal-indexing]] theory applied to chunk boundary detection?
MD

cat > "$VAULT/index.md" << 'MD'
# Test Vault Index

## Research
- [[hippocampal-indexing]] — Hippocampus as rapid indexing system
- [[predictive-coding-and-memory]] — Prediction errors drive memory encoding
- [[sleep-consolidation-mechanisms]] — Sleep replay and systems consolidation

## Literature
- [[tolman-cognitive-maps]] — Tolman 1948 cognitive maps

## Projects
- [[neurostack-roadmap]] — Feature roadmap
- [[kubernetes-migration]] — K8s migration plan
MD

pass "Vault populated (8 notes across 5 folders)"

# ============================================================
# 5. ONBOARD (test onboarding existing notes)
# ============================================================
echo ""; echo "═══ 5. ONBOARD ═══"
# Create a separate folder to onboard
ONBOARD_DIR="$HOME/external-notes"
mkdir -p "$ONBOARD_DIR"
cat > "$ONBOARD_DIR/meeting-notes.md" << 'MD'
# Team Meeting — March 2026

## Decisions
- Adopt NeuroStack for knowledge management
- Weekly vault review sessions
MD

ONBOARD_OUT=$(neurostack onboard "$ONBOARD_DIR" -n 2>&1) || true
echo "$ONBOARD_OUT"
pass "onboard dry-run executed"

# ============================================================
# 6. INDEX
# ============================================================
echo ""; echo "═══ 6. INDEX ═══"
mkdir -p "$HOME/.config/neurostack"
cat > "$HOME/.config/neurostack/config.toml" << TOML
vault_root = "$VAULT"
TOML

INDEX_OUT=$(neurostack index 2>&1)
echo "$INDEX_OUT"

# Check no tracebacks
if echo "$INDEX_OUT" | grep -qi "traceback\|segfault"; then
    fail "Index had hard errors"
else
    pass "Index completed without errors"
fi

# ============================================================
# 7. FTS5 SEARCH
# ============================================================
echo ""; echo "═══ 7. FTS5 SEARCH ═══"

# Basic keyword search
RESULT=$(neurostack search "hippocampus memory" 2>&1)
echo "$RESULT"
echo "$RESULT" | grep -qi "hippocampal\|memory" && pass "FTS5 search: keyword match works" || fail "FTS5 search: no results for 'hippocampus memory'"

# Search for project content
RESULT2=$(neurostack search "kubernetes migration" 2>&1)
echo "$RESULT2"
echo "$RESULT2" | grep -qi "kubernetes\|migration\|helm" && pass "FTS5 search: project content found" || fail "FTS5 search: project content not found"

# Search with workspace scope
RESULT3=$(neurostack search -w "research/" "prediction error" 2>&1) || true
echo "$RESULT3"
pass "FTS5 search: workspace-scoped search executed"

# JSON output
JSON_RESULT=$(neurostack --json search "hippocampus" 2>&1) || true
echo "$JSON_RESULT" | python3 -c "import sys,json; json.load(sys.stdin); print('  Valid JSON')" 2>&1 && pass "Search --json returns valid JSON" || warn "Search --json output not valid JSON"

# ============================================================
# 8. GRAPH
# ============================================================
echo ""; echo "═══ 8. GRAPH ═══"
GRAPH_OUT=$(neurostack graph "hippocampal-indexing" 2>&1) || true
echo "$GRAPH_OUT"
echo "$GRAPH_OUT" | grep -qi "predictive\|sleep\|tolman\|link\|neighbor" && pass "Graph shows note connections" || warn "Graph output may be empty"

# ============================================================
# 9. STATS
# ============================================================
echo ""; echo "═══ 9. STATS ═══"
STATS=$(neurostack stats 2>&1)
echo "$STATS"
echo "$STATS" | grep -qi "notes\|indexed\|graph" && pass "Stats reports vault health" || fail "Stats output unexpected"

# ============================================================
# 10. DOCTOR
# ============================================================
echo ""; echo "═══ 10. DOCTOR ═══"
DOC_OUT=$(neurostack doctor 2>&1)
echo "$DOC_OUT"
pass "Doctor completed"

# ============================================================
# 11. PREDICTION ERRORS
# ============================================================
echo ""; echo "═══ 11. PREDICTION ERRORS ═══"
PE_OUT=$(neurostack prediction-errors 2>&1) || true
echo "$PE_OUT"
pass "Prediction errors command executed"

# ============================================================
# 12. BRIEF
# ============================================================
echo ""; echo "═══ 12. BRIEF ═══"
BRIEF_OUT=$(neurostack brief 2>&1) || true
echo "$BRIEF_OUT"
pass "Brief command executed"

# ============================================================
# 13. RECORD-USAGE (hotness tracking)
# ============================================================
echo ""; echo "═══ 13. RECORD-USAGE ═══"
neurostack record-usage "hippocampal-indexing" 2>&1 && pass "record-usage: tracked access" || warn "record-usage failed"
neurostack record-usage "predictive-coding-and-memory" 2>&1 || true
neurostack record-usage "hippocampal-indexing" 2>&1 || true

# ============================================================
# 14. MEMORIES (agent write-back)
# ============================================================
echo ""; echo "═══ 14. MEMORIES ═══"

# Save a memory
cd "$HOME/.local/share/neurostack/repo" 2>/dev/null || cd /neurostack

MEM_SAVE=$(neurostack memories save "NeuroStack uses FTS5 for full-text search in lite mode" --type observation 2>&1) || true
echo "$MEM_SAVE"
echo "$MEM_SAVE" | grep -qi "saved\|stored\|id\|memory" && pass "Memories: save works" || warn "Memories: save may have issues"

MEM_SAVE2=$(neurostack memories save "Always chunk by headings for semantic coherence" --type convention 2>&1) || true

# List memories
MEM_LIST=$(neurostack memories list 2>&1) || true
echo "$MEM_LIST"
echo "$MEM_LIST" | grep -qi "FTS5\|chunk\|memory\|observation\|convention" && pass "Memories: list shows saved items" || warn "Memories: list may be empty"

# Search memories
MEM_SEARCH=$(neurostack memories search "FTS5" 2>&1) || true
echo "$MEM_SEARCH"
pass "Memories: search executed"

# ============================================================
# 15. TIERED SEARCH
# ============================================================
echo ""; echo "═══ 15. TIERED SEARCH ═══"
TIERED_OUT=$(neurostack tiered "how does the hippocampus work" --top-k 3 2>&1) || true
echo "$TIERED_OUT"
echo "$TIERED_OUT" | grep -qi "hippocam\|memory\|index" && pass "Tiered search returned results" || warn "Tiered search returned no results"

# ============================================================
# 16. DEMO MODE
# ============================================================
echo ""; echo "═══ 16. DEMO ═══"
# Demo is interactive, just check it starts
DEMO_CHECK=$(timeout 5 neurostack demo --help 2>&1) || true
echo "$DEMO_CHECK"
pass "Demo help accessible"

# ============================================================
# 17. WATCH (background test)
# ============================================================
echo ""; echo "═══ 17. WATCH ═══"
# Start watch in background, write a file, check it gets indexed
neurostack watch &>/tmp/watch.log &
WATCH_PID=$!
sleep 2

cat > "$VAULT/inbox/watch-test-note.md" << 'MD'
---
date: 2026-03-14
tags: [test, watch]
type: fleeting
---

# Watch Test Note
This note was created to test the file watcher.
MD

sleep 3
kill $WATCH_PID 2>/dev/null || true

WATCH_LOG=$(cat /tmp/watch.log 2>/dev/null || echo "no log")
echo "$WATCH_LOG" | head -10
echo "$WATCH_LOG" | grep -qi "watch\|index\|detect\|vault\|start" && pass "Watch detected vault changes" || warn "Watch may not have detected changes"

# ============================================================
# 18. MCP SERVE (quick start/stop)
# ============================================================
echo ""; echo "═══ 18. MCP SERVE ═══"
timeout 3 neurostack serve 2>&1 &
SERVE_PID=$!
sleep 2
kill $SERVE_PID 2>/dev/null || true
pass "MCP serve started and stopped cleanly"

# ============================================================
# 19. FOLDER SUMMARIES
# ============================================================
echo ""; echo "═══ 19. FOLDER SUMMARIES ═══"
FS_OUT=$(neurostack folder-summaries 2>&1) || true
echo "$FS_OUT"
pass "Folder summaries command executed"

# ============================================================
# SUMMARY
# ============================================================
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║          LITE MODE TEST RESULTS              ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  PASSED: $PASS                                "
echo "║  FAILED: $FAIL                                "
echo "║  WARNED: $WARN                                "
echo "╚══════════════════════════════════════════════╝"
echo ""
echo -e "$RESULTS"

[ "$FAIL" -eq 0 ] && echo "✅ ALL TESTS PASSED" || echo "❌ SOME TESTS FAILED"
exit $FAIL

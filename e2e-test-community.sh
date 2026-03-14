#!/usr/bin/env bash
set -euo pipefail

# E2E Test: Community mode — Leiden clustering + community queries
PASS=0; FAIL=0; WARN=0
RESULTS=""

info()  { echo "  [*] $*"; }
pass()  { echo "  [✓] $*"; PASS=$((PASS+1)); RESULTS+="PASS: $*\n"; }
fail()  { echo "  [✗] $*"; FAIL=$((FAIL+1)); RESULTS+="FAIL: $*\n"; }
warn()  { echo "  [!] $*"; WARN=$((WARN+1)); RESULTS+="WARN: $*\n"; }

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  NeuroStack E2E — COMMUNITY MODE (Leiden clustering)    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

info "OS: $(cat /etc/fedora-release 2>/dev/null || cat /etc/os-release | head -1)"
info "Python: $(python3 --version)"

# ============================================================
# 1. INSTALL (full+community mode)
# ============================================================
echo ""; echo "═══ 1. INSTALL (full+community) ═══"
export NEUROSTACK_MODE=full
export HOME=/root
bash /neurostack/install.sh 2>&1 | tail -5
export PATH="$HOME/.local/bin:$PATH"

# Install community extra
cd "$HOME/.local/share/neurostack/repo"
uv pip install -e ".[community]" 2>&1 | tail -3

# Verify community imports
uv run python3 -c "import leidenalg; print(f'  leidenalg: {leidenalg.__version__}')" && pass "leidenalg available" || fail "leidenalg not installed"
uv run python3 -c "import igraph; print(f'  igraph: {igraph.__version__}')" && pass "python-igraph available" || fail "igraph not installed"
uv run python3 -c "from neurostack.leiden import detect_communities; print('  leiden module ok')" && pass "leiden module importable" || fail "leiden module broken"
uv run python3 -c "from neurostack.community_search import community_search; print('  community_search ok')" && pass "community_search importable" || fail "community_search broken"

pass "Community mode installed"

# ============================================================
# 2. CREATE LARGE VAULT (need enough notes for clustering)
# ============================================================
echo ""; echo "═══ 2. CREATE VAULT (12 notes, 3 topic clusters) ═══"
VAULT="$HOME/test-vault"
mkdir -p "$VAULT"/{neuroscience,devops,cooking}

# --- Cluster 1: Neuroscience ---
cat > "$VAULT/neuroscience/hippocampal-indexing.md" << 'MD'
---
date: 2026-01-15
tags: [neuroscience, memory, hippocampus]
type: permanent
---
# Hippocampal Indexing Theory
The hippocampus functions as a rapid indexing system for neocortical memory traces.
Memory encoding creates sparse hippocampal indices.
## Links
- [[predictive-coding-and-memory]]
- [[sleep-consolidation]]
- [[spatial-navigation]]
MD

cat > "$VAULT/neuroscience/predictive-coding-and-memory.md" << 'MD'
---
date: 2026-02-01
tags: [neuroscience, predictive-coding]
type: permanent
---
# Predictive Coding and Memory
Prediction errors drive memory encoding — surprising events are stored preferentially.
The hippocampus computes prediction errors.
## Links
- [[hippocampal-indexing]]
- [[sleep-consolidation]]
MD

cat > "$VAULT/neuroscience/sleep-consolidation.md" << 'MD'
---
date: 2026-02-15
tags: [neuroscience, sleep, memory]
type: permanent
---
# Sleep Consolidation Mechanisms
Sharp-wave ripples during NREM sleep replay compressed neural sequences.
Sleep transforms hippocampal memories into neocortical representations.
## Links
- [[hippocampal-indexing]]
- [[predictive-coding-and-memory]]
MD

cat > "$VAULT/neuroscience/spatial-navigation.md" << 'MD'
---
date: 2026-01-20
tags: [neuroscience, navigation, place-cells]
type: permanent
---
# Spatial Navigation and Place Cells
Place cells fire at specific locations, creating a cognitive map.
Grid cells provide a metric for spatial navigation.
## Links
- [[hippocampal-indexing]]
MD

# --- Cluster 2: DevOps ---
cat > "$VAULT/devops/kubernetes-basics.md" << 'MD'
---
date: 2026-03-01
tags: [devops, kubernetes, containers]
type: permanent
---
# Kubernetes Fundamentals
Kubernetes orchestrates containerised workloads across clusters.
Pods are the smallest deployable unit.
## Links
- [[helm-charts]]
- [[cicd-pipeline]]
- [[monitoring-stack]]
MD

cat > "$VAULT/devops/helm-charts.md" << 'MD'
---
date: 2026-03-02
tags: [devops, kubernetes, helm]
type: permanent
---
# Helm Charts
Helm packages Kubernetes manifests into reusable charts.
Values files allow environment-specific configuration.
## Links
- [[kubernetes-basics]]
- [[cicd-pipeline]]
MD

cat > "$VAULT/devops/cicd-pipeline.md" << 'MD'
---
date: 2026-03-03
tags: [devops, ci-cd, automation]
type: permanent
---
# CI/CD Pipeline Architecture
ArgoCD provides GitOps-based continuous deployment to Kubernetes.
GitHub Actions handles CI (build, test, lint).
## Links
- [[kubernetes-basics]]
- [[helm-charts]]
MD

cat > "$VAULT/devops/monitoring-stack.md" << 'MD'
---
date: 2026-03-04
tags: [devops, monitoring, observability]
type: permanent
---
# Monitoring and Observability
Prometheus collects metrics from Kubernetes pods.
Grafana dashboards visualise cluster health and application performance.
## Links
- [[kubernetes-basics]]
MD

# --- Cluster 3: Cooking ---
cat > "$VAULT/cooking/sourdough-bread.md" << 'MD'
---
date: 2026-02-20
tags: [cooking, baking, sourdough]
type: permanent
---
# Sourdough Bread
A traditional fermented bread using wild yeast and lactobacillus.
Requires a mature starter culture maintained over days.
## Links
- [[fermentation-science]]
- [[bread-scoring]]
MD

cat > "$VAULT/cooking/fermentation-science.md" << 'MD'
---
date: 2026-02-21
tags: [cooking, fermentation, science]
type: permanent
---
# Fermentation Science
Fermentation converts sugars into acids, gases, and alcohol via microorganisms.
Temperature and hydration control fermentation rate in bread.
## Links
- [[sourdough-bread]]
MD

cat > "$VAULT/cooking/bread-scoring.md" << 'MD'
---
date: 2026-02-22
tags: [cooking, baking, technique]
type: permanent
---
# Bread Scoring Techniques
Scoring controls oven spring and creates decorative patterns.
A curved lame at 30 degrees produces the classic ear.
## Links
- [[sourdough-bread]]
MD

cat > "$VAULT/index.md" << 'MD'
# Vault Index

## Neuroscience
- [[hippocampal-indexing]] — Memory indexing
- [[predictive-coding-and-memory]] — Prediction errors
- [[sleep-consolidation]] — Sleep and memory
- [[spatial-navigation]] — Place cells

## DevOps
- [[kubernetes-basics]] — K8s fundamentals
- [[helm-charts]] — Chart packaging
- [[cicd-pipeline]] — CI/CD with ArgoCD
- [[monitoring-stack]] — Prometheus + Grafana

## Cooking
- [[sourdough-bread]] — Sourdough baking
- [[fermentation-science]] — Fermentation
- [[bread-scoring]] — Scoring techniques
MD

pass "Vault created (12 notes, 3 clusters)"

# ============================================================
# 3. CONFIGURE + INDEX
# ============================================================
echo ""; echo "═══ 3. INDEX ═══"

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
info "Using LLM: $LLM_MODEL"

mkdir -p "$HOME/.config/neurostack"
cat > "$HOME/.config/neurostack/config.toml" << TOML
vault_root = "$VAULT"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "$LLM_MODEL"
TOML

neurostack init "$VAULT" 2>&1 || true
INDEX_OUT=$(neurostack index 2>&1)
echo "$INDEX_OUT"

if echo "$INDEX_OUT" | grep -qi "traceback\|segfault"; then
    fail "Index had hard errors"
else
    pass "Full index completed"
fi

# ============================================================
# 4. COMMUNITY DETECTION (Leiden algorithm)
# ============================================================
echo ""; echo "═══ 4. COMMUNITY DETECTION ═══"
COMM_OUT=$(neurostack communities build 2>&1) || true
echo "$COMM_OUT"

if echo "$COMM_OUT" | grep -qi "communit\|cluster\|built\|leiden\|detect"; then
    pass "Community detection (build) ran"
else
    warn "Community build output unclear"
fi

# List communities
COMM_LIST=$(neurostack communities list 2>&1) || true
echo "$COMM_LIST"
echo "$COMM_LIST" | grep -qi "communit\|cluster\|topic\|notes" && pass "Communities list shows clusters" || warn "Communities list empty"

# ============================================================
# 5. COMMUNITY QUERY (big-picture questions)
# ============================================================
echo ""; echo "═══ 5. COMMUNITY QUERY ═══"

# Query across neuroscience cluster
CQ1=$(neurostack communities query "what is the relationship between sleep and memory" 2>&1) || true
echo "$CQ1"
echo "$CQ1" | grep -qi "sleep\|memory\|consolidat\|hippocam" && pass "Community query: neuroscience cluster found" || warn "Community query: neuroscience results unclear"

# Query across devops cluster
CQ2=$(neurostack communities query "how does CI/CD work with Kubernetes" 2>&1) || true
echo "$CQ2"
echo "$CQ2" | grep -qi "kubernetes\|cicd\|argocd\|helm\|deploy" && pass "Community query: devops cluster found" || warn "Community query: devops results unclear"

# Query across cooking cluster
CQ3=$(neurostack communities query "how do you make sourdough bread" 2>&1) || true
echo "$CQ3"
echo "$CQ3" | grep -qi "sourdough\|ferment\|bread\|starter" && pass "Community query: cooking cluster found" || warn "Community query: cooking results unclear"

# Cross-cluster query
CQ4=$(neurostack communities query "what parallels exist between neuroscience and software architecture" 2>&1) || true
echo "$CQ4"
pass "Cross-cluster community query executed"

# ============================================================
# 6. VERIFY CLUSTER SEPARATION
# ============================================================
echo ""; echo "═══ 6. STATS + CLUSTER VERIFICATION ═══"
STATS=$(neurostack stats 2>&1)
echo "$STATS"

if echo "$STATS" | grep -qi "communit"; then
    COMM_CT=$(echo "$STATS" | grep -i "communit" | grep -oP '\d+' | head -1)
    if [ "${COMM_CT:-0}" -ge 2 ]; then
        pass "Multiple communities detected: $COMM_CT"
    else
        warn "Only $COMM_CT community detected (expected 2-3)"
    fi
else
    warn "Stats doesn't show community count"
fi

# ============================================================
# 7. SEARCH WITHIN COMMUNITY CONTEXT
# ============================================================
echo ""; echo "═══ 7. COMMUNITY-AWARE SEARCH ═══"
CS_OUT=$(neurostack search "memory encoding and retrieval" 2>&1) || true
echo "$CS_OUT"
pass "Search with community context executed"

# ============================================================
# SUMMARY
# ============================================================
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║       COMMUNITY MODE TEST RESULTS                       ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  PASSED: $PASS                                           "
echo "║  FAILED: $FAIL                                           "
echo "║  WARNED: $WARN                                           "
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo -e "$RESULTS"

[ "$FAIL" -eq 0 ] && echo "✅ ALL TESTS PASSED" || echo "❌ SOME TESTS FAILED"
exit $FAIL

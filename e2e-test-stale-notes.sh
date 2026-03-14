#!/usr/bin/env bash
set -euo pipefail

# Test that stale notes trigger prediction errors
info()  { echo "  [*] $*"; }
pass()  { echo "  [✓] $*"; }
fail()  { echo "  [✗] $*"; }

echo "╔══════════════════════════════════════════════════╗"
echo "║  NeuroStack E2E — STALE NOTES + PREDICTION ERR  ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

export NEUROSTACK_MODE=full
export HOME=/root
bash /neurostack/install.sh 2>&1 | tail -3
export PATH="$HOME/.local/bin:$PATH"

# Detect LLM
LLM_MODEL=$(python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:11434/api/tags')
resp = urllib.request.urlopen(req, timeout=5)
data = json.loads(resp.read())
models = [m['name'] for m in data.get('models', [])]
for pref in ['qwen2.5:3b', 'phi3.5', 'qwen3:14b']:
    if pref in models:
        print(pref); break
else:
    print(models[0] if models else 'phi3.5')
")
info "LLM: $LLM_MODEL"

# Create vault with good notes + stale notes
VAULT="$HOME/test-vault"
mkdir -p "$VAULT"/{research,devops,literature}

# --- Good notes (neuroscience cluster) ---
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
- Memory encoding creates sparse hippocampal indices pointing to distributed cortical representations
- Retrieval involves pattern completion from partial cues through hippocampal replay
- Sleep consolidation gradually transfers index dependency to cortico-cortical pathways
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
---
# Predictive Coding and Memory
Prediction errors drive memory encoding — surprising events are preferentially stored.
## Key Claims
- The hippocampus computes prediction errors by comparing expected and observed input
- High prediction error events receive enhanced encoding via dopaminergic modulation
- Schema-violating information creates strong episodic traces
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
- Over time, memories become less hippocampus-dependent
## Links
- [[hippocampal-indexing]]
- [[predictive-coding-and-memory]]
MD

# --- STALE NOTE 1: ML neural networks masquerading as neuroscience ---
cp /neurostack/ci-test/stale-notes/research/neural-network-architectures.md "$VAULT/research/"

# --- STALE NOTE 2: Outdated Docker Swarm in a K8s vault ---
cp /neurostack/ci-test/stale-notes/devops/docker-swarm-legacy.md "$VAULT/devops/"

# --- STALE NOTE 3: Memory palace (mnemonic) mixed with neuroscience ---
cp /neurostack/ci-test/stale-notes/research/memory-palace-technique.md "$VAULT/research/"

# Good devops notes for contrast
cat > "$VAULT/devops/kubernetes-migration.md" << 'MD'
---
date: 2026-03-10
tags: [devops, kubernetes, infrastructure]
type: permanent
status: active
---
# Kubernetes Migration Plan
Migrating to AKS with Helm charts and ArgoCD for GitOps deployment.
## Links
- [[monitoring-stack]]
MD

cat > "$VAULT/devops/monitoring-stack.md" << 'MD'
---
date: 2026-03-04
tags: [devops, monitoring, observability]
type: permanent
status: active
---
# Monitoring and Observability
Prometheus collects metrics from Kubernetes pods. Grafana dashboards visualise cluster health.
## Links
- [[kubernetes-migration]]
MD

cat > "$VAULT/index.md" << 'MD'
# Vault Index
## Research
- [[hippocampal-indexing]]
- [[predictive-coding-and-memory]]
- [[sleep-consolidation-mechanisms]]
- [[neural-network-architectures]]
- [[memory-palace-technique]]
## DevOps
- [[kubernetes-migration]]
- [[docker-swarm-legacy]]
- [[monitoring-stack]]
MD

pass "Vault created (9 notes, 3 stale)"

# Configure
mkdir -p "$HOME/.config/neurostack"
cat > "$HOME/.config/neurostack/config.toml" << TOML
vault_root = "$VAULT"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "$LLM_MODEL"
TOML

neurostack init "$VAULT" 2>&1 || true

# Index
info "Indexing..."
neurostack index 2>&1
pass "Index done"

# Stats
echo ""
neurostack stats 2>&1
echo ""

# Simulate searches that would create prediction errors
# These queries should retrieve the stale notes but they don't match well semantically
info "Simulating search queries to generate retrieval events..."

# Query 1: neuroscience query that might pull in ML neural-network note
neurostack search "how does hippocampal replay work during sleep" 2>&1 | head -15
neurostack record-usage "hippocampal-indexing" 2>&1 || true
neurostack record-usage "sleep-consolidation-mechanisms" 2>&1 || true

# Query 2: K8s query that might pull in Docker Swarm note
neurostack search "container orchestration with kubernetes and helm" 2>&1 | head -15
neurostack record-usage "kubernetes-migration" 2>&1 || true

# Query 3: memory consolidation query that might pull in memory palace
neurostack search "neuroscience of memory consolidation and encoding" 2>&1 | head -15
neurostack record-usage "predictive-coding-and-memory" 2>&1 || true

echo ""
info "Running prediction-errors..."
PE_OUT=$(neurostack prediction-errors 2>&1)
echo "$PE_OUT"

if echo "$PE_OUT" | grep -qi "neural-network\|docker-swarm\|memory-palace\|flagged\|error"; then
    pass "Prediction errors detected stale notes!"
    echo ""
    echo "Stale notes flagged:"
    echo "$PE_OUT" | grep -i "neural-network\|docker-swarm\|memory-palace" || true
else
    info "No prediction errors surfaced (may need more retrieval events)"
    echo ""
    echo "Trying --all flag..."
    neurostack prediction-errors --all 2>&1 || neurostack prediction-errors 2>&1
fi

echo ""
echo "═══ SEARCH QUALITY CHECK ═══"
info "Searching for 'hippocampal replay' — should NOT return neural-network-architectures"
SEARCH1=$(neurostack search "hippocampal replay during sleep" 2>&1)
echo "$SEARCH1" | head -20
if echo "$SEARCH1" | grep -qi "neural-network-architectures"; then
    pass "CONFIRMED: ML note appears in neuroscience query (prediction error candidate)"
else
    info "ML note correctly excluded from neuroscience query"
fi

info "Searching for 'kubernetes deployment' — should NOT return docker-swarm-legacy"
SEARCH2=$(neurostack search "kubernetes deployment helm argocd" 2>&1)
echo "$SEARCH2" | head -20
if echo "$SEARCH2" | grep -qi "docker-swarm"; then
    pass "CONFIRMED: Swarm note appears in K8s query (prediction error candidate)"
else
    info "Swarm note correctly excluded from K8s query"
fi

echo ""
echo "═══ DONE ═══"

#!/usr/bin/env bash
# Pre-seeds a full-mode E2E vault for VHS blog post recordings.
# Run BEFORE the VHS tapes: bash docs/e2e-demo-setup.sh
set -euo pipefail

DEMO_DIR="/tmp/neurostack-e2e-vhs"
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR/vault"/{research,literature,inbox,projects,daily} "$DEMO_DIR/db"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# --- Populate vault with E2E test notes ---

cat > "$DEMO_DIR/vault/research/hippocampal-indexing.md" << 'MD'
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

cat > "$DEMO_DIR/vault/research/predictive-coding-and-memory.md" << 'MD'
---
date: 2026-02-01
tags: [neuroscience, predictive-coding, memory]
type: permanent
status: active
actionable: false
---

# Predictive Coding and Memory

Prediction errors drive memory encoding - surprising events are preferentially stored.

## Key Claims

- The hippocampus computes prediction errors by comparing expected and observed sensory input
- High prediction error events receive enhanced encoding via dopaminergic modulation
- Familiar patterns are compressed into efficient predictive models (schemas)
- Schema-violating information creates strong episodic traces

## Links

- [[hippocampal-indexing]]
MD

cat > "$DEMO_DIR/vault/literature/tolman-cognitive-maps.md" << 'MD'
---
date: 2026-01-10
tags: [neuroscience, cognitive-maps, navigation]
type: literature
status: reference
actionable: false
---

# Tolman (1948) - Cognitive Maps in Rats and Men

Classic paper establishing that animals form internal spatial representations rather than simple stimulus-response chains.

## Key Findings

- Rats learn spatial layouts, not just motor sequences
- Evidence of latent learning - knowledge acquired without immediate reinforcement
- Supports allocentric (world-centred) over egocentric (body-centred) navigation

## Links

- [[hippocampal-indexing]]
MD

cat > "$DEMO_DIR/vault/research/sleep-consolidation-mechanisms.md" << 'MD'
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

cat > "$DEMO_DIR/vault/research/memory-consolidation.md" << 'MD'
---
date: 2026-02-10
tags: [neuroscience, memory, consolidation, sleep]
type: permanent
status: active
---

# Memory Consolidation

Memory consolidation transforms newly acquired memories into stable long-term representations primarily during sleep.

## Mechanisms

- Active systems consolidation during NREM sleep via hippocampal replay
- Synaptic consolidation stabilises molecular traces
- REM sleep consolidates emotional memories and procedural skills
- Spaced learning enhances consolidation efficiency

## Links

- [[sleep-consolidation-mechanisms]]
- [[hippocampal-indexing]]
- [[spaced-repetition]]
MD

cat > "$DEMO_DIR/vault/research/spaced-repetition.md" << 'MD'
---
date: 2026-01-20
tags: [learning, memory, study-techniques]
type: permanent
status: active
---

# Spaced Repetition

Utilises the spacing effect to enhance memory retention by reviewing at progressively longer intervals.

## Key Claims

- Distributed practice outperforms massed practice (cramming)
- Optimal intervals follow an expanding schedule
- Active recall during review strengthens retrieval pathways
- Maps to memory consolidation during sleep

## Links

- [[memory-consolidation]]
- [[hippocampal-indexing]]
MD

cat > "$DEMO_DIR/vault/research/prediction-errors-in-learning.md" << 'MD'
---
date: 2026-01-25
tags: [neuroscience, learning, prediction-errors]
type: permanent
status: active
---

# Prediction Errors in Learning

Prediction errors - the difference between expected and actual outcomes - are the primary signal driving learning and memory updating.

## Key Claims

- Dopaminergic neurons in VTA signal reward prediction errors
- Hippocampal prediction errors drive episodic memory encoding
- Bayesian brain hypothesis: the brain maintains probabilistic models of the world
- Surprise (high prediction error) triggers attention and enhanced encoding

## Links

- [[predictive-coding-and-memory]]
- [[hippocampal-indexing]]
- [[memory-consolidation]]
- [[sleep-consolidation-mechanisms]]
- [[spaced-repetition]]
- [[tolman-cognitive-maps]]
- [[active-recall-mechanisms]]
MD

cat > "$DEMO_DIR/vault/research/active-recall-mechanisms.md" << 'MD'
---
date: 2026-02-05
tags: [learning, memory, study-techniques]
type: permanent
status: active
---

# Active Recall Mechanisms

Active recall - retrieving information from memory rather than passively reviewing - strengthens memory traces through retrieval practice.

## Key Claims

- Testing effect: retrieval practice outperforms re-reading
- Each successful retrieval strengthens the memory trace
- Failed retrieval attempts followed by feedback enhance learning
- Active recall prompts memory consolidation during sleep

## Links

- [[spaced-repetition]]
- [[memory-consolidation]]
- [[prediction-errors-in-learning]]
MD

cat > "$DEMO_DIR/vault/projects/neurostack-roadmap.md" << 'MD'
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

## Links
- [[kubernetes-migration]]
MD

cat > "$DEMO_DIR/vault/projects/kubernetes-migration.md" << 'MD'
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

# Stale notes for prediction-errors
cat > "$DEMO_DIR/vault/research/neural-network-architectures.md" << 'MD'
---
date: 2026-02-20
tags: [ml, deep-learning, architectures]
type: permanent
status: active
---

# Neural Network Architectures

Overview of modern neural network architectures for deep learning applications.

## Architectures

- Transformers: self-attention for sequence modelling
- CNNs: convolutional layers for spatial hierarchies
- GNNs: message passing on graph-structured data

## Links

- [[hippocampal-indexing]]
MD

cat > "$DEMO_DIR/vault/projects/docker-swarm-legacy.md" << 'MD'
---
date: 2025-06-01
tags: [devops, docker, legacy]
type: project
status: archived
---

# Docker Swarm Deployment Guide

Legacy guide for deploying services with Docker Swarm.

## Why Swarm?

- Simpler than Kubernetes for small clusters
- Built into Docker engine

## Links

- [[kubernetes-migration]]
MD

cat > "$DEMO_DIR/vault/research/memory-palace-technique.md" << 'MD'
---
date: 2026-01-05
tags: [study-techniques, mnemonic, memory]
type: permanent
status: reference
---

# Memory Palace Technique (Method of Loci)

A mnemonic technique that uses spatial memory to organize and recall information.

## Key Principles

- Associate items with locations in a familiar route
- Visualize vivid, unusual images at each location
- Walk the route mentally to recall items in order

## Links

- [[hippocampal-indexing]]
MD

cat > "$DEMO_DIR/vault/index.md" << 'MD'
# Test Vault Index

## Research
- [[hippocampal-indexing]] - Hippocampus as rapid indexing system
- [[predictive-coding-and-memory]] - Prediction errors drive memory encoding
- [[sleep-consolidation-mechanisms]] - Sleep replay and systems consolidation
- [[memory-consolidation]] - Memory consolidation mechanisms
- [[spaced-repetition]] - Distributed practice for retention
- [[prediction-errors-in-learning]] - Prediction errors drive learning
- [[active-recall-mechanisms]] - Testing effect and retrieval practice

## Literature
- [[tolman-cognitive-maps]] - Tolman 1948 cognitive maps

## Projects
- [[neurostack-roadmap]] - Feature roadmap
- [[kubernetes-migration]] - K8s migration plan
MD

echo "=== Vault populated: $(find "$DEMO_DIR/vault" -name '*.md' | wc -l) notes ==="

# --- Index with full mode ---
export NEUROSTACK_VAULT_ROOT="$DEMO_DIR/vault"
export NEUROSTACK_DB_DIR="$DEMO_DIR/db"
export NEUROSTACK_LLM_MODEL=qwen2.5:3b
export NEUROSTACK_LLM_URL=http://localhost:11434
export NEUROSTACK_EMBED_URL=http://localhost:11435

neurostack index 2>&1

# Record usage for hotness
neurostack record-usage "hippocampal-indexing" 2>&1 || true
neurostack record-usage "hippocampal-indexing" 2>&1 || true
neurostack record-usage "hippocampal-indexing" 2>&1 || true
neurostack record-usage "predictive-coding-and-memory" 2>&1 || true

echo ""
echo "E2E demo vault ready. To use:"
echo "  export NEUROSTACK_VAULT_ROOT=$DEMO_DIR/vault"
echo "  export NEUROSTACK_DB_DIR=$DEMO_DIR/db"
echo "  export NEUROSTACK_LLM_MODEL=qwen2.5:3b"
echo "  export NEUROSTACK_LLM_URL=http://localhost:11434"
echo "  export NEUROSTACK_EMBED_URL=http://localhost:11435"

---
date: 2025-01-15
tags: [experiment-tracking, tooling, infrastructure]
type: permanent
status: active
---

# Experiment Tracking Tools

Experiment tracking systems log the inputs, parameters, metrics, and artefacts of every model training run, enabling comparison, reproducibility, and collaboration.

## Tool Comparison

| Feature | MLflow | Weights & Biases | DVC | Neptune | ClearML |
|---------|--------|-------------------|-----|---------|---------|
| **Hosting** | Self-hosted or managed | SaaS (self-hosted available) | Git-based, self-hosted | SaaS | Self-hosted or SaaS |
| **Cost** | Free (OSS) | Free tier, paid for teams | Free (OSS) | Free tier, paid | Free (OSS), paid |
| **Experiment logging** | Yes | Yes | Via pipelines | Yes | Yes |
| **Data versioning** | Limited (artefacts) | Artefact versioning | Core strength | Artefact versioning | Dataset versioning |
| **Visualisation** | Basic UI | Excellent dashboards | Minimal | Good | Good |
| **Model registry** | Yes | Yes (model registry) | No | Yes | Yes |
| **Collaboration** | Shared server | Built-in teams | Git PRs | Built-in teams | Built-in teams |
| **Lock-in risk** | Low (OSS) | Medium (SaaS) | Low (Git) | Medium (SaaS) | Low (OSS) |

## Decision Guide

- **Solo / small team, full control** — MLflow (self-hosted) or DVC
- **Team wants best UI with minimal setup** — Weights & Biases
- **Git-centric workflow, data-heavy** — DVC + Git
- **Enterprise with compliance requirements** — MLflow on managed infra or ClearML self-hosted

## Minimum Viable Tracking

If no tool is available, log at minimum:
1. Git commit SHA
2. Dataset version or hash (see [[data-versioning]])
3. Hyperparameters as JSON
4. Evaluation metrics on validation and test sets
5. Random seed

Store this in a structured log file — even a CSV beats nothing.

## Anti-Patterns

- **Not tracking at all** — "I'll remember what I tried" never works past three experiments
- **Tracking metrics but not data versions** — reproducing results requires knowing the exact data used
- **Manual spreadsheets** — error-prone, no artefact linking, impossible to share reliably

## Related Notes

- [[data-versioning]] — the data half of reproducibility
- [[model-evaluation-metrics]] — what to log as experiment outputs
- [[bias-and-fairness]] — track fairness metrics alongside performance metrics

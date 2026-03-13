---
date: 2026-01-10
tags: [learning, memory, neuroscience]
type: permanent
status: active
actionable: true
compositional: true
---

# Spaced Repetition

Spaced repetition leverages the **spacing effect** — the finding that information is retained more effectively when review sessions are distributed over time rather than massed together.

## Core Mechanism

The optimal review interval follows an exponential growth curve:
- First review: 1 day after learning
- Second review: 3 days later
- Third review: 7 days later
- Each subsequent interval roughly doubles

This maps to [[memory-consolidation]] during sleep — each review reactivates the memory trace and strengthens synaptic connections through long-term potentiation.

## Connection to Prediction Errors

When you retrieve information successfully during review, the **prediction error** is low — the brain predicted correctly. When retrieval fails, the prediction error is high, signalling that the memory trace needs reinforcement. See [[prediction-errors-in-learning]].

## Practical Applications

- Anki and SuperMemo implement the SM-2 algorithm
- Effective for declarative knowledge (facts, concepts, vocabulary)
- Less effective for procedural skills (programming, sports)
- Works best when combined with [[active-recall]] and [[interleaving]]

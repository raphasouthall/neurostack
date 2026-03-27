---
date: 2026-01-05
tags: [neuroscience, architecture, memory]
type: permanent
status: reference
actionable: false
compositional: true
---

# Complementary Learning Systems

The CLS theory (McClelland, McNaughton & O'Reilly, 1995) proposes that intelligent systems require two complementary learning mechanisms operating at different timescales.

## The Two Systems

### Hippocampus (Fast Learner)
- Rapid, one-shot encoding of episodes
- Pattern separation — keeps similar memories distinct
- High learning rate, sparse representations
- Vulnerable to interference

### Neocortex (Slow Learner)
- Gradual extraction of statistical regularities
- Pattern completion — fills in missing information
- Low learning rate, distributed representations
- Resistant to catastrophic forgetting

## Why Both Are Needed

A system with only fast learning (pure hippocampus) would:
- Overfit to recent experiences
- Fail to extract general patterns
- Suffer catastrophic interference

A system with only slow learning (pure neocortex) would:
- Fail to remember specific episodes
- Need many exposures to learn anything
- Miss rare but important events

## Analogies in Computing

| Biological | Computing | Knowledge Vault |
|-----------|-----------|-----------------|
| Hippocampus | Cache / RAM | Inbox, daily notes |
| Neocortex | Database / Disk | Permanent notes |
| Sleep replay | ETL / batch job | Periodic review |
| Prediction error | Cache invalidation | Drift detection |

## Related

- [[memory-consolidation]] — The mechanism of hippocampal-to-cortical transfer
- [[prediction-errors-in-learning]] — Error signals that guide learning

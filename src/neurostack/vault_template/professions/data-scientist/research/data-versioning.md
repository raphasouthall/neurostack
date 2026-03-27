---
date: 2025-01-15
tags: [versioning, reproducibility, infrastructure]
type: permanent
status: active
actionable: true
compositional: false
---

# Data Versioning

Data versioning tracks the exact state of datasets, features, and model artefacts used in each experiment, making results reproducible and regressions traceable.

## Why Version Data

- **Reproducibility** — re-run any experiment with its exact inputs
- **Debugging** — trace a production issue to a specific data or model version
- **Auditing** — comply with regulations requiring lineage documentation
- **Collaboration** — team members work from the same dataset state

## Versioning Strategies

| Strategy | Pros | Cons | Best For |
|----------|------|------|----------|
| DVC (Data Version Control) | Git-native, lightweight pointers | Requires remote storage setup | Files on disk, Git workflows |
| Delta Lake / Iceberg | Time-travel queries, ACID | Tied to Spark/cloud ecosystem | Large-scale analytics |
| LakeFS | Git-like branching for data lakes | Additional infrastructure | S3-based data lakes |
| Manual snapshots | Simple, no tooling needed | Error-prone, storage-heavy | Small projects, prototyping |

## What to Version

- **Raw data** — as received from source, before any transformation
- **Processed data** — after cleaning and feature engineering
- **Feature stores** — the exact feature vectors fed to training
- **Model artefacts** — serialised models, configs, hyperparameters
- **Evaluation outputs** — metrics, predictions, confusion matrices

## Naming Convention

```
dataset-name/v{MAJOR}.{MINOR}
  MAJOR = schema change or significant reprocessing
  MINOR = data refresh with same schema
```

## Integration with Experiment Tracking

Every experiment log should reference:
- Dataset version (hash or tag)
- Code commit (git SHA)
- Environment snapshot (requirements.txt / conda.yml)

This triad — data, code, environment — is the minimum for reproducibility. See [[experiment-tracking-tools]] for tool comparisons.

## Related Notes

- [[experiment-tracking-tools]] — tools that integrate data versioning with experiment logging
- [[exploratory-data-analysis]] — version the dataset after EDA-driven cleaning
- [[feature-engineering-patterns]] — version feature sets independently of raw data

---
date: 2025-01-15
tags: [eda, methodology, data-quality]
type: permanent
status: active
---

# Exploratory Data Analysis

EDA is the disciplined process of understanding a dataset's structure, quality, and distributions before modelling. Skipping EDA is the single most common source of avoidable model failures.

## Structured EDA Checklist

1. **Shape & schema** — row count, column types, cardinality of categoricals
2. **Missing data** — proportion per column, missingness patterns (MCAR / MAR / MNAR)
3. **Distributions** — histograms and KDE for numerics, value counts for categoricals
4. **Outliers** — IQR method, z-scores, domain-specific thresholds
5. **Correlations** — pairwise numeric correlations, mutual information for mixed types
6. **Temporal patterns** — trends, seasonality, stationarity if time-indexed
7. **Target leakage** — features that encode the label directly or via proxy

## Tools by Scale

| Dataset Size | Recommended Stack |
|-------------|-------------------|
| < 1 GB | pandas + matplotlib/seaborn |
| 1-100 GB | polars, DuckDB, or Spark |
| > 100 GB | Spark / BigQuery with sampled EDA locally |

## Anti-Patterns

- Plotting everything without a question — EDA should be hypothesis-driven
- Trusting `.describe()` alone — summary stats hide multi-modal distributions and outliers
- Cleaning before looking — understand the mess before deciding what to fix

## When to Stop

EDA is complete when you can confidently answer:
- What is the grain of each row?
- Which features are informative vs noisy?
- What preprocessing does the data need before modelling?

## Related Notes

- [[feature-engineering-patterns]] — transformations informed by EDA findings
- [[model-evaluation-metrics]] — EDA reveals class imbalance that affects metric choice
- [[data-versioning]] — snapshot the dataset state after EDA-driven cleaning

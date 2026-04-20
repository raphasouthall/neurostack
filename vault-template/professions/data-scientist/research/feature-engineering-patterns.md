---
date: 2025-01-15
tags: [feature-engineering, preprocessing, methodology]
type: permanent
status: active
---

# Feature Engineering Patterns

Feature engineering is the process of transforming raw data into representations that improve model performance. The best features encode domain knowledge into a form the model can exploit.

## Patterns by Data Type

### Numeric

| Pattern | When to Use | Example |
|---------|-------------|---------|
| Log transform | Right-skewed distributions | Income, page views |
| Binning | Non-linear relationships | Age groups, price tiers |
| Interaction terms | Combined effects matter | Price x Quantity |
| Rolling statistics | Time-series context | 7-day mean, 30-day std |
| Ratio features | Relative magnitude matters | Revenue per employee |

### Categorical

| Pattern | When to Use | Example |
|---------|-------------|---------|
| One-hot encoding | Low cardinality (< 20) | Country, department |
| Target encoding | High cardinality | Postcode, product ID |
| Frequency encoding | When prevalence signals value | Rare vs common categories |
| Embedding | Very high cardinality + deep learning | User ID, item ID |

### Temporal

| Pattern | When to Use | Example |
|---------|-------------|---------|
| Cyclical encoding | Periodic features | Hour of day (sin/cos) |
| Time since event | Recency matters | Days since last purchase |
| Lag features | Autoregressive patterns | Value at t-1, t-7 |
| Calendar features | Business patterns | Is weekend, is holiday |

### Text

| Pattern | When to Use | Example |
|---------|-------------|---------|
| TF-IDF | Bag-of-words baseline | Document classification |
| Sentence embeddings | Semantic similarity | Search, clustering |
| Named entity counts | Domain-specific signals | Number of organisations mentioned |

## Feature Selection Signals

- **Permutation importance** — model-agnostic, works on any estimator
- **SHAP values** — directional importance, detects interactions
- **Null importances** — compare real vs shuffled-target importance to find noise features
- **Correlation with target** — quick univariate filter, misses interactions

## Anti-Patterns

- Encoding the target — any feature derived from the label is leakage
- Over-engineering before baseline — start with raw features, add complexity only when justified
- Ignoring feature drift — features that worked in training may shift in production; see [[data-versioning]]

## Related Notes

- [[exploratory-data-analysis]] — EDA reveals which patterns to apply
- [[model-evaluation-metrics]] — validate that engineered features actually help
- [[bias-and-fairness]] — encoding protected attributes via proxy features

---
date: 2025-01-15
tags: [evaluation, metrics, methodology]
type: permanent
status: active
---

# Model Evaluation Metrics

Choosing the right evaluation metric is a modelling decision, not a technical one. The metric encodes what you care about — optimising the wrong metric produces a model that succeeds on paper and fails in production.

## Decision Framework

### Classification

| Scenario | Recommended Metric | Why |
|----------|-------------------|-----|
| Balanced classes, equal error costs | F1 / Accuracy | Symmetric penalty |
| Imbalanced classes | PR-AUC, F1 on minority class | ROC-AUC flatters under imbalance |
| Ranking matters (top-k) | Precision@k, NDCG | Only top predictions matter |
| Cost-asymmetric errors | Custom cost matrix | False negatives cost more than false positives (or vice versa) |
| Calibrated probabilities needed | Brier score, log loss | When you need reliable confidence estimates |

### Regression

| Scenario | Recommended Metric | Why |
|----------|-------------------|-----|
| General performance | RMSE | Penalises large errors |
| Outlier-robust | MAE, Median AE | Less sensitive to extremes |
| Relative error matters | MAPE, sMAPE | Percentage-based interpretation |
| Business units | Custom (e.g., revenue impact) | Translate error into domain units |

### Ranking & Recommendation

| Scenario | Recommended Metric | Why |
|----------|-------------------|-----|
| Binary relevance | MAP, MRR | Position-aware retrieval |
| Graded relevance | NDCG | Weights by relevance level |
| Diversity needed | Coverage, intra-list diversity | Avoid filter bubbles |

## Common Mistakes

- **Optimising accuracy on imbalanced data** — a model predicting the majority class always achieves high accuracy with zero utility
- **Using RMSE when MAE matches the business objective** — RMSE disproportionately penalises large errors, which may or may not matter
- **Reporting only aggregate metrics** — always break down by slice (cohort, time period, category) to catch hidden failures
- **Ignoring calibration** — a model with good AUC but poor calibration is dangerous when probabilities drive decisions

## Validation Strategy

- **Holdout** — fast but high variance on small datasets
- **K-fold cross-validation** — reduced variance, use stratified folds for classification
- **Time-series split** — forward-chaining only; never let future data leak into training
- **Group-aware split** — when rows within a group are correlated (e.g., multiple rows per user)

## Related Notes

- [[exploratory-data-analysis]] — class distribution drives metric choice
- [[bias-and-fairness]] — fairness metrics complement performance metrics
- [[experiment-tracking-tools]] — log metrics consistently across experiments

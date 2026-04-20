---
date: 2025-01-15
tags: [fairness, ethics, evaluation, methodology]
type: permanent
status: active
---

# Bias and Fairness

Bias in ML systems arises when model predictions systematically disadvantage specific groups. Fairness is not a single metric — it requires choosing which definition of fairness matches the deployment context.

## Sources of Bias

| Stage | Bias Type | Example |
|-------|-----------|---------|
| Data collection | Representation bias | Training data underrepresents minority groups |
| Labelling | Annotation bias | Labellers bring cultural assumptions to subjective tasks |
| Feature engineering | Proxy discrimination | Postcode encodes race via residential segregation |
| Modelling | Amplification bias | Model learns and amplifies existing disparities |
| Evaluation | Aggregation bias | Overall accuracy hides poor performance on subgroups |
| Deployment | Feedback loops | Biased predictions change behaviour, generating more biased data |

## Fairness Definitions

These definitions are mathematically incompatible in most real-world settings (Chouldechova, 2017). You must choose based on context.

| Definition | Condition | Use When |
|-----------|-----------|----------|
| Demographic parity | P(Y=1\|A=0) = P(Y=1\|A=1) | Equal selection rates matter (hiring quotas) |
| Equalised odds | TPR and FPR equal across groups | Equal error rates matter (criminal justice) |
| Predictive parity | PPV equal across groups | Trust in positive predictions must be equal |
| Individual fairness | Similar individuals get similar predictions | Case-by-case decisions (loan pricing) |
| Counterfactual fairness | Prediction unchanged if protected attribute flipped | Causal reasoning is possible |

## Practical Evaluation Checklist

1. **Identify protected attributes** — race, gender, age, disability, religion (jurisdiction-dependent)
2. **Measure performance by subgroup** — disaggregate all metrics from [[model-evaluation-metrics]]
3. **Test for proxy features** — check feature importance conditioned on protected attributes
4. **Apply fairness metrics** — choose from the table above based on deployment context
5. **Document trade-offs** — fairness interventions often reduce overall accuracy; record the Pareto frontier
6. **Monitor in production** — distribution shifts can introduce bias post-deployment

## Mitigation Strategies

- **Pre-processing** — resampling, reweighting, or removing proxy features
- **In-processing** — constrained optimisation, adversarial debiasing
- **Post-processing** — threshold adjustment per group to equalise chosen metric

## Tooling

- **Fairlearn** (Python) — metrics and mitigation algorithms
- **AI Fairness 360** (IBM) — comprehensive bias detection suite
- **What-If Tool** (Google) — interactive exploration of fairness trade-offs

## Related Notes

- [[model-evaluation-metrics]] — fairness metrics extend standard evaluation
- [[feature-engineering-patterns]] — proxy features as a source of bias
- [[exploratory-data-analysis]] — EDA should check representation across groups
- [[experiment-tracking-tools]] — log fairness metrics alongside performance

---
date: 2025-01-15
tags: [technical-debt, architecture, planning]
type: permanent
status: active
---

# Technical Debt Management

Technical debt is the implied cost of future rework caused by choosing a quick solution now instead of a better approach that would take longer (Cunningham, 1992).

## Debt Quadrant (Fowler)

| | Reckless | Prudent |
|---|----------|---------|
| **Deliberate** | "We don't have time for design" | "We must ship now and deal with consequences" |
| **Inadvertent** | "What's layering?" | "Now we know how we should have done it" |

Only **prudent deliberate** debt is strategically useful. All other quadrants indicate process or knowledge gaps.

## Identification Signals

- **Code-level**: High cyclomatic complexity, duplicated logic, long methods, missing tests
- **Architecture-level**: Circular dependencies, God services, shared mutable state
- **Process-level**: Increasing time-to-merge, rising incident rate, onboarding friction
- **Metric proxies**: Code churn on same files, bug clustering, deploy frequency decline

## Paying It Down

### The Boy Scout Rule

Leave every file you touch cleaner than you found it. Small, continuous improvements compound.

### Dedicated Allocation

- **20% rule**: Reserve a fraction of each sprint for debt reduction
- **Tech debt sprints**: Periodic full-sprint cleanup (controversial — tends to get deprioritised)
- **Strangler fig**: Incrementally replace legacy components with new implementations behind an interface (see [[refactoring-patterns]])

### Prioritisation Framework

Score each debt item on:

1. **Impact** — how much does it slow us down? (1-5)
2. **Reach** — how many teams/features does it affect? (1-5)
3. **Fix cost** — how much effort to resolve? (1-5, inverted: 5 = cheap)

Priority = Impact x Reach x Fix cost. Tackle highest scores first.

## Communicating to Stakeholders

- Frame debt as **risk**, not cleanup — "this increases our incident probability by X"
- Tie to business metrics: deploy lead time, mean time to recovery, defect rate
- Never ask for a "refactoring quarter" — embed debt work in feature delivery

## Related Notes

- [[twelve-factor-app]] — twelve-factor violations are a common source of architectural debt
- [[refactoring-patterns]] — tactical approaches for paying down code-level debt
- [[code-review-best-practices]] — reviews are a debt prevention mechanism
- [[testing-pyramid]] — missing tests are the most dangerous form of hidden debt

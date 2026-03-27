---
date: 2025-01-15
tags: [testing, quality, architecture]
type: permanent
status: active
actionable: true
compositional: true
---

# Testing Pyramid

The testing pyramid (Cohn, 2009) models the ideal distribution of automated tests: many fast unit tests at the base, fewer integration tests in the middle, and a small number of slow end-to-end tests at the top.

## Layer Characteristics

| Layer | Scope | Speed | Stability | Typical Ratio |
|-------|-------|-------|-----------|---------------|
| Unit | Single function/class | < 10ms | High | 70% |
| Integration | Module boundaries, DB, APIs | 100ms-5s | Medium | 20% |
| E2E / UI | Full user journey | 10s-60s | Low (flaky) | 10% |

## Why the Pyramid Shape

- **Fast feedback**: Unit tests run in seconds, enabling tight development loops
- **Failure isolation**: A failing unit test points to the exact broken function
- **Cost of maintenance**: E2E tests are expensive to write, slow to run, and break on unrelated UI changes
- **Diminishing returns**: Each layer above catches fewer unique bugs per test-minute

## When the Pyramid Breaks

### The Ice Cream Cone (anti-pattern)

Heavy reliance on manual testing and E2E, few or no unit tests. Symptoms: slow CI, flaky builds, fear of refactoring.

### The Hourglass

Many unit tests, many E2E tests, but nothing in between. Integration bugs slip through because module boundaries are untested.

### The Trophy (Kent C. Dodds)

For frontend-heavy applications, integration tests provide the best cost-to-confidence ratio. The trophy shape: static analysis > unit > **integration** > E2E.

## Practical Guidelines

- **Test behaviour, not implementation** — tests should survive refactoring
- **One assertion per concept** — not necessarily one assertion per test, but one logical check
- **Use test doubles wisely** — mock at boundaries (network, filesystem), not internal collaborators
- **Treat test code as production code** — readable, DRY where it helps, but clarity over cleverness
- **Flaky tests are worse than no tests** — they erode trust. Fix or delete.

## Coverage as a Signal

- Coverage measures lines executed, not correctness — 100% coverage can still miss logic errors
- Useful as a **floor** (flag untested code), dangerous as a **target** (incentivises bad tests)
- Mutation testing (Pitest, Stryker) is a stronger measure: does changing code actually break tests?

## Related Notes

- [[code-review-best-practices]] — review test quality alongside production code
- [[technical-debt-management]] — missing tests are high-interest debt
- [[twelve-factor-app]] — dev/prod parity (factor X) determines whether tests reflect production
- [[refactoring-patterns]] — a solid test suite is a prerequisite for safe refactoring

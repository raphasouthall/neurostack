---
date: 2025-01-15
tags: [refactoring, code-quality, patterns]
type: permanent
status: active
---

# Refactoring Patterns

Refactoring is the disciplined practice of restructuring existing code without changing its external behaviour (Fowler, 1999). The goal is to improve internal structure — readability, modularity, testability — while preserving correctness.

## Prerequisites for Safe Refactoring

- **Tests exist and pass** — refactoring without tests is editing with your eyes closed (see [[testing-pyramid]])
- **Version control** — commit before and after each refactoring step
- **Small steps** — each transformation should be individually reversible

## High-Value Refactoring Patterns

### Extract Function/Method

**When**: A block of code has a comment explaining what it does, or a method exceeds ~20 lines.
**Effect**: Improves readability, enables reuse, makes testing granular.

### Replace Conditional with Polymorphism

**When**: A switch/if-else chain dispatches on type and repeats across the codebase.
**Effect**: Eliminates shotgun surgery — adding a new type means adding a class, not editing N switch statements.

### Introduce Parameter Object

**When**: Multiple functions pass the same cluster of parameters together.
**Effect**: Reduces parameter count, creates a named concept, enables validation in one place.

### Strangler Fig

**When**: A legacy system needs replacement but cannot be rewritten at once.
**Effect**: New functionality is built alongside the old system behind a routing layer. Traffic shifts incrementally. The old system is decommissioned when the new one covers all cases.

### Replace Magic Values with Constants/Enums

**When**: Literal numbers or strings appear in logic (`if status == "3"`).
**Effect**: Eliminates a class of typo-driven bugs, improves searchability and documentation.

## Code Smells as Refactoring Triggers

| Smell | Suggested Refactoring |
|-------|----------------------|
| Long method | Extract Function |
| Feature envy | Move Method to the class it envies |
| Data clump | Introduce Parameter Object |
| Primitive obsession | Replace Primitive with Value Object |
| Divergent change | Extract Class (single responsibility) |
| Shotgun surgery | Move related logic together |
| Dead code | Delete it (version control remembers) |

## Refactoring vs. Rewriting

- **Refactoring**: Incremental, safe, continuous. Keeps the system working throughout.
- **Rewriting**: High risk, long timeline, second-system effect. Justified only when the existing architecture fundamentally cannot support new requirements.
- The Strangler Fig pattern bridges both — it is a rewrite executed as a sequence of refactorings.

## Communicating Refactoring Work

- Don't mix refactoring commits with feature commits — reviewers need to verify behaviour preservation (see [[code-review-best-practices]])
- Frame refactoring as risk reduction: "This change reduces the probability of regression when we build feature X"
- Track refactoring as [[technical-debt-management|debt paydown]], not busywork

## Related Notes

- [[testing-pyramid]] — tests are a prerequisite, not an optional companion
- [[technical-debt-management]] — refactoring is the primary mechanism for paying down code debt
- [[code-review-best-practices]] — separate refactoring PRs are easier to review
- [[api-design-principles]] — Strangler Fig enables safe API evolution

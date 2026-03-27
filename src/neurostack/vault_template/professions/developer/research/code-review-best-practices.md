---
date: 2025-01-15
tags: [code-review, collaboration, quality]
type: permanent
status: active
actionable: true
compositional: false
---

# Code Review Best Practices

Code review is one of the most effective defect-prevention techniques available, catching 60-90% of defects when done well (Fagan, 1976; McConnell, 2004). Its value extends beyond bug-finding to knowledge sharing, mentorship, and codebase consistency.

## What to Look For (Priority Order)

1. **Correctness** — does it do what it claims?
2. **Security** — injection, auth bypass, secrets in code
3. **Design** — appropriate abstractions, single responsibility, coupling
4. **Testability** — is the change tested? Are tests meaningful?
5. **Readability** — naming, structure, comments where non-obvious
6. **Performance** — only when relevant (see [[api-design-principles]] for API-level concerns)
7. **Style** — defer to automated formatters; don't spend human attention here

## Reviewer Guidelines

- **Timebox**: Review within 24 hours. Long review queues kill velocity.
- **Batch size**: Review at most 400 lines at once — defect detection drops sharply beyond this (Cisco study)
- **Be specific**: "This could NPE when user is null" beats "looks fragile"
- **Distinguish severity**: Blocking issue vs. suggestion vs. nitpick
- **Ask questions**: "What happens if X?" teaches more than "You forgot X"
- **Praise good work**: Positive reinforcement shapes codebase culture

## Author Guidelines

- **Small PRs**: Under 400 lines. Split larger work into stacked PRs.
- **Self-review first**: Read your own diff before requesting review
- **Description matters**: Explain the why, not just the what. Link to the ticket.
- **Annotate tricky bits**: Proactively comment on non-obvious decisions

## Common Anti-Patterns

| Anti-Pattern | Consequence | Fix |
|-------------|-------------|-----|
| Rubber-stamping | Defects ship, trust erodes | Minimum review checklist |
| Gatekeeping | Bottleneck on one person | Rotate reviewers, pair review |
| Style wars | Wasted energy, resentment | Automate formatting, adopt a style guide |
| Drive-by reviews | No context, surface-level comments | Require reading the linked issue |

## Related Notes

- [[testing-pyramid]] — tests complement review; neither replaces the other
- [[technical-debt-management]] — reviews prevent debt accumulation
- [[refactoring-patterns]] — recognising refactoring opportunities during review

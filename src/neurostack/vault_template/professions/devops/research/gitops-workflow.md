---
date: 2025-01-15
tags: [gitops, ci-cd, deployment, automation]
type: permanent
status: active
---

# GitOps Workflow

GitOps is an operational framework where the entire system is described declaratively in git, and an automated agent ensures the live system matches the desired state in the repository. Git becomes the single source of truth for both application and infrastructure.

## Core Principles

1. **Declarative** — the entire system is described declaratively (Kubernetes manifests, Terraform, Helm charts)
2. **Versioned** — the desired state is stored in git, providing a complete audit trail
3. **Automated** — approved changes are automatically applied to the environment
4. **Self-healing** — the agent continuously reconciles drift between desired and actual state

## Push vs Pull Models

### Push (CI-driven)

Pipeline runs `kubectl apply` or `terraform apply` after merge.

- Simpler to implement — add a deploy step to existing CI
- Pipeline needs cluster credentials — broader attack surface
- No continuous reconciliation — drift between deploys goes undetected
- Examples: GitHub Actions deploy step, Azure DevOps release pipeline

### Pull (Agent-driven)

An operator running inside the cluster watches the git repo and applies changes.

- Cluster pulls from git — no external credentials needed
- Continuous reconciliation — drift is automatically corrected
- Requires an operator deployment (Flux, ArgoCD)
- Examples: Flux CD, ArgoCD, Rancher Fleet

**Recommendation**: Pull-based for Kubernetes workloads, push-based for cloud infrastructure (Terraform/Bicep don't have a native reconciliation loop).

## Branching Strategy for GitOps

- **Trunk-based with environment directories** — `environments/dev/`, `environments/staging/`, `environments/prod/` in one repo. Promotion = PR from dev values to prod values.
- **Branch-per-environment** — `dev`, `staging`, `main` branches. Promotion = merge. Simpler but prone to branch drift.
- **App repo + config repo** — CI builds artefacts and updates image tags in a separate config repo. Separation of concerns, but more moving parts.

## Practical Checklist

- [ ] All manifests in git — no `kubectl edit` or `kubectl apply` from laptops
- [ ] Image tags are immutable — use digests or semantic versions, never `:latest`
- [ ] Secrets managed externally — SOPS, Sealed Secrets, External Secrets Operator, or CSI driver
- [ ] Drift detection enabled — alert when actual state diverges from desired
- [ ] Rollback is a git revert — no special tooling needed

## When GitOps Breaks Down

- **Stateful operations** — database migrations, data backfills, and schema changes don't fit the reconciliation model
- **Emergency changes** — sometimes you need to apply a fix directly; the key is backfilling the change into git immediately
- **Cross-cutting changes** — a single change touching multiple repos/environments needs coordination beyond git merge

## Related Notes

- [[infrastructure-as-code-principles]] — GitOps is IaC's deployment mechanism
- [[incident-management-lifecycle]] — git revert as a remediation path
- [[observability-three-pillars]] — correlating deployments with metric changes
- [[sre-golden-signals]] — monitoring the impact of each deployment

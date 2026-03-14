---
date: 2025-01-15
tags: [iac, automation, infrastructure, principles]
type: permanent
status: active
actionable: true
compositional: true
---

# Infrastructure as Code Principles

Infrastructure as Code (IaC) is the practice of managing infrastructure through declarative definition files rather than manual processes, enabling version control, peer review, and reproducible environments.

## Core Principles

### 1. Declarative Over Imperative

Describe the desired end state, not the steps to get there. The tool calculates the diff and applies changes.

- **Declarative**: Terraform, Bicep, Pulumi (in declarative mode), Kubernetes manifests
- **Imperative**: Shell scripts, Ansible ad-hoc commands, CLI one-liners
- **Trade-off**: Imperative is easier for one-off tasks; declarative is essential for drift detection and idempotency

### 2. Idempotency

Running the same code twice produces the same result. This is the property that makes IaC safe to re-apply.

- If your infrastructure code isn't idempotent, it's a script, not IaC
- Test idempotency by running `plan`/`what-if` after a successful apply — the diff should be empty

### 3. Version Control Everything

All infrastructure definitions live in git. No exceptions.

- State files need special handling — remote backends with locking (S3+DynamoDB, Azure Blob+lease, GCS)
- Secrets reference external stores (Key Vault, Secrets Manager, SOPS) — never committed to the repo
- See [[gitops-workflow]] for using git as the deployment trigger

### 4. Modularity

Compose infrastructure from reusable modules with clear interfaces.

- One module = one logical concern (e.g., a VPC, a Kubernetes cluster, a database)
- Pin module versions — `source = "git::...?ref=v1.2.0"`, not `ref=main`
- Document inputs, outputs, and assumptions

### 5. Immutable Infrastructure

Prefer replacing resources over mutating them in place.

- **Mutable**: SSH in, apt upgrade, restart — configuration drift is inevitable
- **Immutable**: Build a new image (Packer, Docker), deploy it, destroy the old one
- **Pragmatic middle**: Use immutable for compute (VMs, containers), mutable for stateful resources (databases) with controlled change windows

## Anti-Patterns

- **ClickOps** — manual console changes that bypass code review and audit trails
- **Snowflake environments** — dev/staging/prod diverge because they were built manually
- **Terraform monolith** — one state file for everything; blast radius is unbounded
- **Copy-paste modules** — duplicated code drifts apart; use versioned modules instead

## IaC Decision Matrix

| Scenario | Tool Choice | Why |
|----------|------------|-----|
| Cloud infra provisioning | Terraform / OpenTofu / Bicep | Declarative, provider ecosystem |
| Kubernetes resources | Helm + Kustomize | Native K8s tooling, templating |
| Configuration management | Ansible | Agentless, procedural when needed |
| Image building | Packer / Docker | Immutable artefacts |
| Policy enforcement | OPA / Sentinel / Azure Policy | Shift-left compliance |

## Related Notes

- [[gitops-workflow]] — IaC applied through git-driven deployment
- [[incident-management-lifecycle]] — IaC rollback as a remediation strategy
- [[chaos-engineering]] — testing IaC-provisioned infrastructure for resilience

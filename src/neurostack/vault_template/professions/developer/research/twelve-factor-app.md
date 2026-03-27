---
date: 2025-01-15
tags: [architecture, cloud-native, devops]
type: permanent
status: active
actionable: true
compositional: true
---

# Twelve-Factor App

The twelve-factor methodology (Wiggins, 2012) codifies best practices for building software-as-a-service applications that are portable, scalable, and suitable for continuous deployment.

## The Twelve Factors

| # | Factor | Principle | Anti-Pattern |
|---|--------|-----------|--------------|
| I | Codebase | One repo per app, many deploys | Multiple apps in one repo with shared deploy |
| II | Dependencies | Explicitly declare and isolate | Relying on system-wide packages |
| III | Config | Store in environment variables | Hardcoded connection strings |
| IV | Backing Services | Treat as attached resources | Tight coupling to local filesystem |
| V | Build, Release, Run | Strictly separate stages | SSH into prod and edit files |
| VI | Processes | Stateless, share-nothing | Sticky sessions with in-memory state |
| VII | Port Binding | Export services via port | Depending on runtime injection (e.g., war deployment) |
| VIII | Concurrency | Scale out via process model | Vertical scaling only |
| IX | Disposability | Fast startup, graceful shutdown | Long boot sequences, ungraceful termination |
| X | Dev/Prod Parity | Keep environments similar | "Works on my machine" |
| XI | Logs | Treat as event streams | Writing to local log files |
| XII | Admin Processes | Run as one-off processes | Manual database migrations |

## Modern Extensions

The original twelve factors predate containers and Kubernetes. Common additions:

- **API-first** — design contracts before implementation (see [[api-design-principles]])
- **Telemetry** — observability as a first-class concern, not an afterthought
- **Security** — shift left: dependency scanning, secrets management, least privilege

## Decision Framework

When evaluating an architecture decision, check each factor as a lens:

- Does this decision make the app more or less portable?
- Does it increase or decrease coupling to a specific runtime?
- Would a new team member understand the deployment from reading the repo?

## Related Notes

- [[api-design-principles]] — API-first as a modern thirteenth factor
- [[technical-debt-management]] — violations of twelve-factor principles are a common source of debt
- [[testing-pyramid]] — factor X (dev/prod parity) directly impacts test reliability

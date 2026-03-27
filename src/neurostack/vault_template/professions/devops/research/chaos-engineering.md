---
date: 2025-01-15
tags: [chaos-engineering, resilience, testing, sre]
type: permanent
status: active
actionable: true
compositional: true
---

# Chaos Engineering

Chaos engineering is the discipline of experimenting on a system to build confidence in its ability to withstand turbulent conditions in production. It is not random destruction — it is disciplined, hypothesis-driven failure injection.

## The Process

Chaos engineering follows the scientific method:

1. **Define steady state** — what does "normal" look like? Use [[sre-golden-signals]] as your baseline
2. **Hypothesise** — "If we kill one instance of service-X, the load balancer will route traffic to healthy instances with no user-visible impact"
3. **Inject failure** — introduce the real-world event (network partition, instance death, CPU spike, dependency latency)
4. **Observe** — compare actual behaviour against the hypothesis using [[observability-three-pillars|observability data]]
5. **Learn** — if the hypothesis held, confidence increases. If it didn't, you found a weakness before your users did

## Categories of Failure Injection

### Infrastructure

- Kill a VM/container/pod
- Fill a disk
- Degrade network (latency, packet loss, partition)
- Exhaust CPU or memory

### Application

- Inject latency into a dependency call
- Return errors from a downstream service
- Corrupt or delay messages in a queue
- Expire all cache entries simultaneously

### Process

- Page the on-call at 3am — does the runbook work? Does the person have access?
- Simulate a major incident — does the [[incident-management-lifecycle|incident process]] function under pressure?
- Revoke a team member's access — is there single-person dependency?

## Tools

| Tool | Scope | Key Feature |
|------|-------|------------|
| Chaos Monkey | VM/instance | Random instance termination |
| Litmus | Kubernetes | Cloud-native, CRD-based experiments |
| Gremlin | Multi-platform | SaaS, enterprise controls |
| Toxiproxy | Network | Programmable network proxy for testing |
| Chaos Mesh | Kubernetes | Comprehensive fault injection for K8s |
| Azure Chaos Studio | Azure | Native Azure fault injection |

## Maturity Model

**Level 0 — Ad hoc**: No intentional failure testing. Incidents are surprises.

**Level 1 — Game days**: Scheduled exercises in non-production environments. Manual injection, manual observation.

**Level 2 — Automated experiments**: Chaos experiments run automatically in staging. Results are tracked and compared.

**Level 3 — Production chaos**: Controlled failure injection in production with automated blast radius limits and kill switches. This is where Netflix operates.

**Level 4 — Continuous chaos**: Chaos experiments are part of the CI/CD pipeline. A deployment that can't survive failure injection doesn't reach production.

## Prerequisites (Don't Skip These)

- [ ] Observability is in place — you can't learn from chaos if you can't see the impact ([[observability-three-pillars]])
- [ ] Alerting works — golden signal alerts fire when expected ([[sre-golden-signals]])
- [ ] Runbooks exist — the team knows how to respond ([[incident-management-lifecycle]])
- [ ] Blast radius controls — ability to stop the experiment immediately if impact exceeds expectations
- [ ] Stakeholder buy-in — chaos in production requires organisational trust

## Common Objections and Responses

- **"We can't break things in production"** — Start in staging. Graduate to production when confidence and controls are in place
- **"We already test"** — Unit and integration tests verify expected behaviour. Chaos engineering explores unexpected behaviour
- **"We don't have time"** — You don't have time for uncontrolled outages either. Chaos engineering converts surprise incidents into planned learning

## Related Notes

- [[sre-golden-signals]] — defines the steady state baseline for experiments
- [[observability-three-pillars]] — provides the data to evaluate experiment outcomes
- [[incident-management-lifecycle]] — chaos exercises validate the incident process
- [[infrastructure-as-code-principles]] — IaC enables rapid environment rebuild after destructive experiments
- [[gitops-workflow]] — deployment pipeline integration for continuous chaos

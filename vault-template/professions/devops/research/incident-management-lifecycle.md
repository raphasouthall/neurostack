---
date: 2025-01-15
tags: [incident-management, sre, process, on-call]
type: permanent
status: active
---

# Incident Management Lifecycle

Incident management is the structured process of detecting, responding to, and learning from service disruptions. The goal is to restore service quickly and prevent recurrence through systemic improvements, not blame.

## Phases

### 1. Detection

The time between failure occurring and someone knowing about it. This is where most SLO budget silently burns.

- **Automated alerting** on [[sre-golden-signals]] — latency, traffic, errors, saturation
- **Synthetic monitoring** — probes that simulate user journeys and alert on failure
- **Customer reports** — if customers find issues before your alerts, your monitoring has gaps
- **Detection time** is a key metric — track Mean Time to Detect (MTTD)

### 2. Triage

Assess severity and decide the response level.

| Severity | Criteria | Response |
|----------|---------|----------|
| SEV1 | Service down, data loss risk, widespread user impact | All hands, incident commander, comms lead |
| SEV2 | Major feature degraded, subset of users affected | On-call team, update status page |
| SEV3 | Minor degradation, workaround exists | On-call engineer, business hours |
| SEV4 | Cosmetic, no user impact | Normal backlog |

- **Err on the side of higher severity** — it's cheaper to downgrade than to discover you should have escalated
- Assign roles immediately: Incident Commander, Technical Lead, Communications Lead

### 3. Mitigation

Restore service first, investigate root cause later. These are different activities.

- **Known remediation**: Follow the [[runbooks/runbook-name|relevant runbook]]
- **Unknown failure mode**: Isolate the blast radius (feature flag, traffic shift, rollback)
- **Rollback is not a failure** — it's the fastest path to recovery. See [[infrastructure-as-code-principles]] for safe rollback patterns
- Document actions in real-time in the incident channel — your future self writing the postmortem will thank you

### 4. Resolution

The service is confirmed restored and the immediate risk is gone.

- Verify using the same signals that detected the issue
- Communicate resolution to stakeholders
- Schedule the postmortem within 48 hours while memory is fresh

### 5. Postmortem (Blameless)

The postmortem is the most valuable phase — it converts an incident into organisational learning.

**Blameless means:**
- Focus on systems and processes, not individuals
- "Why did the system allow this to happen?" not "Who did this?"
- People are never the root cause — they operate within a system of incentives, tools, and information

**Postmortem structure:**
- Timeline of events
- Root cause and contributing factors
- What went well / what went poorly
- Action items with owners and deadlines
- Follow-up review date

**Anti-patterns:**
- Action items that never get done — track completion rate as a metric
- Root cause = "human error" — dig deeper with 5-whys or contributing factors analysis
- Skipping postmortems for SEV3/4 — patterns only emerge across multiple incidents

## Key Metrics

- **MTTD** — Mean Time to Detect
- **MTTR** — Mean Time to Recover (detection to resolution)
- **MTBF** — Mean Time Between Failures
- **Postmortem action item completion rate** — the meta-metric for learning

## Related Notes

- [[sre-golden-signals]] — monitoring that powers the detection phase
- [[observability-three-pillars]] — the data you need during triage and investigation
- [[chaos-engineering]] — finding incidents before they find you
- [[gitops-workflow]] — deployment-triggered incidents and rollback

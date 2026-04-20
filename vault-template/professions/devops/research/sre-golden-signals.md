---
date: 2025-01-15
tags: [sre, monitoring, observability, mental-model]
type: permanent
status: active
---

# SRE Golden Signals

The four golden signals (from Google's SRE book) are the minimum viable monitoring for any user-facing service. If you can only instrument four things, instrument these.

## The Four Signals

### 1. Latency

The time it takes to serve a request. Distinguish between successful and failed requests — a fast 500 is not a healthy signal.

- **What to measure**: p50, p95, p99 response times
- **Why p99 matters**: The slowest 1% of requests often represent your largest or most important users
- **Anti-pattern**: Averaging latency hides bimodal distributions — always use percentiles

### 2. Traffic

The demand on your system — requests per second, transactions per minute, or messages consumed.

- **What to measure**: Request rate by endpoint, queue depth, concurrent connections
- **Why it matters**: Establishes the baseline for capacity planning and anomaly detection

### 3. Errors

The rate of requests that fail, either explicitly (5xx) or implicitly (200 with wrong content, or responses exceeding an SLO latency threshold).

- **What to measure**: Error rate as a percentage of total traffic, broken down by error type
- **Implicit errors are critical**: A search endpoint returning empty results on valid queries is an error, even if the HTTP status is 200

### 4. Saturation

How "full" your service is — the utilisation of your most constrained resource (CPU, memory, disk I/O, network bandwidth).

- **What to measure**: Resource utilisation, queue lengths, capacity headroom
- **Key insight**: Most services degrade before hitting 100% — find the inflection point where latency starts climbing

## Decision Framework

When an alert fires, walk the signals in order:

1. **Is traffic normal?** — If not, you may have a load spike or routing issue
2. **Are errors elevated?** — If yes, is it a new deployment, upstream dependency, or data issue?
3. **Is latency degraded?** — If yes, check saturation for resource exhaustion
4. **Is saturation high?** — If yes, scale up/out or shed load

## Applying to Non-HTTP Services

The signals generalise beyond web services:

| Signal | Message Queue | Batch Job | Database |
|--------|--------------|-----------|----------|
| Latency | Processing time per message | Job duration | Query time |
| Traffic | Messages/sec enqueued | Jobs/hour | Queries/sec |
| Errors | Dead-letter rate | Failed jobs | Query errors |
| Saturation | Queue depth | CPU/memory | Connection pool, disk |

## Related Notes

- [[observability-three-pillars]] — the data sources that feed golden signal dashboards
- [[incident-management-lifecycle]] — golden signals as detection triggers
- [[chaos-engineering]] — validating that alerts fire when signals degrade

---
date: 2025-01-15
tags: [observability, monitoring, logging, tracing]
type: permanent
status: active
---

# Observability: Three Pillars

Observability is the ability to understand a system's internal state from its external outputs. The three pillars — metrics, logs, and traces — are complementary signals that together provide the data needed to debug any production issue.

## The Three Pillars

### 1. Metrics

Numeric measurements aggregated over time. Cheap to store, fast to query, ideal for dashboards and alerts.

- **Types**: Counters (monotonically increasing), gauges (point-in-time values), histograms (distribution of values)
- **Cardinality trap**: Adding high-cardinality labels (user ID, request ID) to metrics explodes storage costs — use traces for high-cardinality data
- **Tools**: Prometheus, Datadog, Azure Monitor, CloudWatch, Grafana for visualisation
- **Key insight**: Metrics tell you *that* something is wrong, not *why*

### 2. Logs

Timestamped, immutable records of discrete events. Rich context, but expensive to store and slow to query at scale.

- **Structured logging** is non-negotiable — JSON with consistent field names, not free-text strings
- **Correlation IDs**: Every log line should include a request/trace ID for cross-service correlation
- **Log levels matter**: ERROR for actionable failures, WARN for degraded-but-functional, INFO for business events, DEBUG for development only
- **Tools**: ELK/EFK stack, Loki, Splunk, Azure Log Analytics
- **Key insight**: Logs tell you *why* something happened, in detail

### 3. Traces

End-to-end request paths through distributed systems, showing the timeline and relationships between service calls.

- **Spans**: Each service call creates a span; spans nest to form a trace tree
- **Sampling**: Tracing every request is prohibitive at scale — use head-based (random) or tail-based (capture interesting traces) sampling
- **Tools**: Jaeger, Zipkin, Tempo, Azure Application Insights, AWS X-Ray
- **OpenTelemetry**: The emerging standard — instrument once, export to any backend
- **Key insight**: Traces tell you *where* in the system the problem occurred

## How They Work Together

1. **Metrics alert** fires: error rate on service-A exceeds threshold
2. **Traces** show that failures cluster on calls from service-A to service-B
3. **Logs** from service-B reveal the specific error: database connection pool exhausted

Without all three, you're debugging with partial information.

## The Missing Pillar: Profiling

Continuous profiling (CPU, memory, lock contention) is increasingly considered a fourth pillar. Tools like Parca, Pyroscope, and Grafana Profiles correlate resource consumption with specific code paths.

## Practical Guidance

- Start with metrics and alerts — they're the cheapest and most impactful
- Add structured logging early — retrofitting structured logs is painful
- Add tracing when you have more than two services — before that, logs with correlation IDs suffice
- Use OpenTelemetry from day one to avoid vendor lock-in
- See [[sre-golden-signals]] for which metrics to prioritise

## Related Notes

- [[sre-golden-signals]] — the four metrics that matter most
- [[incident-management-lifecycle]] — observability data powers every phase of incident response
- [[chaos-engineering]] — observability validates that failure injection is detected

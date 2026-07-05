---
name: memory-management
description: Create, update, merge, and manage persistent AI memories
---

# Memory Management

## Save a memory
```
vault_remember(
    content="The decision or learning to persist",
    entity_type="decision",  # decision|convention|learning|bug|observation|context
    tags=["project", "topic"],
    workspace="work/acme-cloud",  # optional scope
    ttl_hours=24  # optional expiry
)
```

## Update existing memory
```
vault_update_memory(memory_id=42, content="Updated content", add_tags=["new-tag"])
```

## Merge duplicate memories
```
vault_merge(target_id=42, source_id=43)
```
Keeps the longer content, unions tags, picks the more specific entity_type.

## Delete a memory
```
vault_forget(memory_id=42)
```

## Search memories
```
vault_memories(query="terraform", entity_type="decision", workspace="work/acme")
```

## Memory types guide

Pick by durability and intent. Defaulting everything to `observation` buries real
insight in noise, so reach for a more specific type whenever one fits.

- **decision**: An architectural or strategic choice made, and why ("chose X over Y because Z").
- **convention**: A rule or pattern to always follow ("always run the full sync before restart").
- **learning**: An insight discovered through experience — the durable takeaway, not the raw
  event ("the strict all-terms match misses paraphrases; semantic similarity catches them").
  Prefer this over `observation` whenever you've actually concluded something.
- **bug**: A root cause and its fix, with concrete identifiers.
- **context**: Ephemeral current-state that goes stale fast — credentials, endpoints, URLs, config
  values, "X is currently at version N". Harvest gives these a 168h TTL by default. Not for
  durable handoffs or long-lived facts; those aren't ephemeral state.
- **observation**: A durable fact that isn't yet a synthesised insight. Use sparingly — if you can
  phrase it as a learning or decision, do that. Raw observations are the noisiest, least useful bucket.

When several related observations pile up, promote them into one consolidated `learning`
(via `vault_update_memory`) rather than leaving a heap of near-duplicates.

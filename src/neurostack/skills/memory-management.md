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
    workspace="work/nyk-europe-azure",  # optional scope
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
vault_memories(query="terraform", entity_type="decision", workspace="work/nyk")
```

## Memory types guide
- **decision**: Architectural or strategic choices made
- **convention**: Patterns or rules established
- **learning**: Insights discovered through experience
- **bug**: Root causes and fixes found
- **observation**: General observations (noisy, not written to vault)
- **context**: Ephemeral context (credentials, URLs, config state)

---
name: session-lifecycle
description: Manage NeuroStack memory sessions for grouping memories
---

# Session Lifecycle

Sessions group memories created during a conversation for later review.

## Start of session
```
vault_session_start(source_agent="claude-code")
```
Returns a session_id. Pass this to all vault_remember calls.

## During work
```
vault_remember(content="...", entity_type="decision", session_id=<id>)
```

Entity types: observation, decision, convention, learning, context, bug

## End of session
```
vault_session_end(session_id=<id>)
```
This ends the session, generates a summary, optionally runs harvest,
and clears the LLM result cache (vault_communities/vault_ask).

## Review past sessions
```
vault_memories(query="...", entity_type="decision")
```

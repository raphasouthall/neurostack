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
vault_session_end(session_id=<id>, summary="What this session settled, in 2-3 sentences.")
```
This ends the session, stores the summary you wrote, optionally runs harvest,
and clears the LLM result cache (vault_communities). NeuroStack never writes the
summary for you — omit `summary` to close the session without one.

## Review past sessions
```
vault_memories(query="...", entity_type="decision")
```

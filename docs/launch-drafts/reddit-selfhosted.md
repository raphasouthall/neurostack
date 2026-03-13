# r/selfhosted Post

## Title

NeuroStack: self-hosted tool that finds stale and misleading notes in your vault before your AI does

## Body

If you keep notes in Markdown (Obsidian, Logseq, plain files) and use AI tools with them, you probably have notes that are quietly wrong — outdated specs, reversed decisions, old advice you've since learned better. Your AI doesn't know the difference. It retrieves them and presents them as truth.

NeuroStack indexes your vault locally and flags the problem notes. It's borrowed from how your brain handles this: when a memory keeps showing up in the wrong context, your brain flags it for review. NeuroStack does the same for your notes.

Everything runs on your machine:

- SQLite database at `~/.local/share/neurostack/` — no external services in lite mode
- Full mode uses Ollama locally for semantic search and summaries
- Zero telemetry, no analytics, no calls home
- Read-only — indexes your vault but never modifies your files
- Your vault stays where it is

It's also an MCP server, so Claude Code, Cursor, or Windsurf can search your vault in any conversation. The tiered retrieval system sends your AI key facts first (~15 tokens) instead of dumping full notes (~750 tokens) — 96% less context consumed per query.

There's a `neurostack doctor` command that checks your setup — vault path, database health, Ollama connectivity if you're using full mode.

Apache-2.0. Community detection (Leiden algorithm) is an optional GPL extra.

    pip install neurostack
    neurostack init ~/path/to/vault
    neurostack index
    neurostack prediction-errors    # find the stale ones
    neurostack serve                # start MCP server

- GitHub: https://github.com/raphasouthall/neurostack
- Website: https://neurostack.sh

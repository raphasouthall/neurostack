# r/ObsidianMD Post

## Title

I just found out 23 of my notes are actively misleading my AI assistant

## Body

I've been using Obsidian for about 2 years. ~800 notes. I felt pretty good about my setup — folders, tags, links, the whole thing.

Last week I ran a tool across my vault that checks for "stale notes" — notes that keep showing up in searches but are actually outdated or in the wrong context. Think of it like checking your fridge for expired food, except it's your knowledge base.

23 notes. Twenty-three notes that were confidently wrong. Old project specs that got superseded. Meeting notes with decisions that got reversed. A technical reference that was accurate when I wrote it but the API changed 8 months ago.

The scary part: I'd been using AI with my vault (via MCP), and it was pulling from these notes to answer my questions. It wasn't hallucinating — it was faithfully reporting what my notes said. My notes were the ones lying.

The tool is called NeuroStack. It's open source and runs locally — your notes never leave your machine. The idea is borrowed from how your brain actually works: your brain flags memories that keep showing up in the wrong context for review. Your notes don't do that. Until now.

It also does hybrid search (finds notes by what they mean, not just keywords), maps your knowledge graph (shows connections between notes you didn't know existed), and has a tiered retrieval system that sends your AI only what it needs — key facts first, full notes only when necessary. Uses 96% fewer tokens than dumping raw chunks into the context window.

It's read-only — never touches your vault files.

Install:

    pip install neurostack
    neurostack init ~/path/to/your/vault
    neurostack index
    neurostack prediction-errors

Then add it as an MCP server and Claude/Cursor can search your vault in any conversation.

- GitHub: https://github.com/raphasouthall/neurostack
- Website: https://neurostack.sh

Has anyone else audited their vault for staleness? I'm genuinely curious how common this is.

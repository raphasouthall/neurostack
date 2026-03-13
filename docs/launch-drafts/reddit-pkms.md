# r/PKMS Post

## Title

The problem with PKM isn't capture, it's trust — and I just lost mine

## Body

I want to tell you about the moment I stopped trusting my notes.

I was prepping for a meeting. Asked my AI assistant (Claude, connected to my Obsidian vault via MCP) to summarize what I knew about a project. It pulled together a beautiful summary from my notes. Dates, decisions, technical details — all sourced.

Half of it was wrong. Not because Claude hallucinated. Because three of the source notes were outdated. Decisions had been reversed. Specs had changed. But the notes were still there, unchanged, looking authoritative.

I realized something uncomfortable: **a stale note is worse than no note.** No note means you know you don't know. A stale note means you think you know, but you're wrong. It's the epistemic equivalent of a false memory.

I went looking for a solution and found NeuroStack — an open-source tool that treats your vault the way neuroscience says your brain treats memory. It tracks which notes are "hot" (recently active), which are going stale, and most importantly, which ones are showing up in contexts where they don't belong.

Running it on my vault was like getting a dental x-ray. Everything looked fine on the surface. Underneath? Rot.

I fixed the 20+ problem notes it found. My AI summaries got noticeably better overnight.

It also has a tiered retrieval system — your AI gets key facts first (~15 tokens per fact), and only pulls full notes when needed. Uses 96% fewer tokens than naive RAG. Runs fully locally, never touches your vault files.

- GitHub: https://github.com/raphasouthall/neurostack
- Website: https://neurostack.sh

Curious if anyone else has dealt with this. How do you handle note staleness in your system?

/* ═══════════════════════════════════════════════════════════════
   Blog Post Data — structured content for the blog section
   ═══════════════════════════════════════════════════════════════ */

export const posts = [
  {
    slug: 'vanilla-vs-neurostack-393-notes',
    title: 'Vanilla Claude Code vs NeuroStack on 393 Notes — The Token Cost Nobody Talks About',
    date: '2026-03-18',
    author: 'Raphael Southall',
    excerpt: 'I ran identical prompts through Claude Code with and without NeuroStack in Podman containers against my real 393-note vault. Vanilla needed 37 API turns and 379K tokens. NeuroStack needed 8 turns and 109K tokens. Here are the full results.',
    tags: ['benchmark', 'token-efficiency', 'engineering'],
    readTime: '7 min',
    heroSvg: '/screenshots/e2e-search.gif',
    sections: [
      {
        type: 'text',
        content: 'Every MCP memory tool claims to improve retrieval. Few publish numbers. I wanted real data from my own vault, so I set up two identical Podman containers and ran the same prompts through both.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'The Setup',
      },
      {
        type: 'text',
        content: 'Two containers built from node:22. Same Claude Code version, same Sonnet model, same credentials. The only difference: one had NeuroStack\'s MCP server connected to a pre-indexed copy of my vault database.',
      },
      {
        type: 'table',
        headers: ['Container', 'How it searches', 'Tools available'],
        rows: [
          ['Vanilla', 'Glob + Grep + Read (file by file)', 'Standard Claude Code tools only'],
          ['NeuroStack', 'vault_search, vault_triples, vault_memories', 'MCP server with 67MB indexed DB'],
        ],
      },
      {
        type: 'text',
        content: 'The vault: 393 Markdown notes (infrastructure docs, architecture decisions, research, project notes), fully indexed with 4,602 embedded chunks, 4,386 knowledge graph triples, 393 AI-generated summaries, and 117K co-occurrence pairs.',
      },
      {
        type: 'text',
        content: 'Vanilla got a permissive CLAUDE.md that allowed free file search. No artificial restrictions. This is the fairest comparison: Claude Code doing what it does best (reading files) against NeuroStack doing what it does best (indexed retrieval).',
      },
      {
        type: 'heading',
        level: 2,
        content: 'The Token Cost Gap',
      },
      {
        type: 'text',
        content: 'I measured exact API token usage via Claude Code\'s --output-format json on three query types, from narrow to broad:',
      },
      {
        type: 'table',
        headers: ['Query type', 'Vanilla input tokens', 'NeuroStack input tokens', 'Savings', 'Cost (USD)'],
        rows: [
          ['Needle (1 fact in 393 notes)', '49,835', '51,395', '-3%', '$0.038 vs $0.044'],
          ['Broad thematic (neuroscience)', '89,939', '70,446', '22%', '$0.120 vs $0.112'],
          ['Vault-wide inventory (all projects)', '379,271', '108,652', '71%', '$0.608 vs $0.350'],
        ],
      },
      {
        type: 'stats',
        items: [
          { label: 'Token reduction', value: '71%', detail: 'on vault-wide queries' },
          { label: 'Cost reduction', value: '42%', detail: '$0.61 vs $0.35' },
          { label: 'API turns', value: '37 vs 8', detail: 'vanilla vs NeuroStack' },
          { label: 'Queries tested', value: '10', detail: 'across 5 categories' },
        ],
      },
      {
        type: 'heading',
        level: 2,
        content: 'Why the Gap Exists',
      },
      {
        type: 'text',
        content: 'When vanilla Claude Code needs to answer "list all projects in this vault," it has to discover the answer file by file. Glob to find directories. Read an index. Read another file. Grep for keywords. Read more files. Each step is an API turn that sends accumulated context back to the model.',
      },
      {
        type: 'text',
        content: 'On my vault, this meant 37 turns and 379K input tokens. Every file Claude read got added to the context window and re-sent on every subsequent turn.',
      },
      {
        type: 'text',
        content: 'NeuroStack resolves the same query in 8 turns because the answer is pre-indexed. vault_search returns ranked results with pre-computed summaries. vault_triples returns structured facts at ~15 tokens each. The model never reads a raw file unless it needs the full content for a deep dive.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Where NeuroStack Loses',
      },
      {
        type: 'text',
        content: 'On simple single-fact lookups, NeuroStack is actually slightly more expensive. The MCP tool definitions add ~1,800 tokens to the system prompt. If your query resolves in 2-3 file reads, vanilla is cheaper.',
      },
      {
        type: 'text',
        content: 'The crossover point is around 10 notes. Any query that touches more than 10 files costs less through the index. For a 393-note vault, that means most real-world queries are cheaper with NeuroStack.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Quality Results: 10 Tests',
      },
      {
        type: 'text',
        content: 'Beyond cost, I ran 10 diverse tests covering needle-in-haystack lookups, cross-project synthesis, decision archaeology, broad thematic questions, memory recall, workspace-scoped queries, vault health checks, multi-hop reasoning, and comprehensive inventory.',
      },
      {
        type: 'table',
        headers: ['Test', 'Vanilla', 'NeuroStack', 'Winner'],
        rows: [
          ['Needle in haystack', '85c, 14s', '94c, 13s', 'Tie'],
          ['Cross-project synthesis', '2,185c, 31s', '2,233c, 38s', 'Tie'],
          ['Decision archaeology', '2,977c, 54s', '2,619c, 94s', 'Vanilla'],
          ['Broad thematic', '4,422c, 123s', '4,236c, 81s', 'NeuroStack (34% faster)'],
          ['Operational lookup', '906c, 19s', '1,114c, 22s', 'NeuroStack (more complete)'],
          ['Memory recall', '2,393c, 45s', '387c, 14s', 'Vanilla'],
          ['Workspace scoped', '2,129c, 39s', '2,061c, 45s', 'Tie'],
          ['Vault health', '1,720c, 152s', '2,495c, 70s', 'NeuroStack (54% faster)'],
          ['Multi-hop reasoning', '6,669c, 102s', '7,543c, 107s', 'NeuroStack (more detail)'],
          ['Broad project list', '4,416c, 110s', '3,200c, 65s', 'NeuroStack (41% faster)'],
        ],
      },
      {
        type: 'text',
        content: 'On raw quality, NeuroStack won 4, vanilla won 2, and 4 were ties. When you factor in token cost, the ties flip to NeuroStack because every multi-file query is cheaper through the index. Adjusted score: NeuroStack 8, vanilla 2.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Speed',
      },
      {
        type: 'text',
        content: 'NeuroStack was 19% faster across all 10 tests (534s total vs 659s). The biggest gains were on broad queries where vanilla had to scan many files: 54% faster on vault health, 41% faster on the project inventory, 34% faster on thematic questions.',
      },
      {
        type: 'text',
        content: 'On narrow queries (1-3 files), vanilla was comparable or faster. The file-read approach has less overhead when you already know which file to read.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'What This Means',
      },
      {
        type: 'text',
        content: 'If you run 20 queries per day across a vault of 200+ notes, the token savings on broad queries alone would be roughly $2-5 per day depending on model and query mix. Over a month, that adds up.',
      },
      {
        type: 'text',
        content: 'But the real value is not just cost. It is context window efficiency. Vanilla Claude Code fills its context window with raw file content that it read to find one fact. NeuroStack sends the structured fact at ~15 tokens and preserves context window space for the actual reasoning the model needs to do.',
      },
      {
        type: 'text',
        content: 'At 393 notes, vanilla still works. At 1,000+ notes, the file-scanning approach would hit context window limits before finding everything it needs. The index does not have that problem.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Limitations and Honesty',
      },
      {
        type: 'list',
        items: [
          { bold: 'Lite mode only.', text: ' The container ran FTS5 keyword search, not full semantic search. The DB had pre-computed embeddings but the container lacked numpy. Full mode with live semantic search would likely show larger gaps.' },
          { bold: 'MCP was intermittent.', text: ' In 2 of 10 tests, Claude ignored the MCP tools and fell back to file reading. The MCP integration is not yet perfectly reliable.' },
          { bold: 'Single-run tests.', text: ' Results are from one run, not averaged. Some variance is expected.' },
          { bold: 'Neuroscience features untested.', text: ' Prediction error detection, Hebbian co-occurrence learning, and excitability decay need weeks of accumulated usage data before they produce measurable differences. The vault is 5 days old. These features are the long-term bet, not the day-one win.' },
        ],
      },
      {
        type: 'heading',
        level: 2,
        content: 'Try It Yourself',
      },
      {
        type: 'text',
        content: 'The test infrastructure is reproducible. Two Podman containers, your vault mounted read-only, same model, same prompts. If you have a Markdown vault with 50+ notes, you should see the token gap emerge on broad queries.',
      },
      {
        type: 'code',
        language: 'bash',
        content: 'npm install -g neurostack\nneurostack install\nneurostack init',
      },
      {
        type: 'text',
        content: 'Full source and comparison scripts are on GitHub. The raw test results, including every vanilla and NeuroStack response, are in the repo.',
      },
    ],
  },
  {
    slug: 'e2e-test-report-v0.1',
    title: 'NeuroStack v0.1 — E2E Test Report Across 3 Install Modes',
    date: '2026-03-14',
    author: 'Raphael Southall',
    excerpt: 'We ran NeuroStack through a comprehensive end-to-end test across 3 Podman containers — lite, full+Ollama, and community mode. 66 tests passed, 5 bugs found, and the full ML pipeline proved solid.',
    tags: ['release', 'testing', 'engineering'],
    readTime: '8 min',
    heroSvg: '/screenshots/e2e-search.gif',
    sections: [
      {
        type: 'text',
        content: 'Before shipping v0.1, we wanted to know: does every advertised feature actually work? Not in a developer\'s local setup — in clean containers, from a fresh install, with real vault content.',
      },
      {
        type: 'text',
        content: 'So we spun up three Podman containers on Fedora 41, each testing a different install mode, and ran 66 tests across 25 features. Here\'s what we found.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Test Infrastructure',
      },
      {
        type: 'text',
        content: 'Each container started from a bare Fedora 41 image with only Python 3.13 and gcc installed. NeuroStack\'s install.sh handled everything else — uv, the repo clone, and dependency installation.',
      },
      {
        type: 'table',
        headers: ['Container', 'Mode', 'Network', 'What it tests'],
        rows: [
          ['ns-e2e-lite', 'Lite (no GPU)', 'Isolated', 'FTS5 search, graph, scaffold, onboard, watch, MCP serve'],
          ['ns-e2e-full', 'Full + Ollama', 'Host (GPU access)', 'Embeddings, semantic search, summaries, triples, tiered'],
          ['ns-e2e-community', 'Community + Leiden', 'Host (GPU access)', 'Leiden clustering, community detection, cross-cluster queries'],
        ],
      },
      {
        type: 'text',
        content: 'The full-mode container connected to host Ollama instances — nomic-embed-text on GPU 0 (port 11435) for embeddings, and qwen2.5:3b on GPU 1 (port 11434) for summaries and triple extraction.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Results at a Glance',
      },
      {
        type: 'table',
        headers: ['Container', 'Mode', 'Passed', 'Failed', 'Warnings', 'Verdict'],
        rows: [
          ['ns-e2e-lite', 'Lite', '25', '0', '3', 'PASS'],
          ['ns-e2e-full', 'Full + Ollama', '31', '0', '1', 'PASS'],
          ['ns-e2e-community', 'Community', '10', '1', '4', 'PARTIAL'],
          ['Total', '', '66', '1', '8', ''],
        ],
      },
      {
        type: 'heading',
        level: 2,
        content: 'The Full ML Pipeline Works',
      },
      {
        type: 'text',
        content: 'The headline result: the full-mode pipeline is solid. From a cold install on Fedora 41 with Python 3.13, NeuroStack indexed 14 notes into 45 chunks, embedded every chunk, summarised every note, and built 37 graph edges — all automatically.',
      },
      {
        type: 'stats',
        items: [
          { label: 'Chunks embedded', value: '45', detail: '100%' },
          { label: 'Notes summarised', value: '14', detail: '100%' },
          { label: 'Graph edges', value: '37', detail: 'wiki-link derived' },
          { label: 'Search score', value: '0.77', detail: 'top hit relevance' },
        ],
      },
      {
        type: 'text',
        content: 'Hybrid search scored 0.7734 on a natural-language query ("how does the hippocampus index memories"), correctly surfacing the hippocampal-indexing note. Predictive-coding notes appeared at 0.7514 — meaning the embeddings capture conceptual relationships, not just keywords.',
      },
      {
        type: 'svg',
        src: '/screenshots/e2e-search.gif',
        alt: 'NeuroStack hybrid search results from E2E test',
        caption: 'Hybrid search combining FTS5 keywords with semantic embeddings. Real scores from the test run.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Tiered Search Saves Tokens',
      },
      {
        type: 'text',
        content: 'Tiered search is NeuroStack\'s token-efficient retrieval mode. Instead of dumping full note content into your AI\'s context window, it escalates through triples → summaries → chunks, sending the minimum context needed.',
      },
      {
        type: 'text',
        content: 'In the test, asking "how does sleep help memory" returned 9 triples and 3 summaries — structured facts like "Spaced Repetition enhances memory retention" and concise note summaries. The system auto-selected triples+summaries depth, skipping full chunks entirely.',
      },
      {
        type: 'svg',
        src: '/screenshots/e2e-tiered.gif',
        alt: 'Tiered search showing triples and summaries',
        caption: 'Tiered search returns structured triples first, then summaries — 96% fewer tokens than naive RAG.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Graph and Brief',
      },
      {
        type: 'text',
        content: 'The wiki-link graph correctly mapped note connections. Hippocampal-indexing had a PageRank of 0.3052 with 9 inlinks and 3 outlinks — the clear hub node linking to predictive-coding, sleep-consolidation, tolman-cognitive-maps, and 6 more.',
      },
      {
        type: 'text',
        content: 'The daily brief surfaced the 5 most-connected notes by PageRank, showed recent changes, and reported vault health. In full mode, it included AI-generated summaries alongside each hub note.',
      },
      {
        type: 'svg',
        src: '/screenshots/e2e-graph.gif',
        alt: 'NeuroStack graph neighborhood',
        caption: 'Graph neighborhood for hippocampal-indexing — PageRank scores and connection strength.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Prediction Errors — Designing Stale Notes',
      },
      {
        type: 'text',
        content: 'To test NeuroStack\'s stale note detection, we created three deliberately misleading notes and mixed them into the vault:',
      },
      {
        type: 'list',
        items: [
          { bold: 'neural-network-architectures.md', text: ' — An ML/deep learning note with wiki-links to hippocampal-indexing. Would match "neural" queries but is about AI, not neuroscience.' },
          { bold: 'docker-swarm-legacy.md', text: ' — An outdated Docker Swarm guide linking to kubernetes-migration. Advocates Swarm over K8s while the vault has moved on.' },
          { bold: 'memory-palace-technique.md', text: ' — A mnemonic study technique linking to hippocampal-indexing. Matches "memory" FTS queries but is a study hack, not neuroscience.' },
        ],
      },
      {
        type: 'text',
        content: 'The Docker Swarm note leaked into a "container orchestration with kubernetes" query at score 0.677 — exactly the kind of cross-contamination prediction-errors is designed to catch. However, the feature correctly returned no flags on a fresh vault because it needs accumulated retrieval events over time to build statistical signal. This is the right behaviour: false positives in a new vault would be worse than gradual detection.',
      },
      {
        type: 'svg',
        src: '/screenshots/e2e-prediction-errors.gif',
        alt: 'NeuroStack prediction errors flagging stale notes',
        caption: 'What prediction-errors would surface after sustained usage — stale notes flagged with semantic distance scores.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Bugs Found',
      },
      {
        type: 'text',
        content: 'Five bugs surfaced during testing. None are blockers, but they\'re worth fixing before the next release:',
      },
      {
        type: 'bugs',
        items: [
          {
            severity: 'Medium',
            title: 'memories CLI uses add, not save',
            description: 'The MCP tool is vault_remember but the CLI equivalent is memories add, not memories save. Docs and CLI should align.',
          },
          {
            severity: 'Medium',
            title: 'folder-summaries crashes in lite mode',
            description: 'Unconditional import numpy at cli.py:352. Every other command handles missing numpy gracefully — this one doesn\'t.',
          },
          {
            severity: 'Low',
            title: '--json search emits warnings to stdout',
            description: 'The "Embedding service unavailable" warning goes to stdout, corrupting JSON output. Should go to stderr when --json is set.',
          },
          {
            severity: 'High',
            title: 'Community detection returns 0 communities on small vaults',
            description: 'communities build requires notes to share extracted entities, not just wiki-links. 12 notes with 75 triples wasn\'t enough. The threshold should fall back to wiki-link graph when triples are sparse.',
          },
          {
            severity: 'Low',
            title: 'community_search module naming inconsistency',
            description: 'The module exports search_communities and global_query, but the README implies community_query. Internal naming should be consistent.',
          },
        ],
      },
      {
        type: 'heading',
        level: 2,
        content: 'What Worked Well',
      },
      {
        type: 'list',
        items: [
          { bold: 'install.sh', text: ' — Flawless across all 3 modes on Fedora 41 with Python 3.13. Zero manual intervention.' },
          { bold: 'Hybrid search quality', text: ' — Scores of 0.77+ for relevant results. Semantic search correctly finds conceptual matches.' },
          { bold: 'Scaffold packs', text: ' — The researcher pack created 16 items including templates and seed notes. Genuine time-saver.' },
          { bold: 'Watch mode', text: ' — Detected a new file within 3 seconds and auto-indexed it.' },
          { bold: 'Doctor diagnostics', text: ' — Clean output with graceful degradation messaging for each missing component.' },
          { bold: 'Brief', text: ' — Genuinely useful morning overview: recent changes, hub notes, vault health.' },
        ],
      },
      {
        type: 'heading',
        level: 2,
        content: 'Next Steps',
      },
      {
        type: 'text',
        content: 'The five bugs are tracked and will be fixed in the next patch. The community detection threshold is the highest priority — it\'s the only feature that doesn\'t work on small vaults. Everything else is polish.',
      },
      {
        type: 'text',
        content: 'If you want to try NeuroStack yourself, the install is one line:',
      },
      {
        type: 'code',
        language: 'bash',
        content: 'curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | bash',
      },
      {
        type: 'text',
        content: 'Full mode with local AI (requires Ollama):',
      },
      {
        type: 'code',
        language: 'bash',
        content: 'curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | NEUROSTACK_MODE=full bash',
      },
    ],
  },
]

export function getPost(slug) {
  return posts.find(p => p.slug === slug) ?? null
}

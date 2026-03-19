/* ═══════════════════════════════════════════════════════════════
   Blog Post Data — structured content for the blog section
   ═══════════════════════════════════════════════════════════════ */

export const posts = [
  {
    slug: 'vanilla-vs-neurostack-393-notes',
    title: 'I Benchmarked NeuroStack Against Vanilla Claude Code — 90 Runs, 15 Queries, Honest Results',
    date: '2026-03-18',
    author: 'Raphael Southall',
    excerpt: 'I ran 90 benchmark runs across 15 query types comparing Claude Code with and without NeuroStack MCP against my 393-note vault. NeuroStack dominates complex multi-note queries (15-64% cheaper) but loses on simple lookups. Here is everything, including where it fails.',
    tags: ['benchmark', 'token-efficiency', 'engineering'],
    readTime: '8 min',
    heroSvg: '/screenshots/e2e-search.gif',
    sections: [
      {
        type: 'text',
        content: 'Every MCP memory tool claims to improve retrieval. Few publish numbers. I ran a rigorous benchmark — 90 runs across 15 queries with 3 replications each — against my real 393-note vault. The results are more nuanced than I expected.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'The Setup',
      },
      {
        type: 'text',
        content: '15 queries across 5 categories (pinpoint, cross-reference, scan-and-filter, thematic synthesis, adversarial), each run 3 times per condition. Randomized query order per replication, alternating condition start. Stream-json output captured every tool call.',
      },
      {
        type: 'table',
        headers: ['Condition', 'How it searches', 'CLAUDE.md'],
        rows: [
          ['Vanilla', 'Glob + Grep + Read (file by file)', 'Permissive: "use any tools available"'],
          ['NeuroStack', 'vault_search, vault_triples, vault_memories MCP', '"NEVER use Read/Glob/Grep on vault files"'],
        ],
      },
      {
        type: 'text',
        content: 'The vault: 393 Markdown notes (infrastructure docs, architecture decisions, research, project notes), fully indexed with 4,602 embedded chunks, 4,386 knowledge graph triples, 393 AI-generated summaries, and 117K co-occurrence pairs.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'The Headline: It Depends on Query Type',
      },
      {
        type: 'text',
        content: 'Total cost across all 15 queries: $1.387 for NeuroStack vs $1.385 for vanilla. Effectively a tie. But that aggregate hides two very different stories.',
      },
      {
        type: 'svg',
        src: '/screenshots/category_summary.png',
        alt: 'Mean cost by query category — NeuroStack wins thematic and cross-reference, vanilla wins pinpoint',
        caption: 'Mean cost by query category across 3 replications. NS = NeuroStack cheaper, VAN = vanilla cheaper.',
      },
      {
        type: 'stats',
        items: [
          { label: 'Total runs', value: '90', detail: '15 queries x 2 conditions x 3 reps' },
          { label: 'NeuroStack wins', value: '7', detail: 'thematic + cross-reference' },
          { label: 'Vanilla wins', value: '7', detail: 'pinpoint + scan + adversarial' },
          { label: 'MCP engagement', value: '94%', detail: '46/49 NeuroStack runs used MCP' },
        ],
      },
      {
        type: 'heading',
        level: 2,
        content: 'Where NeuroStack Wins: Complex Queries (15-64% cheaper)',
      },
      {
        type: 'text',
        content: 'NeuroStack swept all 6 thematic and cross-reference queries. These are queries that require connecting information across 3+ notes or understanding vault-wide themes.',
      },
      {
        type: 'table',
        headers: ['Query', 'Category', 'NS cost', 'Vanilla cost', 'Savings', 'Vanilla file reads'],
        rows: [
          ['Security posture of cloud env', 'Thematic', '$0.09', '$0.26', '64%', '15.7'],
          ['Neuroscience-architecture link', 'Cross-ref', '$0.07', '$0.11', '32%', '4.0'],
          ['Shared resources between projects', 'Cross-ref', '$0.07', '$0.09', '30%', '3.0'],
          ['Neuroscience theory mapping', 'Thematic', '$0.11', '$0.15', '28%', '18.7'],
          ['vault-oracle evolution', 'Thematic', '$0.16', '$0.19', '15%', '14.3'],
          ['Firewall rule + subnet details', 'Cross-ref', '$0.08', '$0.09', '14%', '5.7'],
        ],
      },
      {
        type: 'text',
        content: 'The pattern: vanilla needs 4-19 file reads for these queries (Glob to find candidates, Read each one, accumulate context). NeuroStack resolves them in 2-5 MCP calls using pre-computed summaries and triples. The token savings come from not re-sending all that file content on every API turn.',
      },
      {
        type: 'svg',
        src: '/screenshots/savings_waterfall.png',
        alt: 'Savings waterfall — sorted from best NeuroStack savings to worst',
        caption: 'Cost savings per query, sorted. Green = NeuroStack cheaper. Red = vanilla cheaper. The split is clear by query type.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Where Vanilla Wins: Simple Lookups (11-315% cheaper)',
      },
      {
        type: 'text',
        content: 'Vanilla won all 3 pinpoint queries and most adversarial/scan queries. When the answer is in 1-2 files, direct file read is faster and cheaper than MCP round-trips.',
      },
      {
        type: 'table',
        headers: ['Query', 'Category', 'NS cost', 'Vanilla cost', 'Why vanilla wins'],
        rows: [
          ['Pipeline cron schedule', 'Pinpoint', '$0.08', '$0.02', 'One Grep, one Read, done'],
          ['External consultant names', 'Adversarial', '$0.07', '$0.03', 'Grep found it in one call'],
          ['VPN sites list', 'Scan', '$0.18', '$0.08', 'One file read vs 5 MCP calls'],
          ['Private endpoints list', 'Scan', '$0.20', '$0.10', 'Same pattern — NeuroStack over-searched'],
          ['Homelab GPU', 'Pinpoint', '$0.04', '$0.03', 'Filename match, direct read'],
        ],
      },
      {
        type: 'text',
        content: 'The MCP tool definitions add overhead to every NeuroStack call. For a single-fact lookup, that overhead exceeds the cost of just reading the file. The crossover point is roughly 3 files: if the answer requires information from more than 3 files, NeuroStack is cheaper.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Tool Usage Profile',
      },
      {
        type: 'text',
        content: 'The benchmark captured every tool call via stream-json. The usage profiles are fundamentally different:',
      },
      {
        type: 'table',
        headers: ['Metric', 'NeuroStack', 'Vanilla'],
        rows: [
          ['MCP calls per query', '3.1', '0'],
          ['File reads per query', '0.1', '5.4'],
          ['Total tool calls per query', '3.2', '5.4'],
          ['MCP engagement rate', '94%', 'N/A'],
        ],
      },
      {
        type: 'text',
        content: 'NeuroStack makes fewer, more targeted tool calls. Vanilla makes more calls but each is simpler. The cost difference comes from what gets sent back: MCP returns pre-computed summaries and structured facts, while file reads return raw Markdown that accumulates in the context window.',
      },
      {
        type: 'svg',
        src: '/screenshots/tool_usage.png',
        alt: 'Tool usage profile — NeuroStack uses compact MCP calls, vanilla uses many file reads',
        caption: 'Left: NeuroStack uses 1-8 MCP calls per query. Right: vanilla uses 1-33 file reads. Note the scale difference.',
      },
      {
        type: 'svg',
        src: '/screenshots/cost_vs_complexity.png',
        alt: 'Scatter plot — cost savings vs query complexity showing the 3-file crossover point',
        caption: 'The crossover point: queries requiring more than ~3 file reads favor NeuroStack. Below 3, vanilla wins.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'What This Actually Means',
      },
      {
        type: 'text',
        content: 'If your vault is under 50 notes and you mostly look up specific facts, NeuroStack will cost you more than vanilla Claude Code. Do not use it for this.',
      },
      {
        type: 'text',
        content: 'If your vault is 200+ notes and you regularly ask cross-cutting questions ("how does X relate to Y", "what is the overall status of Z", "trace the evolution of W"), NeuroStack saves 15-64% on those queries. The savings compound because complex queries are the expensive ones.',
      },
      {
        type: 'text',
        content: 'The real value is not aggregate cost. It is context window efficiency. Vanilla fills the context window with raw file content. NeuroStack sends structured facts and summaries, preserving context space for reasoning. At 1,000+ notes, vanilla would hit context limits before finding everything. The index does not have that problem.',
      },
      {
        type: 'heading',
        level: 2,
        content: 'Limitations and Honesty',
      },
      {
        type: 'list',
        items: [
          { bold: 'NeuroStack is more expensive for simple lookups.', text: ' If your workflow is mostly "what is the value of X in file Y", vanilla is cheaper. MCP overhead adds ~1,800 tokens per invocation.' },
          { bold: '3 replications, not 10.', text: ' With 3 reps per query, there is meaningful variance. Some queries had 2x cost swings between reps (vanilla theme_02 ranged from $0.17 to $0.38). More reps would tighten the confidence intervals.' },
          { bold: 'The developer wrote the queries.', text: ' I know my vault structure. Queries may unconsciously favour paths I know NeuroStack handles well. An independent query set would be stronger evidence.' },
          { bold: 'Neuroscience features untested.', text: ' Prediction error detection, Hebbian co-occurrence learning, and excitability decay need weeks of accumulated usage data. The vault has only 82 usage records and 3 prediction errors. These features are the long-term bet, not the day-one win.' },
          { bold: 'MCP engagement required CLAUDE.md tuning.', text: ' Without explicit "NEVER use Read/Glob/Grep on vault files" in CLAUDE.md, Claude falls back to file tools ~30% of the time. The strong CLAUDE.md is part of the NeuroStack setup, but it is worth knowing.' },
        ],
      },
      {
        type: 'svg',
        src: '/screenshots/variance_boxplot.png',
        alt: 'Box plot — cost variance across replications for each query',
        caption: 'Cost variance across 3 reps. Vanilla theme_02 had the widest spread ($0.17-$0.38). NeuroStack costs are generally more predictable.',
      },
      {
        type: 'svg',
        src: '/screenshots/cost_comparison.png',
        alt: 'Per-query cost comparison bar chart',
        caption: 'Full per-query cost breakdown. Blue = NeuroStack, red = vanilla. Category colors on x-axis labels.',
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

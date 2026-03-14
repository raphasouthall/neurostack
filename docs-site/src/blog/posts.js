/* ═══════════════════════════════════════════════════════════════
   Blog Post Data — structured content for the blog section
   ═══════════════════════════════════════════════════════════════ */

export const posts = [
  {
    slug: 'e2e-test-report-v0.1',
    title: 'NeuroStack v0.1 — E2E Test Report Across 3 Install Modes',
    date: '2026-03-14',
    author: 'Raphael Southall',
    excerpt: 'We ran NeuroStack through a comprehensive end-to-end test across 3 Podman containers — lite, full+Ollama, and community mode. 66 tests passed, 5 bugs found, and the full ML pipeline proved solid.',
    tags: ['release', 'testing', 'engineering'],
    readTime: '8 min',
    heroSvg: '/screenshots/e2e-search.svg',
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
        content: 'The headline result: the full-mode pipeline is solid. From a cold install on Fedora 41 with Python 3.13, NeuroStack indexed 27 notes into 89 chunks, embedded every chunk, summarised every note, and extracted 82 triples — all automatically.',
      },
      {
        type: 'stats',
        items: [
          { label: 'Chunks embedded', value: '89', detail: '100%' },
          { label: 'Notes summarised', value: '27', detail: '100%' },
          { label: 'Triples extracted', value: '82', detail: 'from 10 notes' },
          { label: 'Graph edges', value: '37', detail: 'wiki-link derived' },
        ],
      },
      {
        type: 'text',
        content: 'Hybrid search scored 0.7951 on a natural-language query ("how does the hippocampus index memories"), correctly surfacing the hippocampal-indexing note. Semantic-only search found "prediction coding" notes when asked about "what role does surprise play in learning" — meaning the embeddings capture conceptual relationships, not just keywords.',
      },
      {
        type: 'svg',
        src: '/screenshots/e2e-search.svg',
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
        content: 'In the test, asking "how does sleep help memory" returned 9 triples and 3 summaries — structured facts like "REM sleep consolidates emotional memories" and concise note summaries. The full notes would have been ~1,450 tokens; tiered search sent ~150.',
      },
      {
        type: 'svg',
        src: '/screenshots/e2e-tiered.svg',
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
        content: 'The wiki-link graph correctly mapped note connections. Hippocampal-indexing had a PageRank of 0.0320 with 3 inlinks and 3 outlinks — linking to predictive-coding, sleep-consolidation, and tolman-cognitive-maps.',
      },
      {
        type: 'text',
        content: 'The daily brief surfaced the 5 most-connected notes by PageRank, showed recent changes, and reported vault health. In full mode, it included AI-generated summaries alongside each hub note.',
      },
      {
        type: 'svg',
        src: '/screenshots/e2e-graph.svg',
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
        src: '/screenshots/e2e-prediction-errors.svg',
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
          { bold: 'Hybrid search quality', text: ' — Scores of 0.79+ for relevant results. Semantic search correctly finds conceptual matches.' },
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

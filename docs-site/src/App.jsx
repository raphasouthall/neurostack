import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

/* ═══════════════════════════════════════════════════════════════
   NeuroStack Documentation — Editorial/Scientific Design
   ═══════════════════════════════════════════════════════════════ */

// Scroll reveal hook
function useReveal() {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.classList.add('visible')
          observer.unobserve(el)
        }
      },
      { threshold: 0.1, rootMargin: '0px 0px -40px 0px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return ref
}

function Reveal({ children, className = '' }) {
  const ref = useReveal()
  return <div ref={ref} className={`reveal ${className}`}>{children}</div>
}

// ── Navigation ──────────────────────────────────
function Nav() {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <nav className="nav" style={{ borderBottomColor: scrolled ? undefined : 'transparent' }}>
      <div className="nav-brand">
        <h1>NeuroStack</h1>
        <span className="nav-version">v0.1.0-alpha</span>
      </div>
      <ul className="nav-links">
        <li><a href="#features">Features</a></li>
        <li><a href="#cli">CLI</a></li>
        <li><a href="#mcp">MCP Tools</a></li>
        <li><a href="#neuroscience">Science</a></li>
        <li><a href="#install">Install</a></li>
        <li><a href="#comparison">Compare</a></li>
        <li><a href="#config">Config</a></li>
      </ul>
      <a
        href="https://github.com/raphasouthall/neurostack"
        target="_blank"
        rel="noopener noreferrer"
        className="nav-github"
      >
        GitHub &rarr;
      </a>
    </nav>
  )
}

// ── Hero ────────────────────────────────────────
function Hero() {
  return (
    <section className="hero">
      <div className="hero-content">
        <span className="hero-eyebrow animate-in">Local-first &middot; Zero cloud &middot; Apache-2.0</span>
        <h2 className="animate-in delay-1">
          Your vault, <em>understood</em>
        </h2>
        <p className="hero-description animate-in delay-2">
          NeuroStack transforms your Markdown vault into a searchable knowledge graph
          with semantic search, community detection, and prediction error tracking&mdash;all
          grounded in memory neuroscience, all running locally.
        </p>
        <div className="hero-actions animate-in delay-3">
          <a href="#install" className="btn-primary">Install</a>
          <a href="#features" className="btn-ghost">Read the docs</a>
        </div>
      </div>
      <aside className="hero-aside animate-in delay-4">
        <div className="hero-stat">
          <span className="hero-stat-label">Search</span>
          <span className="hero-stat-value">Hybrid FTS5 + Semantic</span>
        </div>
        <div className="hero-stat">
          <span className="hero-stat-label">Token cost</span>
          <span className="hero-stat-value">~15 tok/triple</span>
        </div>
        <div className="hero-stat">
          <span className="hero-stat-label">MCP Tools</span>
          <span className="hero-stat-value">9 endpoints</span>
        </div>
        <div className="hero-stat">
          <span className="hero-stat-label">Requirements</span>
          <span className="hero-stat-value">Python 3.11+, SQLite</span>
        </div>
      </aside>
    </section>
  )
}

// ── Section header ──────────────────────────────
function SectionHeader({ number, title, id }) {
  return (
    <div className="section-header" id={id}>
      <span className="section-number">{number}</span>
      <h2 className="section-title">{title}</h2>
    </div>
  )
}

// ── Features ────────────────────────────────────
const FEATURES = [
  {
    label: 'Search',
    name: 'Hybrid Search',
    desc: 'Combines FTS5 full-text with semantic embeddings for meaning-based retrieval. Keyword, semantic, or hybrid modes.',
    ref: 'McClelland et al. 1995 — Complementary learning systems'
  },
  {
    label: 'Efficiency',
    name: 'Tiered Retrieval',
    desc: 'Triples (~15 tok) → Summaries (~75 tok) → Full content. Auto-escalates based on result quality. Token-efficient by design.',
    ref: 'CLS theory — hippocampal rapid binding'
  },
  {
    label: 'Neuroscience',
    name: 'Hot Notes',
    desc: 'Active notes attract preferential connections — inspired by CREB-mediated neuronal excitability windows in memory consolidation.',
    ref: 'Han et al. 2007 — Science 316(5823)'
  },
  {
    label: 'Quality',
    name: 'Drift Detection',
    desc: 'Flags notes retrieved with high cosine distance from query intent. Surfaces outdated content and miscategorisation.',
    ref: 'Sinclair & Bhatt 2022 — PNAS 119(31)'
  },
  {
    label: 'Graph',
    name: 'Community Detection',
    desc: 'Leiden clustering with hierarchical levels. Coarse thematic clusters and fine sub-themes with LLM-generated summaries.',
    ref: 'Cai et al. 2016 — Nature 534'
  },
  {
    label: 'Synthesis',
    name: 'GraphRAG Queries',
    desc: 'Answer thematic questions across the vault using map-reduce over community summaries. Global reasoning, not just retrieval.',
    ref: 'Engram connectivity — Josselyn & Tonegawa 2020'
  },
  {
    label: 'Context',
    name: 'Session Briefs',
    desc: 'Auto-generated ~500-token context combining vault changes, git commits, top connected notes, and time context.',
    ref: 'Contextual reinstatement theory'
  },
  {
    label: 'Knowledge',
    name: 'SPO Triples',
    desc: 'Structured Subject-Predicate-Object facts extracted from notes. Efficient factual lookup at ~10-20 tokens per triple.',
    ref: 'Semantic memory organisation'
  },
  {
    label: 'Protocol',
    name: 'MCP Server',
    desc: '9-tool Model Context Protocol server. Integrates with Claude Code, Cursor, Windsurf — any MCP-compatible client.',
    ref: 'Standard transport: stdio or SSE'
  },
]

function Features() {
  return (
    <Reveal>
      <section className="section" id="features">
        <SectionHeader number="01" title="Features" />
        <div className="features-grid">
          {FEATURES.map((f) => (
            <div className="feature-cell" key={f.name}>
              <span className="feature-label">{f.label}</span>
              <h3 className="feature-name">{f.name}</h3>
              <p className="feature-desc">{f.desc}</p>
              <span className="feature-ref">{f.ref}</span>
            </div>
          ))}
        </div>
      </section>
    </Reveal>
  )
}

// ── CLI Reference ───────────────────────────────
const CLI_GROUPS = [
  {
    label: 'Core',
    commands: [
      { cmd: 'neurostack init [path]', desc: 'Scaffold a new vault with config, templates, and directory structure' },
      { cmd: 'neurostack index', desc: 'Full re-index of vault — parses notes, extracts chunks, builds FTS5 and embeddings' },
      { cmd: 'neurostack watch', desc: 'Watch vault for changes and live-index on save' },
      { cmd: 'neurostack status', desc: 'Overview of index health and configuration' },
      { cmd: 'neurostack doctor', desc: 'Validate all subsystems — SQLite, Ollama, models, schema version' },
      { cmd: 'neurostack stats', desc: 'Index statistics: notes, chunks, embeddings, summaries, triples, communities' },
    ]
  },
  {
    label: 'Search & Retrieval',
    commands: [
      { cmd: 'neurostack search "query"', desc: 'Hybrid FTS5 + semantic search. Flags: --top-k, --mode [hybrid|semantic|keyword], --context, --rerank' },
      { cmd: 'neurostack tiered "query"', desc: 'Tiered search with auto-escalation. Flags: --depth [triples|summaries|full|auto], --top-k, --context, --rerank' },
      { cmd: 'neurostack triples "query"', desc: 'Search structured SPO facts. Flags: --top-k, --mode' },
      { cmd: 'neurostack summary <path>', desc: 'Get pre-computed 2-3 sentence note summary (~100-200 tokens)' },
    ]
  },
  {
    label: 'Graph & Communities',
    commands: [
      { cmd: 'neurostack graph <note.md>', desc: 'Wiki-link neighbourhood with PageRank scoring. Flag: --depth' },
      { cmd: 'neurostack communities build', desc: 'Run Leiden clustering + generate LLM summaries for each community' },
      { cmd: 'neurostack communities query "q"', desc: 'Global GraphRAG query over communities. Flags: --top-k, --level [0|1], --no-map-reduce' },
      { cmd: 'neurostack communities list', desc: 'List detected communities. Flag: --level' },
    ]
  },
  {
    label: 'Maintenance',
    commands: [
      { cmd: 'neurostack prediction-errors', desc: 'Show poorly-fit notes. Flags: --type [low_overlap|contextual_mismatch], --limit, --resolve <path>' },
      { cmd: 'neurostack backfill [target]', desc: 'Backfill missing summaries, triples, or all' },
      { cmd: 'neurostack reembed-chunks', desc: 'Re-embed all chunks with updated context' },
      { cmd: 'neurostack folder-summaries', desc: 'Build folder-level summaries for semantic context boosting. Flag: --force' },
    ]
  },
  {
    label: 'Server & Sessions',
    commands: [
      { cmd: 'neurostack serve', desc: 'Start MCP server. Flag: --transport [stdio|sse]' },
      { cmd: 'neurostack sessions search "q"', desc: 'Search session transcripts via FTS5' },
      { cmd: 'neurostack brief', desc: 'Generate a compact ~500-token session context brief' },
    ]
  },
]

function CLI() {
  return (
    <Reveal>
      <section className="section" id="cli">
        <SectionHeader number="02" title="CLI Reference" />
        <div className="cli-grid">
          {CLI_GROUPS.map((group) => (
            <div key={group.label} className="cli-row" style={{ display: 'contents' }}>
              <div className="cli-group-label">{group.label}</div>
              {group.commands.map((c) => (
                <div key={c.cmd} style={{ display: 'contents' }}>
                  <div className="cli-cmd">{c.cmd}</div>
                  <div className="cli-desc">{c.desc}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
    </Reveal>
  )
}

// ── MCP Tools ───────────────────────────────────
const MCP_TOOLS = [
  {
    name: 'vault_search',
    purpose: 'Primary retrieval tool — hybrid FTS5 + semantic search with tiered depth escalation. Start with depth="auto" and let it escalate based on coverage.',
    params: [
      { name: 'query', type: 'str', desc: 'Natural language search query (required)' },
      { name: 'top_k', type: 'int', desc: 'Number of results. Default: 5' },
      { name: 'mode', type: 'str', desc: '"hybrid" | "semantic" | "keyword". Default: "hybrid"' },
      { name: 'depth', type: 'str', desc: '"triples" | "summaries" | "full" | "auto". Default: "auto"' },
      { name: 'context', type: 'str', desc: 'Domain context for boosting (e.g. "neuroscience", "devops")' },
    ],
    useCase: 'Most lookups — specific facts, notes, or topics. Always pass depth="auto" and context for best results.'
  },
  {
    name: 'vault_summary',
    purpose: 'Get a pre-computed 2-3 sentence summary of a note (~100-200 tokens vs ~500-2000 for full file). Quick overview before committing to a full read.',
    params: [
      { name: 'path_or_query', type: 'str', desc: 'Note path ("research/predictive-coding.md") or search query (required)' },
    ],
    useCase: 'Quick overview of a note before deciding whether to read the full content.'
  },
  {
    name: 'vault_graph',
    purpose: 'Wiki-link neighbourhood with PageRank scoring. Discover related notes without manually following links.',
    params: [
      { name: 'note', type: 'str', desc: 'Note path (required)' },
      { name: 'depth', type: 'int', desc: 'Link-hop distance. Default: 1' },
    ],
    useCase: 'Exploring what connects to a specific note — hub discovery, dependency mapping.'
  },
  {
    name: 'vault_triples',
    purpose: 'Search structured Subject-Predicate-Object facts at ~10-20 tokens each. The most token-efficient retrieval method.',
    params: [
      { name: 'query', type: 'str', desc: 'Natural language query (required)' },
      { name: 'top_k', type: 'int', desc: 'Number of triples. Default: 10' },
      { name: 'mode', type: 'str', desc: '"hybrid" | "semantic" | "keyword". Default: "hybrid"' },
    ],
    useCase: 'Efficient factual lookup — "what depends on X?", "where does Y run?"'
  },
  {
    name: 'vault_communities',
    purpose: 'GraphRAG global queries over Leiden community summaries. Uses map-reduce synthesis for thematic questions that span the whole vault.',
    params: [
      { name: 'query', type: 'str', desc: 'Thematic question (required)' },
      { name: 'top_k', type: 'int', desc: 'Communities to retrieve. Default: 6' },
      { name: 'level', type: 'int', desc: '0 = coarse themes, 1 = fine sub-themes. Default: 0' },
      { name: 'map_reduce', type: 'bool', desc: 'LLM synthesis vs raw hits. Default: true' },
    ],
    useCase: 'Thematic questions — "what topics dominate?", "how does X relate across the vault?"'
  },
  {
    name: 'vault_stats',
    purpose: 'Index health metrics — coverage statistics for notes, chunks, embeddings, summaries, graph edges, triples, and communities.',
    params: [],
    useCase: 'Monitor indexing progress and identify coverage gaps.'
  },
  {
    name: 'vault_record_usage',
    purpose: 'Track note access for hotness scoring. Notes that get used more often rank higher in future searches.',
    params: [
      { name: 'note_paths', type: 'list[str]', desc: 'Notes that were actually consumed (required)' },
    ],
    useCase: 'Provide relevance feedback to improve future ranking.'
  },
  {
    name: 'vault_prediction_errors',
    purpose: 'Surface notes with retrieval anomalies — drift detection. Flags outdated content or notes appearing in unexpected contexts.',
    params: [
      { name: 'error_type', type: 'str', desc: '"low_overlap" or "contextual_mismatch" (optional)' },
      { name: 'limit', type: 'int', desc: 'Max results. Default: 20' },
      { name: 'resolve', type: 'list[str]', desc: 'Mark specific notes as resolved (optional)' },
    ],
    useCase: 'Find outdated or miscategorised notes that need attention.'
  },
  {
    name: 'session_brief',
    purpose: 'Compact ~500-token session context combining recent vault changes, git commits, external memories, top connected notes, and time context.',
    params: [],
    useCase: 'Lightweight context injection at session start — get up to speed fast.'
  },
]

function McpTool({ tool }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mcp-tool">
      <div className="mcp-tool-header" onClick={() => setOpen(!open)}>
        <span className="mcp-tool-name">{tool.name}</span>
        <span className={`mcp-tool-toggle ${open ? 'open' : ''}`}>+</span>
      </div>
      <div className={`mcp-tool-body ${open ? 'open' : ''}`}>
        <div className="mcp-tool-inner">
          <div className="mcp-tool-content">
            <p className="mcp-tool-purpose">{tool.purpose}</p>
            {tool.params.length > 0 && (
              <div className="mcp-params">
                <h4>Parameters</h4>
                {tool.params.map((p) => (
                  <div className="mcp-param" key={p.name}>
                    <span className="mcp-param-name">{p.name}</span>
                    <span className="mcp-param-type">{p.type}</span>
                    <span className="mcp-param-desc">{p.desc}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="mcp-use-case">{tool.useCase}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function MCPTools() {
  return (
    <Reveal>
      <section className="section" id="mcp">
        <SectionHeader number="03" title="MCP Server Tools" />
        <p style={{ marginBottom: 'var(--space-lg)', color: 'var(--ink-light)', maxWidth: '60ch' }}>
          NeuroStack exposes a Model Context Protocol server with 9 tools.
          Add to your MCP config and use with any compatible client.
        </p>
        {MCP_TOOLS.map((tool) => (
          <McpTool key={tool.name} tool={tool} />
        ))}
      </section>
    </Reveal>
  )
}

// ── Neuroscience ────────────────────────────────
const NEURO_TABLE = [
  {
    feature: 'Hot Notes',
    concept: 'CREB-mediated excitability windows',
    mechanism: 'Active notes attract preferential connections, mirroring how elevated CREB levels bias neuronal recruitment into engrams',
    paper: 'Han et al. 2007, Science 316(5823), 457-460'
  },
  {
    feature: 'Drift Detection',
    concept: 'Prediction error-driven reconsolidation',
    mechanism: 'Notes surfacing in unexpected contexts trigger review, analogous to prediction errors destabilising consolidated memories',
    paper: 'Sinclair & Bhatt 2022, PNAS 119(31)'
  },
  {
    feature: 'Knowledge Graph',
    concept: 'Engram connectivity networks',
    mechanism: 'Wiki-links + PageRank model the interconnected neural ensembles that constitute distributed memory traces',
    paper: 'Josselyn & Tonegawa 2020, Science 367(6473)'
  },
  {
    feature: 'Communities',
    concept: 'Overlapping neural ensembles',
    mechanism: 'Leiden clustering mirrors how memories with temporal proximity share neuronal populations',
    paper: 'Cai et al. 2016, Nature 534, 115-118'
  },
  {
    feature: 'Tiered Retrieval',
    concept: 'Complementary learning systems',
    mechanism: 'Progressive depth escalation models the hippocampal-neocortical memory consolidation pathway',
    paper: 'McClelland et al. 1995, Psych. Review 102(3)'
  },
]

function Neuroscience() {
  return (
    <Reveal>
      <section className="section" id="neuroscience">
        <SectionHeader number="04" title="Neuroscience Grounding" />
        <p style={{ marginBottom: 'var(--space-lg)', color: 'var(--ink-light)', maxWidth: '65ch' }}>
          Every core feature maps to established memory neuroscience research.
          This is not metaphor &mdash; the algorithms are direct computational
          analogues of biological memory mechanisms.
        </p>
        <div style={{ overflowX: 'auto' }}>
          <table className="neuro-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Neuroscience Concept</th>
                <th>Mechanism</th>
                <th>Key Paper</th>
              </tr>
            </thead>
            <tbody>
              {NEURO_TABLE.map((row) => (
                <tr key={row.feature}>
                  <td>{row.feature}</td>
                  <td>{row.concept}</td>
                  <td>{row.mechanism}</td>
                  <td>{row.paper}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </Reveal>
  )
}

// ── Installation ────────────────────────────────
function Install() {
  return (
    <Reveal>
      <section className="section" id="install">
        <SectionHeader number="05" title="Installation" />
        <div className="install-grid">
          <div className="install-card">
            <div className="install-card-header">
              <h3 className="install-card-title">Lite Mode</h3>
              <span className="install-card-badge">~50MB</span>
            </div>
            <div className="install-card-body">
              <p className="install-desc">
                FTS5 keyword search only. No GPU needed, no external dependencies
                beyond Python and SQLite.
              </p>
              <div className="install-code">
                <span className="comment"># Quick install</span>{'\n'}
                curl -fsSL https://raw.githubusercontent.com/{'\n'}
                {'  '}raphasouthall/neurostack/main/install.sh | bash{'\n'}
                {'\n'}
                <span className="comment"># Or via pip</span>{'\n'}
                pip install neurostack{'\n'}
                {'\n'}
                <span className="comment"># Initialise vault</span>{'\n'}
                neurostack init ~/my-vault{'\n'}
                neurostack index
              </div>
              <ul className="install-features">
                <li>FTS5 full-text search</li>
                <li>Wiki-link graph + PageRank</li>
                <li>File watching + live indexing</li>
                <li>MCP server (stdio/SSE)</li>
                <li>CLI with all core commands</li>
              </ul>
            </div>
          </div>
          <div className="install-card">
            <div className="install-card-header">
              <h3 className="install-card-title">Full Mode</h3>
              <span className="install-card-badge">~500MB</span>
            </div>
            <div className="install-card-body">
              <p className="install-desc">
                Adds semantic embeddings, LLM summaries, triple extraction,
                and cross-encoder reranking via Ollama.
              </p>
              <div className="install-code">
                <span className="comment"># Install with ML extras</span>{'\n'}
                NEUROSTACK_MODE=full \{'\n'}
                {'  '}curl -fsSL https://raw.githubusercontent.com/{'\n'}
                {'  '}raphasouthall/neurostack/main/install.sh | bash{'\n'}
                {'\n'}
                <span className="comment"># Pull required models</span>{'\n'}
                ollama pull nomic-embed-text{'\n'}
                ollama pull qwen2.5:3b{'\n'}
                {'\n'}
                <span className="comment"># Optional: community detection (GPL-3.0)</span>{'\n'}
                pip install neurostack[community]
              </div>
              <ul className="install-features">
                <li>Everything in Lite, plus:</li>
                <li>Semantic embedding search (768-dim)</li>
                <li>LLM-generated note summaries</li>
                <li>SPO triple extraction</li>
                <li>Cross-encoder reranking</li>
                <li>Leiden community detection</li>
                <li>GraphRAG global queries</li>
                <li>Prediction error tracking</li>
              </ul>
            </div>
          </div>
        </div>
      </section>
    </Reveal>
  )
}

// ── Comparison ──────────────────────────────────
const COMPARISON = [
  { feature: 'Local-first', ns: 'Yes', obs: 'Yes', khoj: 'Partial', mem: 'No', notion: 'No' },
  { feature: 'AI-provider agnostic', ns: 'MCP', obs: 'No', khoj: 'Partial', mem: 'No', notion: 'No' },
  { feature: 'Semantic search', ns: 'Hybrid', obs: 'Plugin', khoj: 'Yes', mem: 'Yes', notion: 'Yes' },
  { feature: 'Knowledge graph', ns: 'PageRank', obs: 'Backlinks', khoj: 'No', mem: 'No', notion: 'No' },
  { feature: 'Community detection', ns: 'Leiden', obs: 'No', khoj: 'No', mem: 'No', notion: 'No' },
  { feature: 'Drift detection', ns: 'Yes', obs: 'No', khoj: 'No', mem: 'No', notion: 'No' },
  { feature: 'Tiered retrieval', ns: 'Auto', obs: 'No', khoj: 'No', mem: 'No', notion: 'No' },
  { feature: 'Lite mode (~50MB)', ns: 'Yes', obs: 'N/A', khoj: 'No', mem: 'No', notion: 'No' },
  { feature: 'CLI', ns: 'Yes', obs: 'No', khoj: 'Yes', mem: 'No', notion: 'No' },
  { feature: 'MCP server', ns: 'Yes', obs: 'No', khoj: 'No', mem: 'No', notion: 'No' },
  { feature: 'Open source', ns: 'Apache-2.0', obs: 'Core only', khoj: 'Yes', mem: 'No', notion: 'No' },
]

function renderCell(val) {
  if (val === 'Yes' || val === 'Apache-2.0' || val === 'MCP' || val === 'Hybrid' || val === 'PageRank' || val === 'Leiden' || val === 'Auto') {
    return <span className="check">{val}</span>
  }
  if (val === 'No' || val === 'N/A') {
    return <span className="cross">{val}</span>
  }
  return <span className="partial">{val}</span>
}

function Comparison() {
  return (
    <Reveal>
      <section className="section" id="comparison">
        <SectionHeader number="06" title="Comparison" />
        <p style={{ marginBottom: 'var(--space-lg)', color: 'var(--ink-light)', maxWidth: '55ch' }}>
          NeuroStack complements Obsidian as your editor &mdash; it adds the
          AI search engine layer that Obsidian lacks.
        </p>
        <div style={{ overflowX: 'auto' }}>
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th className="highlight-col">NeuroStack</th>
                <th>Obsidian</th>
                <th>Khoj</th>
                <th>mem.ai</th>
                <th>Notion AI</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map((row) => (
                <tr key={row.feature}>
                  <td>{row.feature}</td>
                  <td className="highlight-col">{renderCell(row.ns)}</td>
                  <td>{renderCell(row.obs)}</td>
                  <td>{renderCell(row.khoj)}</td>
                  <td>{renderCell(row.mem)}</td>
                  <td>{renderCell(row.notion)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </Reveal>
  )
}

// ── Configuration ───────────────────────────────
function Config() {
  return (
    <Reveal>
      <section className="section" id="config">
        <SectionHeader number="07" title="Configuration" />
        <div className="config-block">
          <div className="config-file">
            <span className="config-file-label">~/.config/neurostack/config.toml</span>
            <div className="config-code">
              <span className="key">vault_root</span> = <span className="val">"~/brain"</span>{'\n'}
              <span className="key">db_dir</span> = <span className="val">"~/.local/share/neurostack"</span>{'\n'}
              {'\n'}
              <span className="comment"># Ollama endpoints</span>{'\n'}
              <span className="key">embed_url</span> = <span className="val">"http://localhost:11435"</span>{'\n'}
              <span className="key">embed_model</span> = <span className="val">"nomic-embed-text"</span>{'\n'}
              <span className="key">embed_dim</span> = <span className="val">768</span>{'\n'}
              {'\n'}
              <span className="key">llm_url</span> = <span className="val">"http://localhost:11434"</span>{'\n'}
              <span className="key">llm_model</span> = <span className="val">"qwen2.5:3b"</span>{'\n'}
              {'\n'}
              <span className="comment"># Session transcripts</span>{'\n'}
              <span className="key">session_dir</span> = <span className="val">"~/.claude/projects"</span>
            </div>
          </div>
          <div className="config-file">
            <span className="config-file-label">MCP Client Config</span>
            <div className="config-code">
              {'{'}{'\n'}
              {'  '}<span className="key">"mcpServers"</span>: {'{'}{'\n'}
              {'    '}<span className="key">"neurostack"</span>: {'{'}{'\n'}
              {'      '}<span className="key">"command"</span>: <span className="val">"neurostack"</span>,{'\n'}
              {'      '}<span className="key">"args"</span>: [<span className="val">"serve"</span>],{'\n'}
              {'      '}<span className="key">"env"</span>: {'{}'}{'\n'}
              {'    }'}{'\n'}
              {'  }'}{'\n'}
              {'}'}
            </div>
          </div>
        </div>
        <div className="config-env-list">
          <h3>Environment Variable Overrides</h3>
          <p style={{ color: 'var(--ink-light)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-md)' }}>
            All config values support <code>NEUROSTACK_*</code> env var overrides:
          </p>
          <div className="env-vars">
            {[
              'NEUROSTACK_VAULT_ROOT',
              'NEUROSTACK_DB_DIR',
              'NEUROSTACK_EMBED_URL',
              'NEUROSTACK_EMBED_MODEL',
              'NEUROSTACK_EMBED_DIM',
              'NEUROSTACK_LLM_URL',
              'NEUROSTACK_LLM_MODEL',
              'NEUROSTACK_SESSION_DIR',
            ].map((v) => (
              <span className="env-var" key={v}>{v}</span>
            ))}
          </div>
        </div>
      </section>
    </Reveal>
  )
}

// ── Footer ──────────────────────────────────────
function Footer() {
  return (
    <footer className="footer">
      <div className="footer-left">
        <span className="footer-title">NeuroStack</span>
        <span className="footer-sub">Apache-2.0 &middot; Built by Raphael Southall</span>
      </div>
      <div className="footer-right">
        <a
          href="https://github.com/raphasouthall/neurostack"
          target="_blank"
          rel="noopener noreferrer"
          className="footer-link"
        >
          GitHub
        </a>
        <a href="#install" className="footer-link">Install</a>
        <a href="#features" className="footer-link">Docs</a>
      </div>
    </footer>
  )
}

// ── App ─────────────────────────────────────────
export default function App() {
  return (
    <div className="page">
      <Nav />
      <Hero />
      <hr className="section-rule" />
      <Features />
      <hr className="section-rule" />
      <CLI />
      <hr className="section-rule" />
      <MCPTools />
      <hr className="section-rule" />
      <Neuroscience />
      <hr className="section-rule" />
      <Install />
      <hr className="section-rule" />
      <Comparison />
      <hr className="section-rule" />
      <Config />
      <Footer />
    </div>
  )
}

import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

/* ═══════════════════════════════════════════════════════════════
   NeuroStack Documentation — Editorial/Scientific Design
   ═══════════════════════════════════════════════════════════════ */

// ── NeuroStack Icon ──────────────────────────────
function NeuroIcon({ size = 24, className = '' }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 128.85 129.11"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M71.64,4.52v29.03c0,4.02,4.85,6.03,7.7,3.2l20.73-20.6c1.78-1.77,4.65-1.75,6.41.04l4.81,4.9c1.73,1.76,1.72,4.57,0,6.33l-19.71,20.06s-2.8,3.42-8.5,3.42h-22.35s-9.94.15-10.41,12.49v21.26c0,.33-.03.66-.11.98-.23,1.02-.81,3.33-1.64,4.43s-14.85,15-21.3,21.39c-1.77,1.75-4.63,1.74-6.38-.03l-4.78-4.83c-1.74-1.76-1.74-4.59,0-6.35l20.59-20.89c2.81-2.85.79-7.69-3.22-7.69H4.52c-2.49,0-4.52-2.02-4.52-4.52v-6.83c0-2.5,2.03-4.53,4.53-4.52l28.83.1c4.02.01,6.05-4.84,3.22-7.69l-20.54-20.74c-1.78-1.8-1.74-4.72.1-6.46l4.99-4.73c1.79-1.69,4.6-1.64,6.32.11l20.41,20.72c2.82,2.86,7.69.89,7.73-3.12l.3-29.51c.03-2.48,2.04-4.47,4.52-4.47h6.69c2.49,0,4.52,2.02,4.52,4.52Z"/>
      <path d="M128.85,60.88v7.41c0,2.48-2.01,4.5-4.5,4.5h-38.11c-.74,0-1.1.89-.58,1.41l26.89,26.89c1.74,1.74,1.76,4.57.03,6.33l-4.62,4.71c-1.74,1.77-4.59,1.8-6.36.06l-27.72-27.19c-.49-.48-1.32-.13-1.31.56l.71,38.97c.05,2.52-1.98,4.58-4.5,4.58h-7.37c-2.48,0-4.5-2.01-4.5-4.5v-60.46s-.77-7.04,6.01-7.19c5.64-.13,47.43-.47,61.4-.58,2.5-.02,4.53,2,4.53,4.5Z"/>
    </svg>
  )
}

// ── PixelIcon — canvas pixelation reveal animation ──
const SVG_PATHS = [
  'M71.64,4.52v29.03c0,4.02,4.85,6.03,7.7,3.2l20.73-20.6c1.78-1.77,4.65-1.75,6.41.04l4.81,4.9c1.73,1.76,1.72,4.57,0,6.33l-19.71,20.06s-2.8,3.42-8.5,3.42h-22.35s-9.94.15-10.41,12.49v21.26c0,.33-.03.66-.11.98-.23,1.02-.81,3.33-1.64,4.43s-14.85,15-21.3,21.39c-1.77,1.75-4.63,1.74-6.38-.03l-4.78-4.83c-1.74-1.76-1.74-4.59,0-6.35l20.59-20.89c2.81-2.85.79-7.69-3.22-7.69H4.52c-2.49,0-4.52-2.02-4.52-4.52v-6.83c0-2.5,2.03-4.53,4.53-4.52l28.83.1c4.02.01,6.05-4.84,3.22-7.69l-20.54-20.74c-1.78-1.8-1.74-4.72.1-6.46l4.99-4.73c1.79-1.69,4.6-1.64,6.32.11l20.41,20.72c2.82,2.86,7.69.89,7.73-3.12l.3-29.51c.03-2.48,2.04-4.47,4.52-4.47h6.69c2.49,0,4.52,2.02,4.52,4.52Z',
  'M128.85,60.88v7.41c0,2.48-2.01,4.5-4.5,4.5h-38.11c-.74,0-1.1.89-.58,1.41l26.89,26.89c1.74,1.74,1.76,4.57.03,6.33l-4.62,4.71c-1.74,1.77-4.59,1.8-6.36.06l-27.72-27.19c-.49-.48-1.32-.13-1.31.56l.71,38.97c.05,2.52-1.98,4.58-4.5,4.58h-7.37c-2.48,0-4.5-2.01-4.5-4.5v-60.46s-.77-7.04,6.01-7.19c5.64-.13,47.43-.47,61.4-.58,2.5-.02,4.53,2,4.53,4.5Z',
]
const SVG_VIEWBOX = { w: 128.85, h: 129.11 }

function PixelIcon({ size = 280, className = '' }) {
  const canvasRef = useRef(null)
  const rafRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    const dpr = window.devicePixelRatio || 1
    const logicalSize = size
    // Set buffer dimensions at device resolution; let CSS control display size
    canvas.width = logicalSize * dpr
    canvas.height = logicalSize * dpr
    ctx.scale(dpr, dpr)

    // Resolve --accent color from CSS
    const accentRaw = getComputedStyle(document.documentElement)
      .getPropertyValue('--accent')
      .trim()

    // Render SVG paths to an offscreen canvas at full logical resolution
    const offscreen = document.createElement('canvas')
    offscreen.width = logicalSize
    offscreen.height = logicalSize
    const octx = offscreen.getContext('2d')

    const scaleX = logicalSize / SVG_VIEWBOX.w
    const scaleY = logicalSize / SVG_VIEWBOX.h
    octx.scale(scaleX, scaleY)
    octx.fillStyle = accentRaw || '#5c6bc0'
    for (const d of SVG_PATHS) {
      const p = new Path2D(d)
      octx.fill(p)
    }

    // Animation parameters
    const DURATION = 1500          // ms
    const MAX_PIXEL = 32           // starting block size
    const TARGET_OPACITY = 0.12
    let startTime = null

    // Easing: exponential ease-out  (t -> 1 fast, settles)
    function easeOut(t) {
      return 1 - Math.pow(1 - t, 3)
    }

    function frame(ts) {
      if (!startTime) startTime = ts
      const elapsed = ts - startTime
      const raw = Math.min(elapsed / DURATION, 1)
      const progress = easeOut(raw)

      // Pixel size shrinks from MAX_PIXEL → 1
      const pixelSize = Math.max(1, Math.round(MAX_PIXEL - progress * (MAX_PIXEL - 1)))

      // Draw: offscreen → tiny → back to display at pixelated scale
      ctx.clearRect(0, 0, logicalSize, logicalSize)
      ctx.globalAlpha = TARGET_OPACITY

      if (pixelSize <= 1) {
        // Fully resolved — draw directly
        ctx.imageSmoothingEnabled = true
        ctx.drawImage(offscreen, 0, 0, logicalSize, logicalSize)
      } else {
        const tinyW = Math.ceil(logicalSize / pixelSize)
        const tinyH = Math.ceil(logicalSize / pixelSize)
        const tiny = document.createElement('canvas')
        tiny.width = tinyW
        tiny.height = tinyH
        const tctx = tiny.getContext('2d')
        tctx.imageSmoothingEnabled = false
        tctx.drawImage(offscreen, 0, 0, tinyW, tinyH)

        ctx.imageSmoothingEnabled = false
        ctx.drawImage(tiny, 0, 0, logicalSize, logicalSize)
      }

      if (raw < 1) {
        rafRef.current = requestAnimationFrame(frame)
      }
    }

    rafRef.current = requestAnimationFrame(frame)

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [size])

  return (
    <canvas
      ref={canvasRef}
      className={className}
      aria-hidden="true"
      style={{ display: 'block' }}
    />
  )
}

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
  const [stars, setStars] = useState(null)
  const [version, setVersion] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  useEffect(() => {
    fetch('https://api.github.com/repos/raphasouthall/neurostack')
      .then(r => r.json())
      .then(d => { if (d.stargazers_count != null) setStars(d.stargazers_count) })
      .catch(() => {})
    fetch('https://api.github.com/repos/raphasouthall/neurostack/releases/latest')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.tag_name) setVersion(d.tag_name) })
      .catch(() => {})
  }, [])

  // Lock body scroll when menu is open
  useEffect(() => {
    if (menuOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [menuOpen])

  const navItems = [
    { href: '#features', label: 'Features' },
    { href: '#neuroscience', label: 'Science' },
    { href: '#cli', label: 'CLI' },
    { href: '#mcp', label: 'MCP' },
    { href: '#install', label: 'Install' },
    { href: '#comparison', label: 'Compare' },
  ]

  return (
    <nav className="nav" style={{ borderBottomColor: scrolled ? undefined : 'transparent' }}>
      <div className="nav-brand">
        <NeuroIcon size={24} className="nav-icon" />
        <h1>NeuroStack</h1>
        {version && <span className="nav-version">{version}</span>}
      </div>
      <ul className="nav-links">
        {navItems.map(item => (
          <li key={item.href}><a href={item.href}>{item.label}</a></li>
        ))}
      </ul>
      <div className="nav-right">
        <a
          href="https://github.com/raphasouthall/neurostack"
          target="_blank"
          rel="noopener noreferrer"
          className="nav-github"
        >
          <svg viewBox="0 0 19 19" width="16" height="16" fill="currentColor" aria-hidden="true">
            <path fillRule="evenodd" d="M9.356 1.85C5.05 1.85 1.57 5.356 1.57 9.694a7.84 7.84 0 0 0 5.324 7.44c.387.079.528-.168.528-.376 0-.182-.013-.805-.013-1.454-2.165.467-2.616-.935-2.616-.935-.349-.91-.864-1.143-.864-1.143-.71-.48.051-.48.051-.48.787.051 1.2.805 1.2.805.695 1.194 1.817.857 2.268.649.064-.507.27-.857.49-1.052-1.728-.182-3.545-.857-3.545-3.87 0-.857.31-1.558.8-2.104-.078-.195-.349-1 .077-2.078 0 0 .657-.208 2.14.805a7.5 7.5 0 0 1 1.946-.26c.657 0 1.328.092 1.946.26 1.483-1.013 2.14-.805 2.14-.805.426 1.078.155 1.883.078 2.078.502.546.799 1.247.799 2.104 0 3.013-1.818 3.675-3.558 3.87.284.247.528.714.528 1.454 0 1.052-.012 1.896-.012 2.156 0 .208.142.455.528.377a7.84 7.84 0 0 0 5.324-7.441c.013-4.338-3.48-7.844-7.773-7.844" clipRule="evenodd"/>
          </svg>
          Stars
          {stars != null && <span className="nav-star-count">{stars}</span>}
        </a>
        <button
          className="nav-hamburger"
          onClick={() => setMenuOpen(!menuOpen)}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={menuOpen}
        >
          <span className={`hamburger-line ${menuOpen ? 'open' : ''}`} />
          <span className={`hamburger-line ${menuOpen ? 'open' : ''}`} />
          <span className={`hamburger-line ${menuOpen ? 'open' : ''}`} />
        </button>
      </div>
      {menuOpen && (
        <div className="mobile-menu">
          <ul className="mobile-menu-links">
            {navItems.map(item => (
              <li key={item.href}>
                <a href={item.href} onClick={() => setMenuOpen(false)}>{item.label}</a>
              </li>
            ))}
          </ul>
          <a
            href="https://github.com/raphasouthall/neurostack"
            target="_blank"
            rel="noopener noreferrer"
            className="mobile-menu-github"
            onClick={() => setMenuOpen(false)}
          >
            View on GitHub {stars != null && `(${stars} stars)`}
          </a>
        </div>
      )}
    </nav>
  )
}

// ── Hero ────────────────────────────────────────
function Hero() {
  return (
      <section className="hero">
        <div className="hero-content">
          <span className="hero-eyebrow animate-in">Local-first &middot; Any AI provider &middot; Apache-2.0</span>
          <h2 className="animate-in delay-1">
            Your second brain, <em>starting today</em>
          </h2>
          <p className="hero-description animate-in delay-2">
            Install one command, answer a few questions, and you have a knowledge vault
            that gets smarter every day you use it. NeuroStack scaffolds your vault,
            indexes everything by meaning, surfaces what needs attention, and gives
            any AI tool long-term memory&mdash;all running locally.
          </p>
          <div className="hero-actions animate-in delay-3">
            <a href="#install" className="btn-primary">Get started</a>
            <a href="#features" className="btn-ghost">See features</a>
          </div>
          <div className="hero-chips animate-in delay-4">
            <span className="hero-chip"><strong>Zero</strong> prerequisites</span>
            <span className="hero-chip"><strong>Any</strong> AI provider</span>
            <span className="hero-chip"><strong>12</strong> MCP tools</span>
            <span className="hero-chip"><strong>~15 tok</strong> per triple</span>
          </div>
        </div>
        <div className="hero-icon-wrap animate-in delay-4">
          <PixelIcon size={280} className="hero-icon" mobileSize={100} />
        </div>
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

// ── How It Works ────────────────────────────────
function HowItWorks() {
  return (
    <Reveal>
      <section className="section how-it-works" id="how">
        <SectionHeader number="01" title="How It Works" />
        <div className="how-grid">
          <div className="how-step">
            <span className="how-step-number">1</span>
            <h3 className="how-step-title">Install &amp; Init</h3>
            <p className="how-step-desc">
              One command installs everything&mdash;no Python, git, or curl needed.
              The interactive setup walks you through vault location, model selection,
              and optional profession packs.
            </p>
            <code className="how-step-cmd">npm install -g neurostack && neurostack install && neurostack init</code>
          </div>
          <div className="how-step">
            <span className="how-step-number">2</span>
            <h3 className="how-step-title">Connect any AI</h3>
            <p className="how-step-desc">
              Use as an MCP server with{' '}
              <a href="https://docs.anthropic.com/en/docs/claude-code/cli-usage" target="_blank" rel="noopener noreferrer">Claude Code</a>,{' '}
              <a href="https://developers.openai.com/codex/mcp/" target="_blank" rel="noopener noreferrer">Codex</a>,{' '}
              <a href="https://geminicli.com/docs/tools/mcp-server/" target="_blank" rel="noopener noreferrer">Gemini CLI</a>,
              Cursor, Windsurf&mdash;or pipe CLI output into any LLM workflow.
            </p>
            <code className="how-step-cmd">neurostack serve</code>
          </div>
          <div className="how-step">
            <span className="how-step-number">3</span>
            <h3 className="how-step-title">It gets better every day</h3>
            <p className="how-step-desc">
              Hot notes surface what matters. Drift detection flags what's stale.
              Community detection reveals hidden themes. Your vault becomes a
              living knowledge system that improves the more you use it.
            </p>
            <code className="how-step-cmd">neurostack search "query"</code>
          </div>
        </div>
      </section>
    </Reveal>
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
    desc: '12-tool Model Context Protocol server. Works with Claude Code, Codex, Gemini CLI, Cursor, Windsurf — any MCP-compatible client. Provider-agnostic by design.',
    ref: 'Standard transport: stdio or SSE'
  },
  {
    label: 'Memory',
    name: 'Agent Memory Layer',
    desc: 'AI agents write observations, decisions, conventions, learnings, context, and bugs into the vault via vault_remember / vault_forget / vault_memories. Memories have optional TTL, workspace scoping, and surface automatically in search results.',
    ref: 'Episodic memory encoding — Tulving 1972'
  },
  {
    label: 'Scoping',
    name: 'Workspace Scoping',
    desc: 'Scope search and memory to subdirectories with --workspace flag or NEUROSTACK_WORKSPACE env var. Keeps project context isolated without separate databases.',
    ref: 'Contextual binding — Howard & Kahana 2002'
  },
]

function Features() {
  return (
    <Reveal>
      <section className="section" id="features">
        <SectionHeader number="02" title="Features" />
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

// ── CLI Showcase ────────────────────────────────
function CLIShowcase() {
  const [active, setActive] = useState(0)
  const screens = [
    { label: 'Search', file: 'search.gif' },
    { label: 'Graph', file: 'graph.gif' },
    { label: 'Brief', file: 'brief.gif' },
    { label: 'Memories', file: 'memories.gif' },
    { label: 'Stats', file: 'stats.gif' },
    { label: 'Scaffold', file: 'scaffold.gif' },
    { label: 'Doctor', file: 'doctor.gif' },
    { label: 'Prediction Errors', file: 'prediction-errors.gif' },
  ]

  return (
    <Reveal>
      <section className="section" id="showcase">
        <div className="showcase-label">See it in action</div>
        <div className="showcase-tabs">
          {screens.map((s, i) => (
            <button
              key={s.label}
              className={`showcase-tab ${i === active ? 'active' : ''}`}
              onClick={() => setActive(i)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="showcase-frame">
          <img
            src={`/screenshots/${screens[active].file}`}
            alt={`NeuroStack ${screens[active].label}`}
            className="showcase-img"
          />
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
      { cmd: 'neurostack install', desc: 'Install or upgrade mode (lite/full/community), auto-install Ollama, and pull models (skips already-available). Flags: --mode, --pull-models, --embed-model, --llm-model' },
      { cmd: 'neurostack init', desc: 'Interactive setup wizard — vault path, model, profession packs. Or: neurostack init [path] -p researcher' },
      { cmd: 'neurostack index', desc: 'Full re-index of vault — parses notes, extracts chunks, builds FTS5 and embeddings', gif: 'index.gif' },
      { cmd: 'neurostack watch', desc: 'Watch vault for changes and live-index on save' },
      { cmd: 'neurostack status', desc: 'Overview of index health and configuration', gif: 'status.gif' },
      { cmd: 'neurostack doctor', desc: 'Validate all subsystems — SQLite, Ollama, models, schema version', gif: 'doctor.gif' },
      { cmd: 'neurostack stats', desc: 'Index statistics: notes, chunks, embeddings, summaries, triples, communities', gif: 'stats.gif' },
      { cmd: 'neurostack uninstall', desc: 'Complete removal — data, venv, database, and npm package' },
    ]
  },
  {
    label: 'Search & Retrieval',
    commands: [
      { cmd: 'neurostack search "query"', desc: 'Hybrid FTS5 + semantic search. Flags: --top-k, --mode [hybrid|semantic|keyword], --context, --rerank, --workspace, --json', gif: 'search.gif' },
      { cmd: 'neurostack tiered "query"', desc: 'Tiered search with auto-escalation. Flags: --depth [triples|summaries|full|auto], --top-k, --context, --rerank, --json' },
      { cmd: 'neurostack triples "query"', desc: 'Search structured SPO facts. Flags: --top-k, --mode, --json' },
      { cmd: 'neurostack summary <path>', desc: 'Get pre-computed 2-3 sentence note summary (~100-200 tokens)', gif: 'summary.gif' },
    ]
  },
  {
    label: 'Graph & Communities',
    commands: [
      { cmd: 'neurostack graph <note.md>', desc: 'Wiki-link neighbourhood with PageRank scoring. Flag: --depth', gif: 'graph.gif' },
      { cmd: 'neurostack communities build', desc: 'Run Leiden clustering + generate LLM summaries for each community' },
      { cmd: 'neurostack communities query "q"', desc: 'Global GraphRAG query over communities. Flags: --top-k, --level [0|1], --no-map-reduce, --json' },
      { cmd: 'neurostack communities list', desc: 'List detected communities. Flag: --level' },
    ]
  },
  {
    label: 'Maintenance',
    commands: [
      { cmd: 'neurostack prediction-errors', desc: 'Show poorly-fit notes. Flags: --type [low_overlap|contextual_mismatch], --limit, --resolve <path>', gif: 'prediction-errors.gif' },
      { cmd: 'neurostack backfill [target]', desc: 'Backfill missing summaries, triples, or all' },
      { cmd: 'neurostack reembed-chunks', desc: 'Re-embed all chunks with updated context' },
      { cmd: 'neurostack folder-summaries', desc: 'Build folder-level summaries for semantic context boosting. Flag: --force' },
    ]
  },
  {
    label: 'Vault & Memories',
    commands: [
      { cmd: 'neurostack scaffold --list', desc: 'List available profession packs (researcher, developer, writer, student, devops, data-scientist)', gif: 'scaffold.gif' },
      { cmd: 'neurostack onboard <dir>', desc: 'Onboard an existing directory of notes into a NeuroStack vault. Flag: -n (dry run)' },
      { cmd: 'neurostack memories add "text"', desc: 'Store an agent memory. Flags: --type [observation|decision|convention|learning|context|bug], --ttl', gif: 'memories.gif' },
      { cmd: 'neurostack memories list', desc: 'List all stored memories' },
      { cmd: 'neurostack memories search "q"', desc: 'Search memories by keyword' },
      { cmd: 'neurostack record-usage <path>', desc: 'Mark a note as used — drives hotness scoring for retrieval priority', gif: 'record-usage.gif' },
    ]
  },
  {
    label: 'Server & Sessions',
    commands: [
      { cmd: 'neurostack serve', desc: 'Start MCP server. Flag: --transport [stdio|sse]' },
      { cmd: 'neurostack sessions search "q"', desc: 'Search session transcripts via FTS5' },
      { cmd: 'neurostack brief', desc: 'Generate a compact ~500-token session context brief', gif: 'brief.gif' },
    ]
  },
]

function CLICommand({ c }) {
  const [showGif, setShowGif] = useState(false)
  return (
    <>
      <div style={{ display: 'contents' }}>
        <div className="cli-cmd">
          {c.cmd}
          {c.gif && (
            <button
              className="cli-demo-toggle"
              onClick={() => setShowGif(!showGif)}
              title={showGif ? 'Hide demo' : 'Show demo'}
            >
              {showGif ? '▾ hide' : '▸ demo'}
            </button>
          )}
        </div>
        <div className="cli-desc">{c.desc}</div>
      </div>
      {showGif && c.gif && (
        <div className="cli-demo-row">
          <img
            src={`/screenshots/${c.gif}`}
            alt={`Demo: ${c.cmd}`}
            className="cli-demo-gif"
            loading="lazy"
          />
        </div>
      )}
    </>
  )
}

function CLI() {
  return (
    <Reveal>
      <section className="section" id="cli">
        <SectionHeader number="04" title="CLI Reference" />
        <div className="cli-grid">
          {CLI_GROUPS.map((group) => (
            <div key={group.label} className="cli-row" style={{ display: 'contents' }}>
              <div className="cli-group-label">{group.label}</div>
              {group.commands.map((c) => (
                <CLICommand key={c.cmd} c={c} />
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
      { name: 'workspace', type: 'str', desc: 'Scope to subdirectory (e.g. "work/project-x"). Also via NEUROSTACK_WORKSPACE env var' },
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
    name: 'vault_remember',
    purpose: 'Write an observation, decision, convention, learning, context note, or bug into the vault. Memories surface automatically in future search results.',
    params: [
      { name: 'content', type: 'str', desc: 'The memory content to store (required)' },
      { name: 'category', type: 'str', desc: '"observation" | "decision" | "convention" | "learning" | "context" | "bug". Default: "observation"' },
      { name: 'ttl_days', type: 'int', desc: 'Auto-expire after N days (optional, omit for permanent)' },
      { name: 'workspace', type: 'str', desc: 'Scope to a subdirectory (optional)' },
    ],
    useCase: 'Agents recording what they learn — project conventions, debugging insights, architectural decisions.'
  },
  {
    name: 'vault_forget',
    purpose: 'Remove a previously stored memory by ID. Use when a memory is outdated, incorrect, or no longer relevant.',
    params: [
      { name: 'memory_id', type: 'str', desc: 'The memory ID to remove (required)' },
    ],
    useCase: 'Cleaning up stale or superseded agent memories.'
  },
  {
    name: 'vault_memories',
    purpose: 'List stored agent memories, optionally filtered by category or workspace. Memories are returned with their IDs for management.',
    params: [
      { name: 'category', type: 'str', desc: 'Filter by category (optional)' },
      { name: 'workspace', type: 'str', desc: 'Filter by workspace scope (optional)' },
      { name: 'limit', type: 'int', desc: 'Max results. Default: 20' },
    ],
    useCase: 'Reviewing what an agent has remembered — auditing conventions, checking for stale context.'
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
        <SectionHeader number="05" title="MCP Server Tools" />
        <p style={{ marginBottom: 'var(--space-lg)', color: 'var(--ink-light)', maxWidth: '60ch' }}>
          NeuroStack exposes a Model Context Protocol server with 12 tools.
          Works with{' '}
          <a href="https://docs.anthropic.com/en/docs/claude-code/cli-usage" target="_blank" rel="noopener noreferrer">Claude Code</a>,{' '}
          <a href="https://developers.openai.com/codex/mcp/" target="_blank" rel="noopener noreferrer">Codex</a>,{' '}
          <a href="https://geminicli.com/docs/tools/mcp-server/" target="_blank" rel="noopener noreferrer">Gemini CLI</a>,
          Cursor, Windsurf, and any MCP-compatible client.
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
        <SectionHeader number="03" title="Neuroscience Grounding" />
        <p style={{ marginBottom: 'var(--space-lg)', color: 'var(--ink-light)', maxWidth: '65ch' }}>
          Every core feature maps to established memory neuroscience research.
          This is not metaphor &mdash; the algorithms are direct computational
          analogues of biological memory mechanisms.
        </p>
        <div className="neuro-table-wrap">
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
        <div className="neuro-cards">
          {NEURO_TABLE.map((row) => (
            <div className="neuro-card" key={row.feature}>
              <span className="neuro-card-feature">{row.feature}</span>
              <h4 className="neuro-card-concept">{row.concept}</h4>
              <p className="neuro-card-mechanism">{row.mechanism}</p>
              <cite className="neuro-card-paper">{row.paper}</cite>
            </div>
          ))}
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
        <SectionHeader number="06" title="Get Started" />
        <p style={{ marginBottom: 'var(--space-lg)', color: 'var(--ink-light)', maxWidth: '60ch' }}>
          Bootstrap the CLI, then use <code>neurostack install</code> to choose your mode
          and set up Ollama models. It auto-installs Ollama if needed and skips
          models you already have. Re-run anytime to upgrade.
        </p>
        <div className="install-grid">
          <div className="install-card">
            <div className="install-card-header">
              <h3 className="install-card-title">Lite Mode</h3>
              <span className="install-card-badge">~130MB</span>
            </div>
            <div className="install-card-body">
              <p className="install-desc">
                FTS5 keyword search, wiki-link graph, stale note detection,
                and MCP server. No GPU needed.
              </p>
              <div className="install-code">
                <span className="comment"># Bootstrap + choose lite mode</span>{'\n'}
                npm install -g neurostack{'\n'}
                neurostack install --mode lite{'\n'}
                neurostack init
              </div>
              <ul className="install-features">
                <li>FTS5 full-text search</li>
                <li>Wiki-link graph + PageRank</li>
                <li>Stale note detection</li>
                <li>File watching + live indexing</li>
                <li>MCP server (stdio/SSE)</li>
                <li>Interactive setup wizard</li>
              </ul>
              <h4 className="install-detail-heading">What gets installed</h4>
              <ul className="install-details">
                <li><strong>uv</strong> ~30MB &mdash; Python package manager (auto-installed)</li>
                <li><strong>Python 3.12</strong> ~50MB &mdash; standalone, managed by uv</li>
                <li><strong>NeuroStack + deps</strong> ~50MB &mdash; pyyaml, watchdog, mcp, httpx</li>
                <li><strong>Config</strong> &mdash; ~/.config/neurostack/config.toml</li>
                <li><strong>Database</strong> &mdash; ~/.local/share/neurostack/neurostack.db</li>
              </ul>
            </div>
          </div>
          <div className="install-card">
            <div className="install-card-header">
              <h3 className="install-card-title">Full Mode</h3>
              <span className="install-card-badge">~560MB</span>
            </div>
            <div className="install-card-body">
              <p className="install-desc">
                Adds semantic embeddings, LLM summaries, triple extraction,
                and cross-encoder reranking. Requires Ollama.
              </p>
              <div className="install-code">
                <span className="comment"># Full mode + pull Ollama models</span>{'\n'}
                npm install -g neurostack{'\n'}
                neurostack install --mode full --pull-models{'\n'}
                neurostack init
              </div>
              <ul className="install-features">
                <li>Everything in Lite, plus:</li>
                <li>Semantic embedding search (768-dim)</li>
                <li>LLM-generated note summaries</li>
                <li>SPO triple extraction</li>
                <li>Cross-encoder reranking</li>
              </ul>
              <h4 className="install-detail-heading">Additional installs</h4>
              <ul className="install-details">
                <li><strong>numpy</strong> ~30MB &mdash; numerical computing</li>
                <li><strong>sentence-transformers</strong> ~100MB &mdash; embeddings &amp; reranking</li>
                <li><strong>PyTorch CPU</strong> ~300MB &mdash; ML runtime</li>
                <li><strong>Ollama</strong> ~1GB+ &mdash; auto-installed on Linux, or <a href="https://ollama.ai" target="_blank" rel="noopener noreferrer">download for macOS</a></li>
              </ul>
            </div>
          </div>
        </div>
        <div style={{ marginTop: 'var(--space-lg)', color: 'var(--ink-light)', fontSize: 'var(--text-sm)' }}>
          <p>
            <strong>Community mode:</strong> Add topic cluster detection with{' '}
            <code>neurostack install --mode community</code> (+15MB, leidenalg GPL-3.0).
          </p>
          <p style={{ marginTop: 'var(--space-sm)' }}>
            <strong>Upgrade anytime:</strong> Re-run <code>neurostack install</code> to switch modes
            (e.g., lite &rarr; full). <strong>Uninstall:</strong> <code>neurostack uninstall</code> removes everything.
            Config is preserved so reinstall picks up where you left off.
          </p>
        </div>
      </section>
    </Reveal>
  )
}

// ── Comparison ──────────────────────────────────
const COMPARISON = [
  { feature: 'Local-first',            lite: 'Yes',        full: 'Yes',        obs: 'Yes',       khoj: 'Partial',  notion: 'No' },
  { feature: 'AI-provider agnostic',   lite: 'MCP',        full: 'MCP',        obs: 'No',        khoj: 'Partial',  notion: 'No' },
  { feature: 'Full-text search',       lite: 'FTS5',       full: 'FTS5',       obs: 'Yes',       khoj: 'Yes',      notion: 'Yes' },
  { feature: 'Semantic search',        lite: 'No',         full: 'Hybrid',     obs: 'Plugin',    khoj: 'Yes',      notion: 'Yes' },
  { feature: 'Knowledge graph',        lite: 'PageRank',   full: 'PageRank',   obs: 'Backlinks', khoj: 'No',       notion: 'No' },
  { feature: 'Community detection',    lite: 'No',         full: 'Leiden',     obs: 'No',        khoj: 'No',       notion: 'No' },
  { feature: 'Drift detection',        lite: 'Yes',        full: 'Yes',        obs: 'No',        khoj: 'No',       notion: 'No' },
  { feature: 'Tiered retrieval',       lite: 'No',         full: 'Auto',       obs: 'No',        khoj: 'No',       notion: 'No' },
  { feature: 'AI summaries & triples', lite: 'No',         full: 'Yes',        obs: 'No',        khoj: 'Partial',  notion: 'Yes' },
  { feature: 'Cross-encoder reranking',lite: 'No',         full: 'Yes',        obs: 'No',        khoj: 'No',       notion: 'No' },
  { feature: 'CLI',                    lite: 'Yes',        full: 'Yes',        obs: 'No',        khoj: 'Yes',      notion: 'No' },
  { feature: 'MCP server',             lite: 'Yes',        full: 'Yes',        obs: 'No',        khoj: 'No',       notion: 'No' },
  { feature: 'Agent memory',           lite: 'Yes',        full: 'Yes',        obs: 'No',        khoj: 'No',       notion: 'No' },
  { feature: 'Open source',            lite: 'Apache-2.0', full: 'Apache-2.0', obs: 'Core only', khoj: 'Yes',      notion: 'No' },
  { feature: 'Install size',           lite: '~130MB',     full: '~560MB',     obs: '~250MB',    khoj: '~500MB',   notion: 'Cloud' },
  { feature: 'GPU required',           lite: 'No',         full: 'Optional',   obs: 'No',        khoj: 'Optional', notion: 'No' },
  { feature: 'Price',                  lite: 'Free',       full: 'Free',       obs: '$50/yr',    khoj: 'Free/paid',notion: '$10/mo' },
]

const POSITIVE_VALUES = new Set([
  'Yes', 'Apache-2.0', 'MCP', 'Hybrid', 'PageRank', 'Leiden', 'Auto', 'FTS5', 'Free',
])

function renderCell(val) {
  if (POSITIVE_VALUES.has(val)) {
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
        <SectionHeader number="07" title="Comparison" />
        <p style={{ marginBottom: 'var(--space-lg)', color: 'var(--ink-light)', maxWidth: '55ch' }}>
          NeuroStack complements Obsidian as your editor &mdash; it adds the
          AI search engine layer that Obsidian lacks.
        </p>
        <div className="table-scroll-wrap">
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th className="highlight-col" colSpan="2">NeuroStack</th>
                <th>Obsidian</th>
                <th>Khoj</th>
                <th>Notion AI</th>
              </tr>
              <tr className="comparison-subheader">
                <th></th>
                <th className="highlight-col sub">Full <span className="comparison-size">~560MB</span></th>
                <th className="highlight-col sub">Lite <span className="comparison-size">~130MB</span></th>
                <th></th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.filter(row => row.feature !== 'Install size').map((row) => (
                <tr key={row.feature}>
                  <td>{row.feature}</td>
                  <td className="highlight-col">{renderCell(row.full)}</td>
                  <td className="highlight-col">{renderCell(row.lite)}</td>
                  <td>{renderCell(row.obs)}</td>
                  <td>{renderCell(row.khoj)}</td>
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
        <SectionHeader number="08" title="Configuration" />
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
              <span className="key">llm_model</span> = <span className="val">"phi3.5"</span>{'\n'}
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
              'NEUROSTACK_WORKSPACE',
            ].map((v) => (
              <span className="env-var" key={v}>{v}</span>
            ))}
          </div>
        </div>
      </section>
    </Reveal>
  )
}

// ── Sponsor Banner ─────────────────────────────
function SponsorBanner() {
  return (
    <Reveal>
      <section className="sponsor-banner">
        <div className="sponsor-inner">
          <div className="sponsor-text">
            <h3 className="sponsor-title">Looking for sponsors</h3>
            <p className="sponsor-desc">
              NeuroStack is built and maintained by a single developer.
              If it&rsquo;s useful to you, consider sponsoring to help fund
              development, hosting, and new features.
            </p>
          </div>
          <a
            href="https://github.com/sponsors/raphasouthall"
            target="_blank"
            rel="noopener noreferrer"
            className="sponsor-btn"
          >
            <svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true">
              <path d="M4.25 2.5c-1.336 0-2.75 1.164-2.75 3 0 2.15 1.58 4.144 3.365 5.682A20 20 0 0 0 8 13.393a20 20 0 0 0 3.135-2.211C12.92 9.644 14.5 7.65 14.5 5.5c0-1.836-1.414-3-2.75-3-1.373 0-2.609.986-3.029 2.456a.75.75 0 0 1-1.442 0C6.859 3.486 5.623 2.5 4.25 2.5M8 14.25l-.345.666-.002-.001-.006-.003-.018-.01a8 8 0 0 1-.31-.17 22 22 0 0 1-3.434-2.414C2.045 10.731 0 8.35 0 5.5 0 2.836 2.086 1 4.25 1 5.797 1 7.153 1.802 8 3.02 8.847 1.802 10.203 1 11.75 1 13.914 1 16 2.836 16 5.5c0 2.85-2.045 5.231-3.885 6.818a22 22 0 0 1-3.744 2.584l-.018.01-.006.003h-.002L8 14.25m0 0 .345.666a.75.75 0 0 1-.69 0z" />
            </svg>
            Sponsor
          </a>
          <a
            href="https://buymeacoffee.com/raphasouthall"
            target="_blank"
            rel="noopener noreferrer"
            className="sponsor-btn"
            style={{ marginLeft: '0.75rem' }}
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
              <path d="M20.216 6.415l-.132-.666c-.119-.598-.388-1.163-1.001-1.379-.197-.069-.42-.098-.57-.241-.152-.143-.196-.366-.231-.572-.065-.378-.125-.756-.192-1.133-.057-.325-.102-.69-.25-.987-.195-.4-.597-.634-.996-.788a5.723 5.723 0 00-.626-.194c-1-.263-2.05-.36-3.077-.416a25.834 25.834 0 00-3.7.062c-.915.083-1.88.184-2.75.5-.318.116-.646.256-.888.501-.297.302-.393.77-.177 1.146.154.267.415.456.692.58.36.162.737.284 1.123.366 1.075.238 2.189.331 3.287.37 1.218.05 2.437.01 3.65-.118.299-.033.598-.073.896-.119.352-.054.578-.513.474-.834-.124-.383-.457-.531-.834-.473-.466.074-.96.108-1.382.146-1.177.08-2.358.082-3.536.006a22.228 22.228 0 01-1.157-.107c-.086-.01-.18-.025-.258-.036-.243-.036-.484-.08-.724-.13-.111-.027-.111-.185 0-.212h.005c.277-.06.557-.108.838-.147h.002c.131-.009.263-.032.394-.048a25.076 25.076 0 013.426-.12c.674.019 1.347.062 2.014.13l.04.005c.11.01.224.021.338.034.24.028.48.062.717.103.196.033.39.072.582.116.121.028.241.059.36.093.038.011.108.03.184.063l.097.039c.025.011.053.022.073.035.083.052.108.088.128.21l.018.098.043.213.038.188.044.217c.032.157-.075.329-.234.348a24.693 24.693 0 01-5.384.168c-.478-.029-.96-.076-1.434-.142a8.02 8.02 0 01-.363-.055c-.103-.018-.209-.033-.3-.058-.025-.01-.049-.019-.065-.026-.093-.048-.179-.165-.163-.282l.002-.014a.376.376 0 01.363-.293c.675.01 1.345-.02 2.014-.082.399-.037.795-.085 1.189-.148.187-.03.373-.066.558-.104a.325.325 0 00.265-.317.327.327 0 00-.323-.329c-.466-.002-.934.022-1.398.064-.958.085-1.908.222-2.871.308a28.28 28.28 0 01-2.882.043c-.479-.016-.911-.085-1.34-.22-.106-.034-.203-.08-.313-.144-.079-.048-.078-.182 0-.231.093-.058.197-.098.301-.131.222-.07.452-.119.684-.156.472-.075.949-.113 1.427-.144.48-.032.961-.048 1.442-.053.481-.005.963.002 1.444.019.24.009.48.02.719.034.253.014.49-.156.508-.403.018-.256-.196-.476-.449-.487-.259-.012-.519-.021-.778-.028a24.553 24.553 0 00-3.1.07 14.57 14.57 0 00-1.079.143c-.058.01-.117.021-.175.034-.209.044-.41.104-.612.173l-.073.028a.326.326 0 00-.193.433c.057.149.166.253.322.29.038.012.08.02.115.025l.014.002c.094.015.19.026.285.038.334.042.67.073 1.008.094a22.93 22.93 0 003.177-.025l.072-.006c.082-.007.165-.017.247-.025a.323.323 0 01.342.231.326.326 0 01-.202.39c-.163.063-.338.09-.5.13l-.066.017c-.259.063-.52.113-.783.151a16.64 16.64 0 01-2.021.164c-.336.007-.673-.003-1.008-.024-.129-.009-.258-.02-.387-.034-.038-.004-.076-.01-.114-.017-.137-.028-.221-.181-.184-.316.037-.135.186-.229.323-.214l.026.003c.065.008.13.013.196.017.334.018.669.024 1.004.014.665-.019 1.327-.076 1.983-.175.147-.022.294-.049.44-.079a.325.325 0 00.256-.392.326.326 0 00-.391-.259c-.137.028-.274.053-.412.074a15.255 15.255 0 01-3.47.126c-.069-.005-.138-.014-.207-.023-.076-.009-.151-.02-.219-.036-.032-.009-.072-.022-.09-.048-.044-.065.028-.192.087-.231l.049-.026a3.57 3.57 0 01.37-.148c.39-.134.792-.23 1.198-.297.811-.132 1.636-.177 2.458-.16.412.009.823.03 1.234.063l.065.006a.329.329 0 00.346-.307.327.327 0 00-.306-.348c-.442-.036-.886-.058-1.33-.064a17.084 17.084 0 00-2.694.168c-.407.067-.81.163-1.2.297l-.044.016a.325.325 0 00-.211.406.326.326 0 00.396.216l.056-.017c.374-.128.762-.22 1.153-.285.781-.13 1.575-.175 2.364-.16.394.008.789.028 1.182.06l.044.004a.329.329 0 00.348-.302.329.329 0 00-.302-.35c-.41-.034-.821-.054-1.232-.062-.823-.015-1.649.03-2.462.16-.406.065-.808.16-1.198.294l-.044.016-.019.008c-.076.032-.138.088-.178.162-.043.082-.057.175-.039.268.033.171.192.296.368.287l.03-.001zm.517 7.834c.025.283-.18.543-.463.572a.537.537 0 01-.573-.464c-.156-1.756-1.245-3.195-2.786-3.735-.222-.078-.291-.352-.136-.522a.397.397 0 01.41-.107c1.896.665 3.272 2.434 3.548 4.256z"/>
              <path d="M5.535 16.476a.537.537 0 01-.316.655c-.192.08-.412-.003-.495-.195a4.69 4.69 0 01-.38-1.87c0-2.591 2.103-4.694 4.694-4.694a4.69 4.69 0 013.32 1.374.397.397 0 01.012.562c-.15.156-.398.163-.556.015a3.898 3.898 0 00-2.776-1.148 3.897 3.897 0 00-3.897 3.897c0 .48.087.952.255 1.396a.54.54 0 01.139.008z"/>
              <path d="M18.85 13.249h.737a2.2 2.2 0 012.2 2.2v.9a2.2 2.2 0 01-2.2 2.2h-.737v-5.3zM4 19.875c0-.55.45-1 1-1h12c.55 0 1 .45 1 1v.25c0 .55-.45 1-1 1H5c-.55 0-1-.45-1-1v-.25z"/>
            </svg>
            Buy me a coffee
          </a>
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
        <NeuroIcon size={20} className="footer-icon" />
        <span className="footer-title">NeuroStack</span>
        <span className="footer-sub">Apache-2.0 &middot; Built by Raphael Southall</span>
      </div>
      <div className="footer-right">
        <a href="mailto:hello@neurostack.sh" className="footer-link">hello@neurostack.sh</a>
        <a href="https://github.com/raphasouthall/neurostack" target="_blank" rel="noopener noreferrer" className="footer-link">
          <svg width="16" height="16" viewBox="0 0 19 19"><use href="/icons.svg#github-icon" /></svg>
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
      <HowItWorks />
      <hr className="section-rule" />
      <Features />
      <hr className="section-rule" />
      <Neuroscience />
      <hr className="section-rule" />
      <CLI />
      <hr className="section-rule" />
      <CLIShowcase />
      <hr className="section-rule" />
      <MCPTools />
      <hr className="section-rule" />
      <Install />
      <hr className="section-rule" />
      <Comparison />
      <hr className="section-rule" />
      <Config />
      <SponsorBanner />
      <Footer />
    </div>
  )
}

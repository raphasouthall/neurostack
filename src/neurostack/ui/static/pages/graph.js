import { html, useState, useEffect, useRef } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';
import {
  Alert, AlertDescription, AlertTitle, Button, Card, CardAction, CardContent, CardHeader, CardTitle, Input, Loading,
  NativeSelect,
} from '../components/ui.js';

// Canvas colours come from the theme tokens. Communities cycle through the
// chart colours; notes outside any community are muted.
const PALETTE = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5', '--chart-6', '--chart-7', '--destructive'];
function themeColors() {
  const s = getComputedStyle(document.documentElement);
  const v = (name) => s.getPropertyValue(name).trim();
  return { palette: PALETTE.map(v), none: v('--muted-foreground'), link: v('--border'), ink: v('--foreground') };
}

document.head.insertAdjacentHTML('beforeend', `<style>
.graph-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
/* A long community name must not widen the page. */
.graph-bar .input { min-width: 0; max-width: 100%; }
.graph-bar .sub { margin-left: auto; }
.graph-canvas, .graph-panel { height: calc(100vh - 210px); min-height: 360px; }
.graph-canvas { overflow: hidden; border-radius: var(--radius-xl); }
.graph-stage { min-width: 0; }
.graph-panel { display: flex; flex-direction: column; }
.graph-panel .card-content { flex: 1; overflow: auto; }
.graph-close { width: 32px; height: 32px; margin: -6px -8px -6px 0; font-size: 16px; font-weight: 400; color: var(--secondary-foreground); }
.graph-title { font-size: 16px; font-weight: 600; margin: 0 0 4px; }
.graph-path { font: 12px var(--font-mono); color: var(--muted-foreground); word-break: break-all; margin-bottom: 12px; }
.graph-summary { font-size: 13px; line-height: 1.5; margin: 0 0 12px; }
.graph-nb { margin-top: 16px; }
.graph-nb .card-header { padding: 0 0 8px; }
.graph-nb .btn { display: flex; justify-content: flex-start; width: 100%; padding: 4px 0; font-size: 13px;
  color: var(--foreground); text-align: left; white-space: normal; }
</style>`);

// force-graph ships as UMD only, so it loads once as a classic script.
let forceGraph;
function loadForceGraph() {
  return forceGraph ??= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = new URL('../vendor/force-graph.min.js', import.meta.url);
    s.onload = () => resolve(window.ForceGraph);
    s.onerror = () => { forceGraph = null; reject(new Error('could not load force-graph')); };
    document.head.append(s);
  });
}

// The shell keeps this page mounted when only the query changes, so both the
// first render and hashchange read `#/graph?note=<path>` through here.
const hashNote = () => new URLSearchParams(location.hash.split('?')[1]).get('note');

export default function Page() {
  const [selected, setSelected] = useState(hashNote);
  const [limit, setLimit] = useState(500);
  const [community, setCommunity] = useState('');
  const [communities, setCommunities] = useState([]);
  const [data, setData] = useState(null);
  const [note, setNote] = useState(null);
  const [query, setQuery] = useState('');
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(null);
  const box = useRef();
  const fg = useRef();
  // The canvas callbacks are bound once, so they read live state from here.
  const view = useRef({ pending: selected });
  view.current.colors ??= themeColors();
  view.current.query = query.trim().toLowerCase();
  view.current.selected = selected;

  function focus(path) {
    setSelected(path);
    const n = fg.current?.graphData().nodes.find(x => x.id === path);
    if (n?.x == null) return void (view.current.pending = path);
    fg.current.centerAt(n.x, n.y, 600).zoom(3, 600);
  }

  function color(n) {
    const v = view.current, c = v.colors;
    const base = n.community == null ? c.none : c.palette[n.community % c.palette.length];
    if (v.query && !n.key.includes(v.query)) return base + '26';
    return n.status === 'dormant' ? base + '59' : base;
  }

  function decorate(n, ctx, scale) {
    const v = view.current;
    if (n.id === v.selected) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + 2 / scale, 0, 2 * Math.PI);
      ctx.strokeStyle = v.colors.ink;
      ctx.lineWidth = 1.5 / scale;
      ctx.stroke();
    }
    const shown = v.query ? n.key.includes(v.query) : scale > 2.5 || n.rank < 20;
    if (!shown && n !== v.hover && n.id !== v.selected) return;
    ctx.font = `${11 / scale}px Inter, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = v.colors.ink;
    ctx.fillText(n.title || n.id, n.x, n.y + n.r + 2 / scale);
  }

  useEffect(() => {
    let alive = true, g, ro;
    loadForceGraph().then(ForceGraph => {
      if (!alive) return;
      g = fg.current = ForceGraph()(box.current)
        .nodeRelSize(1).nodeVal(n => n.r * n.r).nodeColor(color)
        .nodeCanvasObjectMode(() => 'after').nodeCanvasObject(decorate)
        // Lay out before the first frame so a deep-linked node is centred where it settles.
        .warmupTicks(100)
        .linkColor(() => view.current.colors.link).linkWidth(0.5)
        .onNodeHover(n => { view.current.hover = n; })
        .onNodeClick(n => focus(n.id))
        .onEngineTick(() => {
          const p = view.current.pending;
          const n = p && g.graphData().nodes.find(x => x.id === p);
          if (n?.x != null) { view.current.pending = null; focus(p); }
        });
      ro = new ResizeObserver(() =>
        g.width(box.current.clientWidth).height(box.current.clientHeight));
      ro.observe(box.current);
      setReady(true);
    }, e => setError(e.message));
    api('communities').then(setCommunities, e => setError(e.message));
    const onHash = () => { const p = hashNote(); if (p) focus(p); };
    // Re-setting an accessor makes force-graph redraw in the new colours.
    const onTheme = () => {
      view.current.colors = themeColors();
      g?.nodeColor(color).linkColor(() => view.current.colors.link);
    };
    addEventListener('hashchange', onHash);
    addEventListener('ns-theme', onTheme);
    return () => {
      alive = false;
      removeEventListener('hashchange', onHash);
      removeEventListener('ns-theme', onTheme);
      ro?.disconnect();
      g?._destructor();
      fg.current = null;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    api(`graph?limit=${limit}${community && `&community=${community}`}`)
      .then(d => alive && setData(d), e => setError(e.message));
    return () => { alive = false; };
  }, [limit, community]);

  useEffect(() => {
    if (!ready || !data) return;
    // Nodes arrive sorted by PageRank, so the index is the rank.
    const top = data.nodes[0]?.pagerank || 1;
    data.nodes.forEach((n, i) => {
      n.rank = i;
      n.r = 2 + 10 * Math.sqrt(n.pagerank / top);
      n.key = (n.title || n.id).toLowerCase();
    });
    fg.current.graphData({ nodes: data.nodes, links: data.edges });
  }, [data, ready]);

  // Re-setting an accessor is how force-graph is told to redraw.
  useEffect(() => { fg.current?.nodeColor(color); }, [query, selected]);

  useEffect(() => {
    setNote(null);
    if (!selected) return;
    let alive = true;
    api(`notes?path=${encodeURIComponent(selected)}`)
      .then(n => alive && setNote(n), e => alive && setNote({ error: e.message }));
    return () => { alive = false; };
  }, [selected]);

  const neighbors = dir => (note?.neighbors || []).filter(x => x.direction === dir);
  const nbList = (label, list) => html`
    <div class="graph-nb">
      <${CardHeader}><${CardTitle}>${label} (${list.length})<//><//>
      ${list.map(x => html`<${Button} variant="link" onClick=${() => focus(x.path)}>${x.title || x.path}<//>`)}
    </div>`;

  return html`
    <h1 class="page-title">Graph</h1>
    ${error && html`<${Card}><${CardContent}><${Alert} variant="destructive">
      <${AlertTitle}>Graph error<//><${AlertDescription}>${error}<//>
    <//><//><//>`}
    <${Card}>
      <${CardContent} class="graph-bar">
        <${Input} type="search" placeholder="Search titles" aria-label="Search titles"
          value=${query} onInput=${e => setQuery(e.target.value)} />
        <${NativeSelect} aria-label="Node count" value=${limit} onChange=${e => setLimit(+e.target.value)}>
          ${[200, 500, 1000, 2000].map(n => html`<option value=${n}>${fmtNum(n)} notes</option>`)}
        <//>
        <${NativeSelect} aria-label="Community" value=${community} onChange=${e => setCommunity(e.target.value)}>
          <option value="">All communities</option>
          ${communities.map(c => html`
            <option value=${c.id}>${c.title || `Community ${c.id}`} (${c.member_notes})</option>`)}
        <//>
        ${data && html`<span class="sub">${
          `Showing ${fmtNum(data.nodes.length)} of ${fmtNum(data.total_nodes)} notes`
          + (data.truncated ? ', highest PageRank first' : '')}</span>`}
      <//>
    <//>
    <div class=${selected ? 'grid-2' : ''}>
      <${Card} class="graph-stage"><div class="graph-canvas" ref=${box}></div><//>
      ${selected && html`
        <${Card} class="graph-panel">
          <${CardHeader}>
            <${CardTitle}>Note<//>
            <${CardAction}>
              <${Button} variant="ghost" size="icon" class="graph-close" aria-label="Close" onClick=${() => setSelected(null)}>×<//>
            <//>
          <//>
          <${CardContent}>
            ${!note ? html`<${Loading} />`
              : note.error ? html`<${Alert} variant="destructive"><${AlertDescription}>${note.error}<//><//>`
              : html`
                <h2 class="graph-title">${note.title}</h2>
                <div class="graph-path">${note.path}</div>
                ${note.summary && html`<p class="graph-summary">${note.summary}</p>`}
                <div class="stat-strip">
                  <div class="stat"><span>PageRank</span><b>${note.pagerank.toFixed(4)}</b></div>
                  <div class="stat"><span>Status</span><b>${note.status || 'n/a'}</b></div>
                  <div class="stat"><span>Updated</span><b>${fmtAgo(note.updated_at)}</b></div>
                </div>
                ${nbList('In', neighbors('in'))}
                ${nbList('Out', neighbors('out'))}`}
          <//>
        <//>`}
    </div>`;
}

import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo } from '../api.js';
import {
  Alert, AlertDescription, AlertTitle, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle,
  Input, Label, Loading, NativeSelect, Switch, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '../components/ui.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.srch-bar { display: flex; gap: 8px; }
.srch-bar input { flex: 1 1 auto; min-width: 0; }
.srch-opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px 16px; margin-top: 16px; }
.srch-opts .native-select, .srch-opts .native-select .input { width: 100%; }
.srch-opts .label { flex-direction: column; align-items: stretch; gap: 6px; font-size: 13px; }
.srch-opts .srch-switch { flex-direction: row; align-items: center; justify-content: space-between; }
.srch-hint { font-size: 12px; font-weight: 400; color: var(--muted-foreground); }
.srch-meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.srch-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
.srch-list li { border-bottom: 1px solid var(--border); padding-bottom: 12px; }
.srch-list li:last-child { border-bottom: 0; }
.srch-title { font-weight: 500; }
.srch-path { font-size: 12px; color: var(--muted-foreground); overflow-wrap: anywhere; }
.srch-body { margin-top: 4px; font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
.srch-best { margin-left: auto; }
.srch-best[aria-pressed="true"] { background: var(--color-success); color: var(--color-success-content); border-color: transparent; }
.srch-mem { white-space: pre-wrap; overflow-wrap: anywhere; }
.srch-table { table-layout: fixed; min-width: 760px; }
.srch-table th:nth-child(2) { width: 120px; }
.srch-table th:nth-child(3) { width: 160px; }
.srch-table th:nth-child(4) { width: 80px; }
.srch-table th:nth-child(5) { width: 90px; }
</style>`);

const MODES = [['hybrid', 'Hybrid'], ['semantic', 'Meaning only'], ['keyword', 'Keyword only']];
const DEPTHS = [['full', 'Full sections'], ['summaries', 'Note summaries'], ['triples', 'Facts (triples)'], ['auto', 'Auto']];
const TOP_K = [5, 10, 20, 50];
const TYPES = ['', 'observation', 'decision', 'convention', 'learning', 'context', 'bug'];
const LIMITS = [20, 50, 100, 200];
const DEFAULTS = {
  target: 'notes', q: '', mode: 'hybrid', depth: 'full', top_k: '10', workspace: '', context: '',
  rerank: false, reference_only: false, max_tokens: '', type: '', limit: '20',
};
// Which options each target sends; the rest stay in the form but not the request.
const SENDS = {
  notes: ['q', 'mode', 'depth', 'top_k', 'workspace', 'context', 'rerank', 'reference_only', 'max_tokens'],
  memories: ['q', 'type', 'workspace', 'limit'],
};

function fromHash() {
  const p = new URLSearchParams(location.hash.split('?')[1]);
  const o = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) {
    if (!p.has(k)) continue;
    o[k] = typeof DEFAULTS[k] === 'boolean' ? p.get(k) === '1' : p.get(k);
  }
  return o;
}

function query(o) {
  const p = new URLSearchParams();
  // A switched-on rerank stays in the form but is not sent where the server refuses it.
  const skip = !(o.reference_only || o.depth === 'full') ? 'rerank' : null;
  for (const k of SENDS[o.target]) {
    if (k === skip) continue;
    const v = o[k];
    if (typeof v === 'boolean') { if (v) p.set(k, '1'); } else if (String(v).trim()) p.set(k, String(v).trim());
  }
  return p;
}

const noteLink = (path, title) => html`<a class="srch-title" href=${`#/graph?note=${encodeURIComponent(path)}`}>${title || path}</a>`;
const score = (s) => (s == null ? '' : html`<${Badge} variant="secondary">${Number(s).toFixed(3)}<//>`);

// "Best result" stores the query and the chosen note as an explicit label (#291),
// which the Tuning page learns ranking weights from. Clicking again takes it back.
function BestButton({ query, path, shown, marks, setMarks }) {
  const id = marks[path];
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    setBusy(true);
    try {
      if (id) {
        await api('feedback/undo', { feedback_id: id });
        setMarks((m) => { const n = { ...m }; delete n[path]; return n; });
      } else {
        const r = await api('feedback', { query, chosen_path: path, shown_paths: shown });
        setMarks((m) => ({ ...m, [path]: r.feedback_id }));
      }
    } finally {
      setBusy(false);
    }
  };
  return html`<${Button} size="sm" variant="outline" class="srch-best" aria-pressed=${!!id} disabled=${busy}
    title=${id ? 'Take back this label' : 'Label this note as the right answer to this search'}
    onClick=${toggle}>${id ? '✓ Best result' : 'Best result'}<//>`;
}

function NoteResults({ data, query }) {
  const { results = [], triples = [], summaries = [], chunks = [] } = data;
  const [marks, setMarks] = useState(data.marked || {});
  // One entry per note, in the order shown, so the stored rank is the note's rank.
  const shown = [...new Set([...results, ...summaries, ...chunks].map((r) => r.path || r.note))];
  if (!results.length && !triples.length && !summaries.length && !chunks.length) {
    return html`<${CardDescription} class="empty">No notes match<//>`;
  }
  return html`
    ${triples.length > 0 && html`<${CardContent}>
      <${CardTitle} class="sub">Facts<//>
      <${Table} class="srch-table"><${TableHeader}><${TableRow}>
        <${TableHead}>Fact<//><${TableHead}>Subject<//><${TableHead}>Note<//><${TableHead}>Score<//><${TableHead}><//>
      <//><//><${TableBody}>
        ${triples.map((t, i) => html`<${TableRow} key=${i}>
          <${TableCell}>${t.p} → ${t.o}<//><${TableCell}>${t.s}<//>
          <${TableCell}>${noteLink(t.note, t.title)}<//><${TableCell}>${score(t.score)}<//><${TableCell}><//>
        <//>`)}
      <//><//>
    <//>`}
    ${[...results, ...summaries, ...chunks].length > 0 && html`<${CardContent}><ol class="srch-list">
      ${[...results, ...summaries, ...chunks].map((r, i) => html`<li key=${i}>
        <div class="srch-meta">${noteLink(r.path || r.note, r.title)} ${score(r.score)}
          <${BestButton} query=${query} path=${r.path || r.note} shown=${shown} marks=${marks} setMarks=${setMarks} /></div>
        <div class="srch-path">${r.path || r.note}${r.section ? ` · ${r.section}` : ''}</div>
        ${r.summary && html`<div class="srch-body">${r.summary}</div>`}
        ${r.snippet && html`<div class="srch-body sub">${r.snippet}</div>`}
      </li>`)}
    </ol><//>`}`;
}

function MemoryResults({ data }) {
  const items = data.items || [];
  if (!items.length) return html`<${CardDescription} class="empty">No memories match<//>`;
  return html`<${Table} class="srch-table"><${TableHeader}><${TableRow}>
      <${TableHead}>Memory<//><${TableHead}>Type<//><${TableHead}>Workspace<//><${TableHead}>Score<//><${TableHead}>Created<//>
    <//><//><${TableBody}>
      ${items.map((m) => html`<${TableRow} key=${m.id}>
        <${TableCell}><div class="srch-mem">${m.content}</div>
          <div class="srch-path">#${m.id}${m.source_agent ? ` · ${m.source_agent}` : ''}${m.tags.length ? ` · ${m.tags.join(', ')}` : ''}</div><//>
        <${TableCell}><${Badge} variant="secondary">${m.entity_type}<//><//>
        <${TableCell} title=${m.workspace || ''}><span class="sub">${m.workspace || ''}</span><//>
        <${TableCell}>${score(m.score)}<//>
        <${TableCell} title=${`${m.created_at} UTC`}>${fmtAgo(m.created_at)}<//>
      <//>`)}
    <//><//>`;
}

export default function Page() {
  const [o, setO] = useState(fromHash);
  // The submitted search; `n` makes a resubmit of the same options fetch again.
  const [run, setRun] = useState(() => (o.q || o.target === 'memories'
    ? { target: o.target, qs: String(query(o)), n: 0 } : null));
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [took, setTook] = useState(null);
  const [spaces, setSpaces] = useState([]);
  const set = (k) => (v) => setO((prev) => ({ ...prev, [k]: v }));
  const onInput = (k) => (e) => set(k)(e.target.value);
  const wholeNotes = o.reference_only || o.depth === 'full';

  useEffect(() => { api('workspaces').then(setSpaces, () => {}); }, []);

  useEffect(() => {
    if (run === null) return;
    const { target, qs } = run;
    history.replaceState(null, '', `#/search?target=${target}${qs ? `&${qs}` : ''}`);
    let live = true;
    const t0 = performance.now();
    setBusy(true);
    setErr(null);
    api(`search/${target}?${qs}`).then(
      (d) => live && (setData({ target, q: new URLSearchParams(qs).get('q') || '', ...d }),
        setTook(performance.now() - t0)),
      (e) => live && (setErr(e.message), setData(null)),
    ).finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [run]);

  const submit = (e) => {
    e.preventDefault();
    if (o.target === 'notes' && !o.q.trim()) return setErr('Type something to search notes.');
    setRun({ target: o.target, qs: String(query(o)), n: (run ? run.n : 0) + 1 });
  };

  const field = (label, body, hint) => html`<${Label}>${label}${body}${hint && html`<span class="srch-hint">${hint}</span>`}<//>`;
  const select = (k, opts) => html`<${NativeSelect} value=${o[k]} onChange=${onInput(k)}>
    ${opts.map((x) => (Array.isArray(x) ? html`<option value=${x[0]}>${x[1]}</option>` : html`<option value=${x}>${x || 'Any type'}</option>`))}
  <//>`;
  const toggle = (k, label, hint, disabled) => html`<${Label} class="srch-switch">
    <span>${label}${hint && html`<br /><span class="srch-hint">${hint}</span>`}</span>
    <${Switch} checked=${o[k] && !disabled} disabled=${disabled} onCheckedChange=${set(k)} />
  <//>`;
  const workspace = field('Workspace', html`<${Input} list="srch-spaces" placeholder="Whole vault" value=${o.workspace} onInput=${onInput('workspace')} />`);

  return html`
    <h1 class="page-title">Search</h1>
    <${Card}>
      <${CardHeader}><${CardTitle}>Search the vault<//>
        <${CardDescription}>Notes use the same ranking as the vault_search tool; memories use vault_memories. Searches here do not count as note usage.<//>
      <//>
      <${CardContent}>
        <form onSubmit=${submit}>
          <${Tabs} value=${o.target} onValueChange=${set('target')}>
            <${TabsList} aria-label="What to search">
              <${TabsTrigger} value="notes">Notes<//>
              <${TabsTrigger} value="memories">Memories<//>
            <//>
            <div class="srch-bar" style="margin-top: 12px">
              <${Input} type="search" autofocus aria-label="Search text" value=${o.q} onInput=${onInput('q')}
                placeholder=${o.target === 'notes' ? 'e.g. pihole rate limit on lxc 122' : 'Leave empty to list the newest'} />
              <${Button} type="submit" disabled=${busy}>${busy ? 'Searching…' : 'Search'}<//>
            </div>
            <datalist id="srch-spaces">${spaces.map((w) => html`<option value=${w.path}>${w.notes} notes</option>`)}</datalist>
            <${TabsContent} value="notes"><div class="srch-opts">
              ${field('Mode', select('mode', MODES))}
              ${field('Depth', select('depth', DEPTHS), o.reference_only ? 'Ignored in reference mode' : '')}
              ${field('Results', select('top_k', TOP_K))}
              ${workspace}
              ${field('Context boost', html`<${Input} placeholder="Project or topic" value=${o.context} onInput=${onInput('context')} />`)}
              ${field('Max tokens', html`<${Input} type="number" min="1" placeholder="No limit" value=${o.max_tokens} onInput=${onInput('max_tokens')} />`)}
              ${toggle('rerank', 'Rerank with judge', wholeNotes ? 'Slower, more precise order' : 'Needs Full depth or reference mode', !wholeNotes)}
              ${toggle('reference_only', 'Reference only', 'Paths and snippets, no bodies')}
            </div><//>
            <${TabsContent} value="memories"><div class="srch-opts">
              ${field('Type', select('type', TYPES))}
              ${workspace}
              ${field('Results', select('limit', LIMITS))}
            </div><//>
          <//>
        </form>
      <//>
    <//>
    <${Card}>
      <${CardHeader}>
        <${CardTitle}>Results<//>
        ${data && html`<div class="srch-meta">
          ${data.depth_used && html`<${Badge} variant="secondary">${data.depth_used}<//>`}
          ${data.reranked && html`<${Badge}>reranked<//>`}
          ${data.truncated && html`<${Badge} variant="outline">trimmed to max tokens<//>`}
          ${took != null && html`<span class="sub">${(took / 1000).toFixed(2)} s</span>`}
        </div>`}
      <//>
      ${err ? html`<${CardContent}><${Alert} variant="destructive"><${AlertTitle}>Search failed<//><${AlertDescription}>${err}<//><//><//>`
        : busy && !data ? html`<${CardContent}><${Loading} /><//>`
        : !data ? html`<${CardDescription} class="empty">Type a query and press Search<//>`
        : data.target === 'notes' ? html`<${NoteResults} key=${data.q} data=${data} query=${data.q} />`
        : html`<${MemoryResults} data=${data} />`}
    <//>`;
}

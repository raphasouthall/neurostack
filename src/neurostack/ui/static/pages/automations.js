import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';
import { BentoGrid, StatTile } from '../bento.js';
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Loading,
  Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow, Tooltip, TooltipContent, TooltipTrigger,
} from '../components/ui.js';

const STYLE = `
.auto-history { display: flex; gap: 2px; }
.auto-history i { width: 8px; height: 8px; border-radius: 2px; background: var(--border); }
.auto-history i.ok { background: var(--success); }
.auto-history i.failed { background: var(--destructive); }
.auto-history i.skipped { background: var(--muted-foreground); }
.auto-history i.running { background: var(--chart-1); }
.table tr.auto-row { cursor: pointer; }
.table tr.auto-panel:hover { background: none; }
.auto-panel > td { background: var(--muted); padding: 8px 24px; }
.auto-panel .table { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-sm); }
`;
if (!document.getElementById('auto-style')) {
  document.head.append(Object.assign(document.createElement('style'), { id: 'auto-style', textContent: STYLE }));
}

const fmtDur = (s) => (s == null ? '' : s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`);
const VARIANT = { ok: 'success', failed: 'destructive' };

function Status({ status }) {
  return status ? html`<${Badge} variant=${VARIANT[status] || 'secondary'}>${status}<//>` : html`<span class="sub">never</span>`;
}

// `result` is free-form JSON per job; show its scalar fields as key=value.
function summary(run) {
  if (run.error) return html`<span class="error">${run.error}</span>`;
  const r = run.result;
  if (!r || typeof r !== 'object') return r == null ? '' : String(r);
  return Object.entries(r).filter(([, v]) => v === null || typeof v !== 'object')
    .map(([k, v]) => `${k}=${v}`).join(' ');
}

function Failed({ title, error }) {
  return html`<${Alert} variant="destructive"><${AlertTitle}>${title}<//><${AlertDescription}>${error.message}<//><//>`;
}

function Runs({ job }) {
  const [state, setState] = useState({});
  useEffect(() => {
    api(`automations/${encodeURIComponent(job)}/runs?limit=20`)
      .then((runs) => setState({ runs }), (error) => setState({ error }));
  }, [job]);
  if (state.error) return html`<${Failed} title="Could not load runs" error=${state.error} />`;
  if (!state.runs) return html`<${Loading} />`;
  if (!state.runs.length) return html`<${CardDescription} class="empty">No runs yet.<//>`;
  return html`<${Table}>
    <${TableCaption} class="sr-only">Last ${state.runs.length} runs of ${job}<//>
    <${TableBody}>
    ${state.runs.map((r) => html`<${TableRow}>
      <${TableCell}><${Status} status=${r.status} /><//>
      <${TableCell} title=${r.started_at}>${fmtAgo(r.started_at)}<//>
      <${TableCell} class="num">${fmtDur(r.duration_s)}<//>
      <${TableCell} class="sub">${summary(r)}<//>
    <//>`)}
  <//><//>`;
}

function JobRow({ job, open, toggle }) {
  // recent is newest first; pad to 14 so the newest square is always rightmost.
  const recent = (job.recent || []).slice(0, 14).reverse();
  const history = [...Array(14 - recent.length).fill(''), ...recent];
  return html`
    <${TableRow} class=${job.blocked ? 'auto-row muted' : 'auto-row'} tabIndex="0" aria-expanded=${open}
      onClick=${toggle} onKeyDown=${(e) => e.key === 'Enter' && toggle()}>
      <${TableCell}>${job.name}<div class="sub">${job.description}</div><//>
      <${TableCell}>${job.schedule}<//>
      <${TableCell} style="white-space:nowrap">${job.last ? html`<${Status} status=${job.last.status} /> <span class="sub">${fmtAgo(job.last.started_at)}</span>` : html`<${Status} />`}<//>
      <${TableCell} class="num hide-sm">${fmtDur(job.last?.duration_s)}<//>
      <${TableCell}>${job.blocked ? html`<${Tooltip}>
          <${TooltipTrigger}><${Badge} variant="warning">blocked<//><//><${TooltipContent}>${job.blocked}<//>
        <//>` : fmtAgo(job.next_due)}<//>
      <${TableCell} class="hide-sm"><div class="auto-history">${history.map((s) => html`<i class=${s} title=${s}></i>`)}</div><//>
    <//>
    ${open && html`<${TableRow} class="auto-panel"><${TableCell} colspan="6"><${Runs} job=${job.name} /><//><//>`}`;
}

export default function Page() {
  const [state, setState] = useState({});
  const [open, setOpen] = useState(null);

  useEffect(() => {
    // A failed refresh keeps the last good data on screen next to the error.
    const load = () => api('automations').then((data) => setState({ data }),
      (error) => setState((s) => ({ data: s.data, error })));
    load();
    const timer = setInterval(() => document.visibilityState === 'visible' && load(), 30000);
    return () => clearInterval(timer);
  }, []);

  const title = html`<h1 class="page-title">Automations</h1>`;
  if (!state.data) {
    return html`${title}<${Card}><${CardContent}>${state.error
      ? html`<${Failed} title="Could not load automations" error=${state.error} />` : html`<${Loading} />`}<//><//>`;
  }
  const jobs = state.data.jobs || [];
  const queues = Object.entries(state.data.queues || {});
  const failures = jobs.filter((j) => j.last?.status === 'failed').length;
  const sum = (k) => queues.reduce((n, [, q]) => n + (q[k] || 0), 0);

  return html`${title}
    <${BentoGrid}>
      <${StatTile} label="Jobs">${jobs.length}<//>
      <${StatTile} label="Last-run failures"><span class=${failures ? 'error' : ''}>${failures}</span><//>
      <${StatTile} label="Queued">${fmtNum(sum('queued'))}<//>
      <${StatTile} label="Running">${fmtNum(sum('running'))}<//>
      <${Card} class="magic-bento-card bento-full">
        ${state.error && html`<${CardContent}><${Failed} title="Refresh failed" error=${state.error} /><//>`}
        <${Table}>
          <${TableHeader}><${TableRow}>
            <${TableHead}>Job<//><${TableHead}>Schedule<//><${TableHead}>Last run<//>
            <${TableHead} class="num hide-sm">Duration<//><${TableHead}>Next due<//><${TableHead} class="hide-sm">History<//>
          <//><//>
          <${TableBody}>
            ${jobs.map((j) => html`<${JobRow} key=${j.name} job=${j} open=${open === j.name}
              toggle=${() => setOpen(open === j.name ? null : j.name)} />`)}
          <//>
        <//>
      <//>
      <${Card} class="magic-bento-card bento-full">
        <${CardHeader}><${CardTitle}>Queues<//><//>
        ${queues.length ? html`<${Table}>
          <${TableHeader}><${TableRow}>
            <${TableHead}>Queue<//><${TableHead} class="num">Queued<//><${TableHead} class="num">Running<//>
            <${TableHead} class="num">Done<//><${TableHead} class="num">Failed<//>
          <//><//>
          <${TableBody}>${queues.map(([name, q]) => html`<${TableRow}>
            <${TableCell}>${name}<//>
            <${TableCell} class="num">${fmtNum(q.queued)}<//><${TableCell} class="num">${fmtNum(q.running)}<//>
            <${TableCell} class="num">${fmtNum(q.done)}<//><${TableCell} class="num">${fmtNum(q.failed)}<//>
          <//>`)}<//>
        <//>` : html`<${CardDescription} class="empty">No queues.<//>`}
      <//>
    <//>`;
}

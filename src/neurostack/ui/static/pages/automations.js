import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';

const STYLE = `
.auto-history { display: flex; gap: 2px; }
.auto-history i { width: 8px; height: 8px; border-radius: 2px; background: var(--hairline); }
.auto-history i.ok { background: var(--ok); }
.auto-history i.failed { background: var(--failed); }
.auto-history i.skipped { background: var(--stone); }
.auto-history i.running { background: var(--running); }
.table tr.auto-row { cursor: pointer; }
.table tr.auto-panel:hover { background: none; }
.auto-panel > td { background: var(--surface-soft); padding: 8px 24px; }
.auto-panel .table { background: var(--card); border: 1px solid var(--hairline); border-radius: 8px; }
`;
if (!document.getElementById('auto-style')) {
  document.head.append(Object.assign(document.createElement('style'), { id: 'auto-style', textContent: STYLE }));
}

const fmtDur = (s) => (s == null ? '' : s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`);

function Chip({ status }) {
  return status ? html`<span class=${`chip ${status}`}>${status}</span>` : html`<span class="sub">never</span>`;
}

// `result` is free-form JSON per job; show its scalar fields as key=value.
function summary(run) {
  if (run.error) return html`<span class="error">${run.error}</span>`;
  const r = run.result;
  if (!r || typeof r !== 'object') return r == null ? '' : String(r);
  return Object.entries(r).filter(([, v]) => v === null || typeof v !== 'object')
    .map(([k, v]) => `${k}=${v}`).join(' ');
}

function Runs({ job }) {
  const [state, setState] = useState({});
  useEffect(() => {
    api(`automations/${encodeURIComponent(job)}/runs?limit=20`)
      .then((runs) => setState({ runs }), (error) => setState({ error }));
  }, [job]);
  if (state.error) return html`<div class="error">${state.error.message}</div>`;
  if (!state.runs) return html`<div class="empty">Loading…</div>`;
  if (!state.runs.length) return html`<div class="empty">No runs yet.</div>`;
  return html`<table class="table"><tbody>
    ${state.runs.map((r) => html`<tr>
      <td><${Chip} status=${r.status} /></td>
      <td title=${r.started_at}>${fmtAgo(r.started_at)}</td>
      <td class="num">${fmtDur(r.duration_s)}</td>
      <td class="sub">${summary(r)}</td>
    </tr>`)}
  </tbody></table>`;
}

function JobRow({ job, open, toggle }) {
  // recent is newest first; pad to 14 so the newest square is always rightmost.
  const recent = (job.recent || []).slice(0, 14).reverse();
  const history = [...Array(14 - recent.length).fill(''), ...recent];
  return html`
    <tr class=${job.blocked ? 'auto-row muted' : 'auto-row'} tabIndex="0" aria-expanded=${open}
      onClick=${toggle} onKeyDown=${(e) => e.key === 'Enter' && toggle()}>
      <td>${job.name}<div class="sub">${job.description}</div></td>
      <td>${job.schedule}</td>
      <td style="white-space:nowrap">${job.last ? html`<${Chip} status=${job.last.status} /> <span class="sub">${fmtAgo(job.last.started_at)}</span>` : html`<${Chip} />`}</td>
      <td class="num">${fmtDur(job.last?.duration_s)}</td>
      <td>${job.blocked || fmtAgo(job.next_due)}</td>
      <td><div class="auto-history">${history.map((s) => html`<i class=${s} title=${s}></i>`)}</div></td>
    </tr>
    ${open && html`<tr class="auto-panel"><td colspan="6"><${Runs} job=${job.name} /></td></tr>`}`;
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
    return html`${title}<div class="card"><div class="card-body">${state.error
      ? html`<div class="error">${state.error.message}</div>` : html`<div class="empty">Loading…</div>`}</div></div>`;
  }
  const jobs = state.data.jobs || [];
  const queues = Object.entries(state.data.queues || {});
  const failures = jobs.filter((j) => j.last?.status === 'failed').length;
  const sum = (k) => queues.reduce((n, [, q]) => n + (q[k] || 0), 0);

  return html`${title}
    <div class="card">
      <div class="card-body stat-strip">
        <div class="stat"><span>Jobs</span><strong>${jobs.length}</strong></div>
        <div class="stat"><span>Last-run failures</span><strong class=${failures ? 'error' : ''}>${failures}</strong></div>
        <div class="stat"><span>Queued</span><strong>${fmtNum(sum('queued'))}</strong></div>
        <div class="stat"><span>Running</span><strong>${fmtNum(sum('running'))}</strong></div>
      </div>
      ${state.error && html`<div class="card-body error">Refresh failed: ${state.error.message}</div>`}
      <table class="table">
        <thead><tr><th>Job</th><th>Schedule</th><th>Last run</th><th class="num">Duration</th><th>Next due</th><th>History</th></tr></thead>
        <tbody>
          ${jobs.map((j) => html`<${JobRow} key=${j.name} job=${j} open=${open === j.name}
            toggle=${() => setOpen(open === j.name ? null : j.name)} />`)}
        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-head">Queues</div>
      ${queues.length ? html`<table class="table">
        <thead><tr><th>Queue</th><th class="num">Queued</th><th class="num">Running</th><th class="num">Done</th><th class="num">Failed</th></tr></thead>
        <tbody>${queues.map(([name, q]) => html`<tr>
          <td>${name}</td>
          <td class="num">${fmtNum(q.queued)}</td><td class="num">${fmtNum(q.running)}</td>
          <td class="num">${fmtNum(q.done)}</td><td class="num">${fmtNum(q.failed)}</td>
        </tr>`)}</tbody>
      </table>` : html`<div class="empty">No queues.</div>`}
    </div>`;
}

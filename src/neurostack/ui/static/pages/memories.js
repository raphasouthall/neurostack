import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.mem-clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; cursor: pointer; }
.mem-full { white-space: pre-wrap; overflow-wrap: anywhere; cursor: pointer; }
.mem-table { table-layout: fixed; }
.mem-table td { overflow: hidden; text-overflow: ellipsis; }
.mem-table th:nth-child(2) { width: 120px; }
.mem-table th:nth-child(3) { width: 190px; }
.mem-table th:nth-child(4) { width: 130px; }
.mem-table th:nth-child(5) { width: 160px; }
.mem-table th:nth-child(6) { width: 90px; }
.mem-table td:nth-child(n+4) { white-space: nowrap; }
.mem-tags { display: flex; flex-wrap: wrap; gap: 2px 4px; }
.mem-tag { padding: 1px 6px; border-radius: 9999px; background: var(--surface-soft); color: var(--mute); font-size: 11px; white-space: nowrap; }
.mem-tools { display: flex; gap: 8px; }
</style>`);

const LIMITS = [50, 100, 250, 500];

const tail = (ws) => (ws ? ws.replace(/\/+$/, '').split('/').pop() : '');

export default function Page() {
  const init = new URLSearchParams(location.hash.split('?')[1]);
  const [type, setType] = useState(init.get('type') || '');
  const [text, setText] = useState(init.get('q') || '');
  const [q, setQ] = useState(text.trim());
  const [limit, setLimit] = useState(Number(init.get('limit')) || 50);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 300);
    return () => clearTimeout(t);
  }, [text]);

  // One query string drives both the fetch and the hash, so a reload keeps the filter.
  const params = new URLSearchParams();
  if (type) params.set('type', type);
  if (q) params.set('q', q);
  if (limit !== 50) params.set('limit', limit);
  const qs = String(params) && `?${params}`;

  useEffect(() => {
    // replaceState does not fire hashchange, so the router does not remount the page.
    history.replaceState(null, '', `#/memories${qs}`);
    let live = true;
    api(`memories${qs}`).then(
      (d) => live && (setData(d), setErr(null)),
      (e) => live && setErr(e.message),
    );
    return () => { live = false; };
  }, [qs]);

  const byType = data ? data.by_type : {};
  const items = data ? data.items : [];
  const toggle = (id) => setOpen(open === id ? null : id);
  const tab = (value, label, n) => html`
    <button class=${type === value ? 'tab active' : 'tab'} onClick=${() => setType(value)}>
      ${label} <span class="sub">${n == null ? '' : fmtNum(n)}</span>
    </button>`;

  return html`
    <h1 class="page-title">Memories</h1>
    <div class="tabs">
      ${tab('', 'All', data && data.total)}
      ${Object.entries(byType).map(([t, n]) => tab(t, t, n))}
    </div>
    <div class="card">
      <div class="card-head">
        <span>Memories</span>
        <span class="mem-tools">
          <input class="input" type="search" placeholder="Search memories" aria-label="Search memories"
            value=${text} onInput=${(e) => setText(e.target.value)} />
          <select class="input" aria-label="Rows to show" value=${limit}
            onChange=${(e) => setLimit(Number(e.target.value))}>
            ${LIMITS.map((n) => html`<option value=${n}>${n}</option>`)}
          </select>
        </span>
      </div>
      <div class="stat-strip">
        <div class="stat"><span>Total</span><strong>${data ? fmtNum(data.total) : ''}</strong></div>
        <div class="stat"><span>${type || 'All types'}</span>
          <strong>${data ? fmtNum(type ? byType[type] || 0 : data.total) : ''}</strong></div>
        <div class="stat"><span>Shown</span><strong>${data ? fmtNum(items.length) : ''}</strong></div>
      </div>
      ${err ? html`<div class="error">${err}</div>`
        : !data ? html`<div class="empty">Loading</div>`
        : !items.length ? html`<div class="empty">No memories match</div>`
        : html`
        <table class="table mem-table">
          <thead><tr><th>Memory</th><th>Type</th><th>Tags</th><th>Workspace</th><th>Source</th><th>Created</th></tr></thead>
          <tbody>
            ${items.map((m) => {
              const tags = m.tags.filter((t) => t.trim());
              return html`
              <tr key=${m.id} tabindex="0" aria-expanded=${open === m.id} onClick=${() => toggle(m.id)}
                onKeyDown=${(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), toggle(m.id))}>
                <td><div class=${open === m.id ? 'mem-full' : 'mem-clamp'}>${m.content}</div></td>
                <td><span class="chip">${m.entity_type}</span></td>
                <td title=${tags.join(', ')}><div class="mem-tags">
                  ${tags.slice(0, 3).map((t) => html`<span class="mem-tag">${t}</span>`)}
                  ${tags.length > 3 && html`<span class="mem-tag">+${tags.length - 3}</span>`}
                </div></td>
                <td><span class="sub" title=${m.workspace || ''}>${tail(m.workspace)}</span></td>
                <td title=${m.source_agent}>${m.source_agent}</td>
                <td title=${`${m.created_at} UTC`}>${fmtAgo(m.created_at)}</td>
              </tr>`;
            })}
          </tbody>
        </table>`}
    </div>`;
}

import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';
import { BentoGrid, StatTile } from '../bento.js';
import {
  Alert, AlertDescription, AlertTitle, Badge, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle,
  Input, Loading, NativeSelect, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '../components/ui.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.mem-clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; cursor: pointer; }
.mem-full { white-space: pre-wrap; overflow-wrap: anywhere; cursor: pointer; }
.mem-table { table-layout: fixed; min-width: 880px; }
.mem-table td { overflow: hidden; text-overflow: ellipsis; }
.mem-table th:nth-child(2) { width: 120px; }
.mem-table th:nth-child(3) { width: 190px; }
.mem-table th:nth-child(4) { width: 130px; }
.mem-table th:nth-child(5) { width: 160px; }
.mem-table th:nth-child(6) { width: 90px; }
.mem-table td:nth-child(n+4) { white-space: nowrap; }
.mem-tags { display: flex; flex-wrap: wrap; gap: 2px 4px; }
/* Block, not flex, so a long tag ends in an ellipsis. */
.mem-tag { display: inline-block; padding: 1px 6px; font-size: 11px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.mem-tools input { min-width: 0; flex: 1 1 160px; }
@media (max-width: 768px) { .mem-table { min-width: 560px; } }
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
    <${TabsTrigger} value=${value}>${label} <span class="sub">${n == null ? '' : fmtNum(n)}</span><//>`;

  return html`
    <h1 class="page-title">Memories</h1>
    <${Tabs} value=${type} onValueChange=${setType}>
      <${TabsList} aria-label="Memory type">
        ${tab('', 'All', data && data.total)}
        ${Object.entries(byType).map(([t, n]) => tab(t, t, n))}
      <//>
      <${TabsContent} value=${type}>
        <${BentoGrid} className="cols-3">
          <${StatTile} label="Total">${data ? fmtNum(data.total) : ''}<//>
          <${StatTile} label=${type || 'All types'}>${data ? fmtNum(type ? byType[type] || 0 : data.total) : ''}<//>
          <${StatTile} label="Shown">${data ? fmtNum(items.length) : ''}<//>
          <${Card} class="magic-bento-card bento-full">
            <${CardHeader}>
              <${CardTitle}>Memories<//>
              <${CardAction} class="mem-tools">
                <${Input} type="search" placeholder="Search memories" aria-label="Search memories"
                  value=${text} onInput=${(e) => setText(e.target.value)} />
                <${NativeSelect} aria-label="Rows to show" value=${limit} onChange=${(e) => setLimit(Number(e.target.value))}>
                  ${LIMITS.map((n) => html`<option value=${n}>${n}</option>`)}
                <//>
              <//>
            <//>
            ${err ? html`<${CardContent}><${Alert} variant="destructive">
                <${AlertTitle}>Could not load memories<//><${AlertDescription}>${err}<//>
              <//><//>`
              : !data ? html`<${CardContent}><${Loading} /><//>`
              : !items.length ? html`<${CardDescription} class="empty">No memories match<//>`
              : html`
              <${Table} class="mem-table">
                <${TableHeader}><${TableRow}>
                  <${TableHead}>Memory<//><${TableHead}>Type<//><${TableHead}>Tags<//>
                  <${TableHead} class="hide-sm">Workspace<//><${TableHead} class="hide-sm">Source<//><${TableHead}>Created<//>
                <//><//>
                <${TableBody}>
                  ${items.map((m) => {
                    const tags = m.tags.filter((t) => t.trim());
                    return html`
                    <${TableRow} key=${m.id} tabindex="0" aria-expanded=${open === m.id} onClick=${() => toggle(m.id)}
                      onKeyDown=${(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), toggle(m.id))}>
                      <${TableCell}><div class=${open === m.id ? 'mem-full' : 'mem-clamp'}>${m.content}</div><//>
                      <${TableCell}><${Badge} variant="secondary">${m.entity_type}<//><//>
                      <${TableCell} title=${tags.join(', ')}><div class="mem-tags">
                        ${tags.slice(0, 3).map((t) => html`<${Badge} variant="secondary" class="mem-tag">${t}<//>`)}
                        ${tags.length > 3 && html`<${Badge} variant="secondary" class="mem-tag">+${tags.length - 3}<//>`}
                      </div><//>
                      <${TableCell} class="hide-sm"><span class="sub" title=${m.workspace || ''}>${tail(m.workspace)}</span><//>
                      <${TableCell} class="hide-sm" title=${m.source_agent}>${m.source_agent}<//>
                      <${TableCell} title=${`${m.created_at} UTC`}>${fmtAgo(m.created_at)}<//>
                    <//>`;
                  })}
                <//>
              <//>`}
          <//>
        <//>
      <//>
    <//>`;
}

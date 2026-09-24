import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';
import { BentoGrid } from '../bento.js';
import {
  Alert, AlertDescription, AlertTitle, Card, CardContent, CardDescription, CardHeader, CardTitle, Loading,
  Table, TableBody, TableCell, TableRow, Tooltip, TooltipContent, TooltipTrigger,
} from '../components/ui.js';

// Each endpoint loads on its own, so a failing one leaves the other cards up.
function useApi(path) {
  const [state, setState] = useState({});
  useEffect(() => {
    api(path).then((data) => setState({ data }), (error) => setState({ error }));
  }, [path]);
  return state;
}

function Tile({ label, class: c = '', children }) {
  return html`<${Card} class=${`magic-bento-card ${c}`}>
    <${CardHeader}><${CardTitle}>${label}<//><//>
    <${CardContent}>${children}<//>
  <//>`;
}

// parts: [label, value, width %]; widths fill the bar in the order c1, c2, c3.
function Bar({ parts }) {
  return html`
    <div class="bar">${parts.map(([, , w], i) => html`<span class=${`c${i + 1}`} style=${`width:${w}%`}></span>`)}</div>
    <div class="legend">${parts.map(([label, value], i) => html`<span><i class=${`c${i + 1}`}></i>${label} ${value}</span>`)}</div>`;
}

function Rows({ rows }) {
  return html`<${Table}><${TableBody}>
    ${rows.map(([label, value]) => html`<${TableRow}><${TableCell}>${label}<//><${TableCell} class="num">${value}<//><//>`)}
  <//><//>`;
}

function Status({ state }) {
  return state.error ? html`<${Alert} variant="destructive">
      <${AlertTitle}>Could not load<//><${AlertDescription}>${state.error.message}<//>
    <//>` : html`<${Loading} />`;
}

function Index({ stats }) {
  const cov = [['Embeddings', stats.embedding_coverage], ['Summaries', stats.summary_coverage],
    ['Triples', stats.triple_coverage]];
  // Each coverage fills a third of the bar, so a full bar means all three are complete.
  const parts = cov.map(([label, pct]) => [label, pct ?? '0%', (parseFloat(pct) || 0) / 3]);
  return html`<${Tile} label="Index">
    <div class="big-num">${fmtNum(stats.notes ?? 0)}</div>
    <${CardDescription}>notes, ${fmtNum(stats.chunks ?? 0)} chunks, ${fmtNum(stats.graph_edges ?? 0)} links<//>
    <div style="margin-top:16px"><${Bar} parts=${parts} /></div>
  <//>`;
}

function Communities({ stats }) {
  const build = stats.community_build || {};
  return html`<${Tile} label="Communities">
    <div class="stat-strip">
      <div class="stat"><span>Coarse</span><b>${fmtNum(stats.communities_coarse ?? 0)}</b></div>
      <div class="stat"><span>Fine</span><b>${fmtNum(stats.communities_fine ?? 0)}</b></div>
      <div class="stat"><span>Summarised</span><b>${fmtNum(stats.communities_summarized ?? 0)}</b></div>
    </div>
    ${build.last_built && html`<div class="sub" style="margin-top:10px">Built ${fmtAgo(build.last_built)}</div>`}
    ${build.stale && build.reason && html`<${CardDescription} style="margin-top:10px">${build.reason}<//>`}
  <//>`;
}

function Recent({ notes }) {
  return html`<${Card} class="magic-bento-card bento-full">
    <${CardHeader}><${CardTitle}>Recently changed<//><//>
    ${notes.length ? html`<${Table}><${TableBody}>
      ${notes.map((n) => html`<${TableRow}>
        <${TableCell} class="wrap"><a href=${`#/graph?note=${encodeURIComponent(n.path)}`}>${n.title || n.path}</a><//>
        <${TableCell} class="num sub" style="white-space:nowrap">${fmtAgo(n.updated_at)}<//>
      <//>`)}
    <//><//>` : html`<${CardDescription} class="empty">No notes indexed yet.<//>`}
  <//>`;
}

// The cobalt card is the large bento tile. A blocked job shows why in its tooltip.
function Automations({ state }) {
  if (!state.data) return html`<${Tile} label="Automations" class="accent bento-lg"><${Status} state=${state} /><//>`;
  const jobs = state.data.jobs || [];
  const count = (s) => jobs.filter((j) => j.last?.status === s).length;
  const ok = count('ok'), failed = count('failed'), other = jobs.length - ok - failed;
  const pct = (n) => (jobs.length ? (n / jobs.length) * 100 : 0);
  return html`<${Tile} label="Automations" class="accent bento-lg">
    <h2 class="accent-title">${failed ? `${failed} failing` : 'All healthy'}</h2>
    <${Bar} parts=${[['ok', ok, pct(ok)], ['failed', failed, pct(failed)], ['other', other, pct(other)]]} />
    <div class="sub" style="margin-top:12px"><a href="#/automations">Last run of ${jobs.length} jobs</a></div>
    <ul class="accent-jobs">
      ${jobs.map((j) => html`<li>
        <i class=${j.last?.status || ''} title=${j.last?.status || 'never run'}></i>
        <span>${j.name}</span>
        <span>${j.last ? fmtAgo(j.last.started_at) : 'never'}</span>
        ${j.blocked ? html`<${Tooltip}><${TooltipTrigger}>blocked<//><${TooltipContent}>${j.blocked}<//><//>`
          : html`<span>${fmtAgo(j.next_due)}</span>`}
      </li>`)}
    </ul>
  <//>`;
}

export default function Page() {
  const ov = useApi('overview');
  const auto = useApi('automations');
  const stats = ov.data?.stats || {};
  const mem = ov.data?.memories || {};
  const exc = stats.excitability || {};
  return html`
    <h1 class="page-title">Overview</h1>
    <${BentoGrid}>
      <${Automations} state=${auto} />
      ${ov.data ? html`
        <${Index} stats=${stats} />
        <${Communities} stats=${stats} />
        <${Tile} label="Memories">
          <div class="big-num">${fmtNum(mem.total ?? 0)}</div>
          <${Rows} rows=${Object.entries(mem.by_type || {}).map(([t, n]) => [t, fmtNum(n)])} />
        <//>
        <${Tile} label="Excitability">
          <${Rows} rows=${[['Active', fmtNum(exc.active ?? 0)], ['Dormant', fmtNum(exc.dormant ?? 0)],
            ['Never used', fmtNum(exc.never_used ?? 0)]]} />
        <//>
        <${Recent} notes=${ov.data.recent_notes || []} />`
      : html`<${Card} class="magic-bento-card bento-full"><${CardContent}><${Status} state=${ov} /><//><//>`}
    <//>`;
}

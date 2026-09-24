import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';

// Each endpoint loads on its own, so a failing one leaves the other cards up.
function useApi(path) {
  const [state, setState] = useState({});
  useEffect(() => {
    api(path).then((data) => setState({ data }), (error) => setState({ error }));
  }, [path]);
  return state;
}

function Card({ label, accent, children }) {
  return html`<div class=${accent ? 'card accent' : 'card'}>
    <div class="card-head">${label}</div>
    <div class="card-body">${children}</div>
  </div>`;
}

// parts: [label, value, width %]; widths fill the bar in the order c1, c2, c3.
function Bar({ parts }) {
  return html`
    <div class="bar">${parts.map(([, , w], i) => html`<span class=${`c${i + 1}`} style=${`width:${w}%`}></span>`)}</div>
    <div class="legend">${parts.map(([label, value], i) => html`<span><i class=${`c${i + 1}`}></i>${label} ${value}</span>`)}</div>`;
}

function Rows({ rows }) {
  return html`<table class="table"><tbody>
    ${rows.map(([label, value]) => html`<tr><td>${label}</td><td class="num">${value}</td></tr>`)}
  </tbody></table>`;
}

function Status({ state }) {
  return state.error ? html`<div class="error">${state.error.message}</div>` : html`<div class="empty">Loading…</div>`;
}

function Index({ stats }) {
  const cov = [['Embeddings', stats.embedding_coverage], ['Summaries', stats.summary_coverage],
    ['Triples', stats.triple_coverage]];
  // Each coverage fills a third of the bar, so a full bar means all three are complete.
  const parts = cov.map(([label, pct]) => [label, pct ?? '0%', (parseFloat(pct) || 0) / 3]);
  return html`<${Card} label="Index">
    <div class="big-num">${fmtNum(stats.notes ?? 0)}</div>
    <div class="sub">notes, ${fmtNum(stats.chunks ?? 0)} chunks, ${fmtNum(stats.graph_edges ?? 0)} links</div>
    <div style="margin-top:16px"><${Bar} parts=${parts} /></div>
  <//>`;
}

function Communities({ stats }) {
  const build = stats.community_build || {};
  return html`<${Card} label="Communities">
    <div class="stat-strip">
      <div class="stat"><span>Coarse</span><b>${fmtNum(stats.communities_coarse ?? 0)}</b></div>
      <div class="stat"><span>Fine</span><b>${fmtNum(stats.communities_fine ?? 0)}</b></div>
      <div class="stat"><span>Summarised</span><b>${fmtNum(stats.communities_summarized ?? 0)}</b></div>
    </div>
    ${build.last_built && html`<div class="sub" style="margin-top:10px">Built ${fmtAgo(build.last_built)}</div>`}
    ${build.stale && build.reason && html`<div class="sub" style="margin-top:10px">${build.reason}</div>`}
  <//>`;
}

function Recent({ notes }) {
  return html`<div class="card">
    <div class="card-head">Recently changed</div>
    ${notes.length ? html`<table class="table"><tbody>
      ${notes.map((n) => html`<tr>
        <td><a href=${`#/graph?note=${encodeURIComponent(n.path)}`}>${n.title || n.path}</a></td>
        <td class="num sub">${fmtAgo(n.updated_at)}</td>
      </tr>`)}
    </tbody></table>` : html`<div class="empty">No notes indexed yet.</div>`}
  </div>`;
}

function Automations({ state }) {
  if (!state.data) return html`<${Card} label="Automations" accent><${Status} state=${state} /><//>`;
  const jobs = state.data.jobs || [];
  const count = (s) => jobs.filter((j) => j.last?.status === s).length;
  const ok = count('ok'), failed = count('failed'), other = jobs.length - ok - failed;
  const pct = (n) => (jobs.length ? (n / jobs.length) * 100 : 0);
  return html`<${Card} label="Automations" accent>
    <h2 class="accent-title">${failed ? `${failed} failing` : 'All healthy'}</h2>
    <${Bar} parts=${[['ok', ok, pct(ok)], ['failed', failed, pct(failed)], ['other', other, pct(other)]]} />
    <div class="sub" style="margin-top:12px"><a href="#/automations">Last run of ${jobs.length} jobs</a></div>
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
    <div class="grid-2">
      <div>
        ${ov.data ? html`
          <${Index} stats=${stats} />
          <${Communities} stats=${stats} />
          <${Recent} notes=${ov.data.recent_notes || []} />`
        : html`<div class="card"><div class="card-body"><${Status} state=${ov} /></div></div>`}
      </div>
      <div>
        <${Automations} state=${auto} />
        ${ov.data && html`
          <${Card} label="Memories">
            <div class="big-num">${fmtNum(mem.total ?? 0)}</div>
            <${Rows} rows=${Object.entries(mem.by_type || {}).map(([t, n]) => [t, fmtNum(n)])} />
          <//>
          <${Card} label="Excitability">
            <${Rows} rows=${[['Active', fmtNum(exc.active ?? 0)], ['Dormant', fmtNum(exc.dormant ?? 0)],
              ['Never used', fmtNum(exc.never_used ?? 0)]]} />
          <//>`}
      </div>
    </div>`;
}

import { html, useState, useEffect } from '../lib.js';
import { api, fmtAgo, fmtNum } from '../api.js';
import { BentoGrid, StatTile } from '../bento.js';
import {
  Alert, AlertDescription, AlertTitle, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle,
  Loading, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '../components/ui.js';

document.head.insertAdjacentHTML('beforeend', `<style>
.tune-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.tune-changed { font-weight: 600; color: var(--primary); }
.tune-steps { margin: 0; padding-left: 20px; display: grid; gap: 6px; }
</style>`);

// Weight names as a person reads them.
const NAMES = {
  convergence_weight: 'Several matching sections in one note',
  hotness_weight: 'Notes you use often',
  primed_weight: 'Notes shown to agents recently',
  inhibition_threshold: 'How similar two results must be to count as repeats',
  inhibition_strength: 'How hard repeats are pushed down',
  cooccurrence_boost_weight: 'Notes sharing entities with other results',
  link_section_penalty: 'Link lists (1 = no penalty)',
};
const pct = (x) => (x == null ? '' : `${(x * 100).toFixed(1)}%`);
const num = (x) => (x == null ? '' : Number(x).toFixed(2));

export default function Page() {
  const [s, setS] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api('tune').then((d) => (setS(d), setErr(null)), (e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  const running = s && s.runs.some((r) => r.status === 'running');
  // Poll while a run is going; it takes minutes.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [running]);

  const act = (path, body) => async () => {
    setBusy(true);
    try {
      const d = await api(path, body || {});
      if (d.runs) setS(d); else await load();
      setErr(null);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!s) return html`<h1 class="page-title">Tuning</h1>${err
    ? html`<${Alert} variant="destructive"><${AlertTitle}>Could not load tuning<//><${AlertDescription}>${err}<//><//>`
    : html`<${Loading} />`}`;

  const latest = s.runs[0];
  const done = s.runs.find((r) => r.status === 'done');
  const gain = (r) => r && r.holdout_tuned - r.holdout_baseline;
  const canApply = done && gain(done) > 0 && s.applied?.run_id !== done.run_id;
  const enough = s.labels >= s.min_labels;

  return html`
    <h1 class="page-title">Tuning</h1>
    <${BentoGrid} className="cols-3">
      <${StatTile} label="Labels">${fmtNum(s.labels)}<//>
      <${StatTile} label="Marked by you">${fmtNum(s.explicit_labels)}<//>
      <${StatTile} label="Weights in use">${s.applied ? `Tuned (run ${s.applied.run_id})` : 'Config defaults'}<//>
      <${Card} class="bento-full">
        <${CardHeader}><${CardTitle}>How it works<//><//>
        <${CardContent}>
          <ol class="tune-steps">
            <li>On the Search page, press <b>Best result</b> on the note that answers your search. Each press is a label.</li>
            <li>Press <b>Run tuning</b>. It tries weight settings on half the labels and checks the winner on the other half.</li>
            <li>If the winner ranks the right notes higher on labels it never saw, press <b>Apply</b>. Every search uses it at once.</li>
            <li><b>Revert</b> goes back to the config weights.</li>
          </ol>
          <p class="sub">Labels also come from notes you open right after a search. Your own marks replace those for the same search.</p>
          ${err && html`<${Alert} variant="destructive"><${AlertTitle}>That did not work<//><${AlertDescription}>${err}<//><//>`}
          <div class="tune-actions">
            <${Button} disabled=${busy || running || !enough} onClick=${act('tune')}>${running ? 'Tuning…' : 'Run tuning'}<//>
            <${Button} variant="outline" disabled=${busy || !canApply} onClick=${act('tune/apply', { run_id: done?.run_id })}>
              Apply run ${done?.run_id ?? ''}<//>
            <${Button} variant="outline" disabled=${busy || !s.applied} onClick=${act('tune/revert')}>Revert to config<//>
            ${!enough && html`<span class="sub">Needs ${s.min_labels} labels to run; you have ${s.labels}.</span>`}
            ${done && !(gain(done) > 0) && html`<span class="sub">The last run found nothing better, so there is nothing to apply.</span>`}
          </div>
        <//>
      <//>
      <${Card} class="bento-full">
        <${CardHeader}><${CardTitle}>Weights<//>
          <${CardDescription}>In use now, and what the latest finished run would change.<//><//>
        <${Table}>
          <${TableHeader}><${TableRow}>
            <${TableHead}>Weight<//><${TableHead}>Config<//><${TableHead}>In use<//><${TableHead}>Run ${done?.run_id ?? ''}<//>
          <//><//>
          <${TableBody}>
            ${s.weights.map((w) => {
              const t = done?.tuned_weights?.[w.name];
              return html`<${TableRow} key=${w.name}>
                <${TableCell} title=${w.name}>${NAMES[w.name] || w.name}<//>
                <${TableCell}>${num(w.config)}<//>
                <${TableCell}>${num(w.active)}<//>
                <${TableCell} class=${t != null && t !== w.active ? 'tune-changed' : ''}>${num(t)}<//>
              <//>`;
            })}
          <//>
        <//>
      <//>
      <${Card} class="bento-full">
        <${CardHeader}><${CardTitle}>Runs<//>
          <${CardDescription}>Score is ${s.metric.toUpperCase()}@${s.k}: 100% means the right note is always first.<//><//>
        ${!s.runs.length ? html`<${CardDescription} class="empty">No runs yet<//>` : html`
        <${Table}>
          <${TableHeader}><${TableRow}>
            <${TableHead}>Run<//><${TableHead}>Status<//><${TableHead}>Labels<//>
            <${TableHead}>Unseen labels, before → after<//><${TableHead}>Started<//>
          <//><//>
          <${TableBody}>
            ${s.runs.map((r) => html`<${TableRow} key=${r.run_id}>
              <${TableCell}>${r.run_id}${s.applied?.run_id === r.run_id ? html` <${Badge}>applied<//>` : ''}<//>
              <${TableCell} title=${r.error || ''}><${Badge} variant=${r.status === 'failed' ? 'destructive' : 'secondary'}>${r.status}<//><//>
              <${TableCell}>${r.labels} (${r.explicit_labels} yours)<//>
              <${TableCell}>${r.status === 'done' ? `${pct(r.holdout_baseline)} → ${pct(r.holdout_tuned)}` : r.error || ''}<//>
              <${TableCell} title=${`${r.started_at} UTC`}>${fmtAgo(r.started_at)}<//>
            <//>`)}
          <//>
        <//>`}
      <//>
    <//>`;
}

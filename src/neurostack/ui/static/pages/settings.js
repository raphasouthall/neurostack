import { html, useState, useEffect } from '../lib.js';
import { BentoGrid, getSettings, saveSettings, resetSettings } from '../bento.js';
import { chooseTheme } from '../app.js';
import { THEMES, THEME_KEY } from '../themes.js';
import {
  Button, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, Label, Switch,
  ToggleGroup, ToggleGroupItem,
} from '../components/ui.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.set-list { display: grid; gap: 4px 24px; grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr)); }
.set-row { justify-content: space-between; gap: 12px; min-height: 52px; font-weight: 400; cursor: pointer; }
.set-row .sub { display: block; }
.set-effect-note { margin-top: 12px; }
/* Each tile carries its own data-theme, so it paints in that theme's colours. The
   selection ring uses --ring, inherited from the page's theme. */
.theme-grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
.theme-grid .toggle-group-item.theme-tile { display: flex; align-items: center; justify-content: space-between; gap: 8px;
  height: auto; padding: 10px 12px; border-radius: var(--radius-sm); font-weight: 500;
  background: var(--color-base-100); color: var(--color-base-content);
  border: 1px solid color-mix(in oklab, var(--color-base-content) 15%, transparent); }
.theme-grid .toggle-group-item.theme-tile[aria-pressed="true"] { outline: 2px solid var(--ring); outline-offset: 2px; }
.theme-dots { display: flex; gap: 3px; }
.theme-dots i { width: 8px; height: 18px; border-radius: 4px; }
.set-sample { font-size: 16px; font-weight: 600; margin: 4px 0; }
</style>`);

const TOGGLES = [
  ['enableBorderGlow', 'Border glow', 'The card edge nearest the cursor lights up'],
  ['enableTilt', 'Tilt', 'Cards lean toward the cursor'],
  ['clickEffect', 'Click ripple', 'A ripple spreads from each click'],
  ['textAutoHide', 'Text auto-hide', 'Card titles keep to one line and descriptions to two'],
  ['disableAnimations', 'Disable animations', 'Turns every effect off'],
];
const SAMPLES = [
  ['Insights', 'Hover here to see the glow in the theme accent, and click for the ripple.'],
  ['Graph', 'Every wiki link between notes, ranked by PageRank so the hubs stand out first.'],
  ['Memories', 'What your agents learned in past sessions, kept, typed and searchable from any client.'],
];

const storedTheme = () => localStorage.getItem(THEME_KEY) || 'system';

export default function Page() {
  const [s, setS] = useState(getSettings);
  const [theme, setTheme] = useState(storedTheme);
  useEffect(() => {
    const onBento = () => setS(getSettings());
    const onTheme = () => setTheme(storedTheme());
    addEventListener('ns-bento', onBento);
    addEventListener('ns-theme', onTheme);
    return () => {
      removeEventListener('ns-bento', onBento);
      removeEventListener('ns-theme', onTheme);
    };
  }, []);
  const set = (key, value) => saveSettings({ ...s, [key]: value });
  const tile = (value, label, theme) => html`
    <${ToggleGroupItem} class="theme-tile" value=${value} data-theme=${theme}>
      <span>${label}</span>
      <span class="theme-dots" aria-hidden="true">
        <i style="background:var(--color-primary)" /><i style="background:var(--color-secondary)" />
        <i style="background:var(--color-accent)" /><i style="background:var(--color-neutral)" />
      </span>
    <//>`;

  return html`
    <h1 class="page-title">Settings</h1>
    <${BentoGrid}>
      <${Card} class="magic-bento-card bento-lg">
        <${CardHeader}><${CardTitle}>Effects<//><//>
        <${CardContent}>
          <div class="set-list">
            ${TOGGLES.map(([key, label, hint]) => html`
              <${Label} class="set-row">
                <span>${label}<span class="sub">${hint}</span></span>
                <${Switch} checked=${s[key]} onCheckedChange=${(v) => set(key, v)} />
              <//>`)}
          </div>
          <${CardDescription} class="set-effect-note">Effects take the theme's accent colour.<//>
        <//>
        <${CardFooter}><${Button} variant="secondary" onClick=${resetSettings}>Reset to defaults<//><//>
      <//>
      ${SAMPLES.map(([title, text]) => html`
        <${Card} class="magic-bento-card">
          <${CardContent}>
            <div class="sub">Preview</div>
            <${CardTitle} class="set-sample">${title}<//>
            <${CardDescription}>${text}<//>
          <//>
        <//>`)}
      <${Card} class="bento-full">
        <${CardHeader}><${CardTitle}>Theme<//>
          <${CardDescription}>daisyUI themes. System follows the light or dark setting of your OS.<//>
        <//>
        <${CardContent}>
          <${ToggleGroup} class="theme-grid" aria-label="Theme" value=${theme} onValueChange=${chooseTheme}>
            ${tile('system', 'System', matchMedia('(prefers-color-scheme: dark)').matches ? 'neurostack-dark' : 'neurostack')}
            ${THEMES.map(([name, label]) => tile(name, label, name))}
          <//>
        <//>
      <//>
    <//>`;
}

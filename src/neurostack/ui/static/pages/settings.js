import { html, useState, useEffect } from '../lib.js';
import { BentoGrid, getSettings, saveSettings, resetSettings } from '../bento.js';
import { chooseTheme } from '../app.js';
import {
  Button, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, Input, Label, Separator, Slider, Switch,
  ToggleGroup, ToggleGroupItem,
} from '../components/ui.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.set-list { display: grid; gap: 4px 24px; grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr)); }
.set-row { justify-content: space-between; gap: 12px; min-height: 52px; font-weight: 400; cursor: pointer; }
.set-row .sub { display: block; }
.set-sep { margin-top: 16px; }
.set-range { display: grid; gap: 4px; margin-top: 16px; }
.set-range .label { font-weight: 400; }
.set-range > div { display: flex; justify-content: space-between; gap: 8px; }
.set-colors { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 16px; }
.set-colors > span { margin-right: auto; }
.set-color { width: 44px; height: 32px; padding: 0; border-radius: var(--radius-sm); background: none; cursor: pointer; }
.swatch { width: 28px; height: 28px; padding: 0; border: 2px solid var(--card); border-radius: 50%;
  box-shadow: 0 0 0 1px var(--border); }
.swatch[aria-pressed="true"] { box-shadow: 0 0 0 2px var(--foreground); }
.set-theme { margin-bottom: 16px; }
.set-sample { font-size: 16px; font-weight: 600; margin: 4px 0; }
</style>`);

const TOGGLES = [
  ['enableStars', 'Stars', 'Particles drift over the hovered card'],
  ['enableSpotlight', 'Spotlight', 'A soft light follows the cursor across the grid'],
  ['enableBorderGlow', 'Border glow', 'The card edge nearest the cursor lights up'],
  ['enableTilt', 'Tilt', 'Cards lean toward the cursor'],
  ['enableMagnetism', 'Magnetism', 'Cards drift a little toward the cursor'],
  ['clickEffect', 'Click ripple', 'A ripple spreads from each click'],
  ['textAutoHide', 'Text auto-hide', 'Card titles keep to one line and descriptions to two'],
  ['disableAnimations', 'Disable animations', 'Turns every effect off'],
];
const SWATCHES = [['Cobalt', '73, 79, 223'], ['Teal', '0, 168, 126'], ['Pink', '230, 30, 73'],
  ['Orange', '236, 126, 0'], ['Purple', '132, 0, 255']];
const THEMES = [['light', 'Light'], ['dark', 'Dark'], ['system', 'System']];
const SAMPLES = [
  ['Insights', 'Hover here to see the stars, the glow and the spotlight, and click for the ripple.'],
  ['Graph', 'Every wiki link between notes, ranked by PageRank so the hubs stand out first.'],
  ['Memories', 'What your agents learned in past sessions, kept, typed and searchable from any client.'],
];

// The glow colour is stored as "r, g, b" so CSS can add its own alpha.
const toHex = (rgb) => `#${rgb.split(',').map((n) => (+n).toString(16).padStart(2, '0')).join('')}`;
const toRgb = (hex) => hex.slice(1).match(/../g).map((h) => parseInt(h, 16)).join(', ');
const storedTheme = () => localStorage.getItem('ns_theme') || 'system';

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
  const range = (key, label, min, max, step, unit) => html`
    <div class="set-range">
      <div><${Label} for=${`set-${key}`}>${label}<//><output class="sub" for=${`set-${key}`}>${s[key]}${unit}</output></div>
      <${Slider} id=${`set-${key}`} min=${min} max=${max} step=${step} value=${s[key]} onValueChange=${(v) => set(key, v)} />
    </div>`;

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
          <${Separator} class="set-sep" />
          ${range('spotlightRadius', 'Spotlight radius', 100, 600, 10, 'px')}
          ${range('particleCount', 'Particles', 0, 40, 1, '')}
          <div class="set-colors">
            <span>Glow colour</span>
            <${ToggleGroup} aria-label="Glow colour" value=${s.glowColor} onValueChange=${(rgb) => set('glowColor', rgb)}>
              ${SWATCHES.map(([name, rgb]) => html`
                <${ToggleGroupItem} class="swatch" value=${rgb} aria-label=${name} title=${name}
                  style=${`background:rgb(${rgb})`} />`)}
            <//>
            <${Input} class="set-color" type="color" aria-label="Custom glow colour" value=${toHex(s.glowColor)}
              onInput=${(e) => set('glowColor', toRgb(e.target.value))} />
          </div>
        <//>
        <${CardFooter}><${Button} variant="secondary" onClick=${resetSettings}>Reset to defaults<//><//>
      <//>
      <${Card} class="magic-bento-card">
        <${CardHeader}><${CardTitle}>Appearance<//><//>
        <${CardContent}>
          <${ToggleGroup} class="set-theme" aria-label="Theme" value=${theme} onValueChange=${chooseTheme}>
            ${THEMES.map(([value, label]) => html`<${ToggleGroupItem} value=${value}>${label}<//>`)}
          <//>
          <${CardDescription}>System follows the light or dark setting of your OS.<//>
        <//>
      <//>
      ${SAMPLES.map(([title, text]) => html`
        <${Card} class="magic-bento-card">
          <${CardContent}>
            <div class="sub">Preview</div>
            <${CardTitle} class="set-sample">${title}<//>
            <${CardDescription}>${text}<//>
          <//>
        <//>`)}
    <//>`;
}

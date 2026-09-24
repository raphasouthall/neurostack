import { html, useState, useEffect } from '../lib.js';
import { BentoGrid, getSettings, saveSettings, resetSettings } from '../bento.js';
import { chooseTheme } from '../app.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.set-list { display: grid; gap: 4px 24px; grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr)); }
.set-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 52px; cursor: pointer; }
.set-row .sub { display: block; }
.switch { appearance: none; flex: none; position: relative; width: 40px; height: 24px; margin: 0; border-radius: 9999px;
  background: var(--faint); cursor: pointer; transition: background .2s; }
.switch::before { content: ""; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%;
  background: #fff; transition: translate .2s; }
.switch:checked { background: var(--primary); }
.switch:checked::before { translate: 16px 0; }
.set-range { display: grid; gap: 4px; margin-top: 16px; }
.set-range > div { display: flex; justify-content: space-between; gap: 8px; }
.set-range input { width: 100%; accent-color: var(--primary); }
.set-colors { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 16px 0 24px; }
.set-colors > span { margin-right: auto; }
.set-color { width: 44px; height: 32px; padding: 0; border: 1px solid var(--hairline); border-radius: 8px; background: none; cursor: pointer; }
.swatch { width: 28px; height: 28px; padding: 0; border: 2px solid var(--card); border-radius: 50%; cursor: pointer;
  box-shadow: 0 0 0 1px var(--hairline); }
.swatch[aria-pressed="true"] { box-shadow: 0 0 0 2px var(--ink); }
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
    <label class="set-range">
      <div><span>${label}</span><output class="sub">${s[key]}${unit}</output></div>
      <input type="range" min=${min} max=${max} step=${step} value=${s[key]}
        onInput=${(e) => set(key, Number(e.target.value))} />
    </label>`;

  return html`
    <h1 class="page-title">Settings</h1>
    <${BentoGrid}>
      <div class="card magic-bento-card bento-lg">
        <div class="card-head"><span class="magic-bento-card__title">Effects</span></div>
        <div class="card-body">
          <div class="set-list">
            ${TOGGLES.map(([key, label, hint]) => html`
              <label class="set-row">
                <span>${label}<span class="sub">${hint}</span></span>
                <input class="switch" type="checkbox" role="switch" checked=${s[key]}
                  onChange=${(e) => set(key, e.target.checked)} />
              </label>`)}
          </div>
          ${range('spotlightRadius', 'Spotlight radius', 100, 600, 10, 'px')}
          ${range('particleCount', 'Particles', 0, 40, 1, '')}
          <div class="set-colors">
            <span>Glow colour</span>
            ${SWATCHES.map(([name, rgb]) => html`
              <button class="swatch" type="button" aria-label=${name} title=${name}
                aria-pressed=${s.glowColor === rgb} style=${`background:rgb(${rgb})`}
                onClick=${() => set('glowColor', rgb)}></button>`)}
            <input class="set-color" type="color" aria-label="Custom glow colour" value=${toHex(s.glowColor)}
              onInput=${(e) => set('glowColor', toRgb(e.target.value))} />
          </div>
          <button class="btn btn-soft" type="button" onClick=${resetSettings}>Reset to defaults</button>
        </div>
      </div>
      <div class="card magic-bento-card">
        <div class="card-head"><span class="magic-bento-card__title">Appearance</span></div>
        <div class="card-body">
          <div class="tabs">
            ${THEMES.map(([value, label]) => html`
              <button class=${theme === value ? 'tab active' : 'tab'} type="button" aria-pressed=${theme === value}
                onClick=${() => chooseTheme(value)}>${label}</button>`)}
          </div>
          <div class="sub magic-bento-card__description">System follows the light or dark setting of your OS.</div>
        </div>
      </div>
      ${SAMPLES.map(([title, text]) => html`
        <div class="card magic-bento-card">
          <div class="card-body">
            <div class="sub">Preview</div>
            <div class="set-sample magic-bento-card__title">${title}</div>
            <div class="sub magic-bento-card__description">${text}</div>
          </div>
        </div>`)}
    <//>`;
}

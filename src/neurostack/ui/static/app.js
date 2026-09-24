import { html, render, useState, useEffect } from './lib.js';
import { api } from './api.js';
import {
  Alert, AlertDescription, AlertTitle, Button, Card, CardContent, Sheet, SheetContent, SheetHeader, SheetTitle,
} from './components/ui.js';
import Login from './pages/login.js';

const routes = {
  '': './pages/overview.js',
  automations: './pages/automations.js',
  graph: './pages/graph.js',
  memories: './pages/memories.js',
  settings: './pages/settings.js',
};
const icon = (body) => html`<svg viewBox="0 0 16 16" aria-hidden="true">${body}</svg>`;
const NAV = [
  ['Vault', [
    ['', 'Overview', icon(html`<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>`)],
    ['graph', 'Graph', icon(html`<circle cx="4" cy="4" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="7" cy="12" r="2"/><path d="M5.8 4.3l4.3.5M5 5.8l1.4 4.4M11 6.8l-2.8 3.6"/>`)],
    ['memories', 'Memories', icon(html`<path d="M3 2.5h10v11l-5-3-5 3z"/>`)],
  ]],
  ['System', [
    ['automations', 'Automations', icon(html`<circle cx="8" cy="8" r="6"/><path d="M8 4.5V8l2.5 1.5"/>`)],
    ['settings', 'Settings', icon(html`<circle cx="8" cy="8" r="2"/><circle cx="8" cy="8" r="4.5"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>`)],
  ]],
];
const LOGO = html`<img class="logo-mark" src="logo.svg" alt="" />NeuroStack`;
// The icon shows the theme a click switches to.
const MOON = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>`;
const SUN = html`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const MENU = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>`;

const main = document.getElementById('app');
const nav = document.getElementById('nav');
let seq = 0;
let signedOut = false;
let user = null;
let active = '';
const isDark = () => document.documentElement.dataset.theme === 'dark';

// Below 768px only the logo and menu button show; the menu opens the same links in a Sheet.
function Sidebar({ active, user }) {
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(isDark);
  useEffect(() => {
    const sync = () => setDark(isDark());
    addEventListener('ns-theme', sync);
    return () => removeEventListener('ns-theme', sync);
  }, []);
  const close = () => setOpen(false);
  const links = () => NAV.map(([group, items]) => html`
    <div class="nav-label">${group}</div>
    ${items.map(([key, label, svg]) => html`
      <a class="nav-item" href=${`#/${key}`} aria-current=${key === active ? 'page' : undefined} onClick=${close}>${svg}${label}</a>`)}`);
  const tail = () => html`
    <div class="nav-user">${user && html`
      <span class="sub" title=${user}>${user}</span>
      <${Button} variant="outline" onClick=${signOut}>Sign out<//>`}</div>
    <${Button} variant="outline" size="icon" class="theme-toggle" aria-label="Dark mode" aria-pressed=${dark}
      onClick=${() => chooseTheme(dark ? 'light' : 'dark')}>${dark ? SUN : MOON}<//>`;
  return html`
    <div class="logo">${LOGO}</div>
    <${Button} variant="outline" size="icon" class="menu-btn" aria-label="Menu" aria-expanded=${open}
      onClick=${() => setOpen(true)}>${MENU}<//>
    ${links()}${tail()}
    <${Sheet} open=${open} onOpenChange=${setOpen}>
      <${SheetContent}>
        <${SheetHeader}><${SheetTitle} class="logo">${LOGO}<//><//>
        ${links()}${tail()}
      <//>
    <//>`;
}
const drawNav = () => render(html`<${Sidebar} active=${active} user=${user} />`, nav);

// The route is the hash path before any `?`; pages own their query string.
async function route() {
  if (signedOut) return;
  const name = location.hash.replace(/^#\/?/, '').split('?')[0];
  const key = name in routes ? name : '';
  active = key;
  drawNav();
  const n = ++seq;
  let Page;
  try {
    Page = (await import(routes[key])).default;
  } catch (e) {
    Page = () => html`<${Card}><${CardContent}><${Alert} variant="destructive">
      <${AlertTitle}>Could not load this page<//><${AlertDescription}>${e.message}<//>
    <//><//><//>`;
  }
  // A slower import must not overwrite a newer navigation.
  if (n === seq) render(html`<${Page} key=${key} />`, main);
}

// Any 401 lands here. Bumping seq drops a page import still in flight.
function showLogin() {
  signedOut = true;
  seq++;
  document.body.classList.add('signed-out');
  render(html`<${Login} onDone=${start} />`, main);
}

async function signOut() {
  await api('logout', {}).catch(() => {});
  showLogin();
}

// A failed /api/me other than 401 still routes, so the page shows its own error.
async function start() {
  signedOut = false;
  const me = await api('me').catch(() => ({ user: null }));
  if (signedOut) return;
  document.body.classList.remove('signed-out');
  user = me.user;
  route();
}

// index.html set the first theme. A choice is stored; 'system' clears it, so the OS decides.
const darkOS = matchMedia('(prefers-color-scheme: dark)');
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  dispatchEvent(new Event('ns-theme'));
}
export function chooseTheme(choice) {
  if (choice === 'system') localStorage.removeItem('ns_theme');
  else localStorage.setItem('ns_theme', choice);
  setTheme(choice === 'system' ? (darkOS.matches ? 'dark' : 'light') : choice);
}
darkOS.addEventListener('change',
  (e) => localStorage.getItem('ns_theme') || setTheme(e.matches ? 'dark' : 'light'));

addEventListener('ns-auth', showLogin);
addEventListener('hashchange', route);
drawNav();
start();

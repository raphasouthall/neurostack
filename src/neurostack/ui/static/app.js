import { html, render, useState, useEffect } from './lib.js';
import { api } from './api.js';
import {
  Alert, AlertDescription, AlertTitle, Button, Card, CardContent, Sheet, SheetContent, SheetHeader, SheetTitle,
} from './components/ui.js';
import Login from './pages/login.js';
import { THEME_KEY } from './themes.js';

const routes = {
  '': './pages/overview.js',
  automations: './pages/automations.js',
  graph: './pages/graph.js',
  memories: './pages/memories.js',
  search: './pages/search.js',
  settings: './pages/settings.js',
  tuning: './pages/tuning.js',
};
const icon = (body) => html`<svg viewBox="0 0 16 16" aria-hidden="true">${body}</svg>`;
const NAV = [
  ['Vault', [
    ['', 'Overview', icon(html`<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>`)],
    ['search', 'Search', icon(html`<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/>`)],
    ['graph', 'Graph', icon(html`<circle cx="4" cy="4" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="7" cy="12" r="2"/><path d="M5.8 4.3l4.3.5M5 5.8l1.4 4.4M11 6.8l-2.8 3.6"/>`)],
    ['memories', 'Memories', icon(html`<path d="M3 2.5h10v11l-5-3-5 3z"/>`)],
  ]],
  ['System', [
    ['automations', 'Automations', icon(html`<circle cx="8" cy="8" r="6"/><path d="M8 4.5V8l2.5 1.5"/>`)],
    ['tuning', 'Tuning', icon(html`<path d="M3 4h6M11 4h2M3 8h2M7 8h6M3 12h8M13 12h0"/><circle cx="10" cy="4" r="1.5"/><circle cx="6" cy="8" r="1.5"/><circle cx="12" cy="12" r="1.5"/>`)],
    ['settings', 'Settings', icon(html`<circle cx="8" cy="8" r="2"/><circle cx="8" cy="8" r="4.5"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>`)],
  ]],
];
const LOGO = html`<img class="logo-mark" src="logo.svg" alt="" /><span class="nav-text">NeuroStack</span>`;
// The icon shows the theme a click switches to.
const MOON = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>`;
const SUN = html`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const MENU = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>`;
const PIN = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4h6l-1 6 3 3H7l3-3zM12 13v7"/></svg>`;
const CARET = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>`;
const MINUS = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12"/></svg>`;
const PIN_KEY = 'ns_nav_pinned';
const CLOSED_KEY = 'ns_nav_closed';

const main = document.getElementById('app');
const nav = document.getElementById('nav');
let seq = 0;
let signedOut = false;
let user = null;
let active = '';
// Any daisyUI theme can be dark, so ask the page rather than the theme name.
const isDark = () => getComputedStyle(document.documentElement).colorScheme === 'dark';

const initials = (name) => (name || 'local').replace(/[^A-Za-z0-9]/g, ' ').trim().slice(0, 2).toUpperCase();

// From 768px up the sidebar is a 64px icon rail beside the page. It widens while
// hovered, while focus is inside it, and while the account menu is open; the pin
// holds it wide and is remembered. Width is a flex basis, so widening pushes the
// page over instead of covering it. Labels never unmount: they fade in CSS, so an
// icon-only row keeps its accessible name. Below 768px it is a top bar whose menu
// opens the same nav, always wide, in a Sheet.
function Sidebar({ active, user }) {
  const [sheet, setSheet] = useState(false);
  const [pinned, setPinned] = useState(() => localStorage.getItem(PIN_KEY) !== '0');
  const [menu, setMenu] = useState(false);
  const [closed, setClosed] = useState(() => new Set(JSON.parse(localStorage.getItem(CLOSED_KEY) || '[]')));
  const [dark, setDark] = useState(isDark);
  useEffect(() => {
    const sync = () => setDark(isDark());
    addEventListener('ns-theme', sync);
    return () => removeEventListener('ns-theme', sync);
  }, []);
  // The rail's class lives on the <nav> render() targets, so it is set here.
  useEffect(() => {
    nav.classList.toggle('pinned', pinned);
    nav.classList.toggle('menu-open', menu);
  }, [pinned, menu]);
  useEffect(() => {
    if (!menu) return;
    const shut = (e) => (e.type === 'keydown' ? e.key === 'Escape' : !e.target.closest('.nav-foot')) && setMenu(false);
    addEventListener('pointerdown', shut);
    addEventListener('keydown', shut);
    return () => { removeEventListener('pointerdown', shut); removeEventListener('keydown', shut); };
  }, [menu]);

  const pin = (e) => {
    // Unpinning by mouse would leave focus inside and hold the rail wide.
    if (pinned && e.detail) e.currentTarget.blur();
    localStorage.setItem(PIN_KEY, pinned ? '0' : '1');
    setPinned(!pinned);
  };
  const toggleGroup = (group) => {
    const next = new Set(closed);
    next.has(group) ? next.delete(group) : next.add(group);
    localStorage.setItem(CLOSED_KEY, JSON.stringify([...next]));
    setClosed(next);
  };
  const theme = () => chooseTheme(dark ? 'neurostack' : 'neurostack-dark');

  const body = (inSheet) => html`
    <div class="nav-scroll">
      ${NAV.map(([group, items]) => {
        const open = !closed.has(group);
        return html`<div class="nav-group" key=${group}>
          <button class="nav-heading" aria-expanded=${open} onClick=${() => toggleGroup(group)}>
            <span class="nav-text">${group}</span><span class="nav-caret">${open ? CARET : MINUS}</span>
          </button>
          <div class="nav-rows" data-closed=${!open || undefined}><div>
            ${items.map(([key, label, svg]) => html`
              <a class="nav-row" href=${`#/${key}`} title=${label} aria-current=${key === active ? 'page' : undefined}
                onClick=${() => inSheet && setSheet(false)}>${svg}<span class="nav-text">${label}</span></a>`)}
          </div></div>
        </div>`;
      })}
    </div>
    <div class="nav-foot">
      ${menu && !inSheet && html`<div class="nav-menu" role="menu" aria-label="Account">
        <button role="menuitem" onClick=${() => { theme(); setMenu(false); }}>${dark ? SUN : MOON}${dark ? 'Light mode' : 'Dark mode'}</button>
        ${user && html`<button role="menuitem" class="nav-danger" onClick=${signOut}>Sign out</button>`}
      </div>`}
      <button class="nav-account" aria-haspopup="menu" aria-expanded=${!inSheet && menu}
        onClick=${() => (inSheet ? theme() : setMenu(!menu))} title=${user || 'Local session'}>
        <span class="nav-avatar" aria-hidden="true">${initials(user)}</span>
        <span class="nav-text nav-who"><span class="nav-name">${user || 'Local'}</span>
          <span class="sub">${inSheet ? (dark ? 'Switch to light mode' : 'Switch to dark mode') : user ? 'Signed in' : 'Loopback, no login'}</span></span>
      </button>
      ${inSheet && user && html`<${Button} variant="outline" onClick=${signOut}>Sign out<//>`}
    </div>`;

  return html`
    <div class="nav-brand">
      <a class="logo" href="#/" aria-label="NeuroStack home">${LOGO}</a>
      <button class="nav-pin" aria-pressed=${pinned} aria-label=${pinned ? 'Unpin sidebar' : 'Pin sidebar open'}
        title=${pinned ? 'Unpin sidebar' : 'Pin sidebar open'} onClick=${pin}>${PIN}</button>
    </div>
    ${body(false)}
    <${Button} variant="outline" size="icon" class="menu-btn" aria-label="Menu" aria-expanded=${sheet}
      onClick=${() => setSheet(true)}>${MENU}<//>
    <${Button} variant="outline" size="icon" class="theme-toggle" aria-label="Dark mode" aria-pressed=${dark}
      onClick=${theme}>${dark ? SUN : MOON}<//>
    <${Sheet} open=${sheet} onOpenChange=${setSheet}>
      <${SheetContent} class="nav-sheet">
        <${SheetHeader}><${SheetTitle} class="logo">${LOGO}<//><//>
        ${body(true)}
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
  if (n !== seq) return;
  render(html`<${Page} key=${key} />`, main);
  // The page panel is the scrollport from 768px up, so a new route starts at its top.
  main.scrollTop = 0;
  scrollTo(0, 0);
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

// index.html set the first theme. A choice is a daisyUI theme name and is stored;
// 'system' clears it, so the OS picks between the two NeuroStack themes.
const darkOS = matchMedia('(prefers-color-scheme: dark)');
const osTheme = () => (darkOS.matches ? 'neurostack-dark' : 'neurostack');
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  dispatchEvent(new Event('ns-theme'));
}
export function chooseTheme(choice) {
  if (choice === 'system') localStorage.removeItem(THEME_KEY);
  else localStorage.setItem(THEME_KEY, choice);
  setTheme(choice === 'system' ? osTheme() : choice);
}
darkOS.addEventListener('change', () => localStorage.getItem(THEME_KEY) || setTheme(osTheme()));

addEventListener('ns-auth', showLogin);
addEventListener('hashchange', route);
drawNav();
start();

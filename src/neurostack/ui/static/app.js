import { html, render } from './lib.js';
import { api } from './api.js';
import Login from './pages/login.js';

const routes = {
  '': './pages/overview.js',
  automations: './pages/automations.js',
  graph: './pages/graph.js',
  memories: './pages/memories.js',
  settings: './pages/settings.js',
};
const main = document.getElementById('app');
const userBox = document.getElementById('user');
let seq = 0;
let signedOut = false;

// The route is the hash path before any `?`; pages own their query string.
async function route() {
  if (signedOut) return;
  const name = location.hash.replace(/^#\/?/, '').split('?')[0];
  const key = name in routes ? name : '';
  for (const a of document.querySelectorAll('.nav-item')) {
    a.classList.toggle('active', a.dataset.route === key);
  }
  const n = ++seq;
  let Page;
  try {
    Page = (await import(routes[key])).default;
  } catch (e) {
    Page = () => html`<div class="card"><div class="card-body error">Could not load this page: ${e.message}</div></div>`;
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
  render(me.user && html`
    <span class="sub" title=${me.user}>${me.user}</span>
    <button class="btn" onClick=${signOut}>Sign out</button>`, userBox);
  route();
}

// index.html set the first theme. A choice is stored; 'system' clears it, so the OS decides.
const themeBtn = document.getElementById('theme');
const darkOS = matchMedia('(prefers-color-scheme: dark)');
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeBtn.setAttribute('aria-pressed', theme === 'dark');
  dispatchEvent(new Event('ns-theme'));
}
export function chooseTheme(choice) {
  if (choice === 'system') localStorage.removeItem('ns_theme');
  else localStorage.setItem('ns_theme', choice);
  setTheme(choice === 'system' ? (darkOS.matches ? 'dark' : 'light') : choice);
}
themeBtn.setAttribute('aria-pressed', document.documentElement.dataset.theme === 'dark');
themeBtn.addEventListener('click',
  () => chooseTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
darkOS.addEventListener('change',
  (e) => localStorage.getItem('ns_theme') || setTheme(e.matches ? 'dark' : 'light'));

// Below 768px the nav is an overlay; picking a page or Escape closes it.
const nav = document.querySelector('.sidebar');
const menuBtn = document.getElementById('menu');
function setMenu(open) {
  nav.classList.toggle('open', open);
  menuBtn.setAttribute('aria-expanded', open);
}
menuBtn.addEventListener('click', () => setMenu(!nav.classList.contains('open')));
nav.addEventListener('click', (e) => e.target.closest('.nav-item') && setMenu(false));
addEventListener('keydown', (e) => e.key === 'Escape' && setMenu(false));

addEventListener('ns-auth', showLogin);
addEventListener('hashchange', route);
start();

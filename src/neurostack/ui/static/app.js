import { html, render } from './lib.js';

const routes = {
  '': './pages/overview.js',
  automations: './pages/automations.js',
  graph: './pages/graph.js',
  memories: './pages/memories.js',
};
const main = document.getElementById('app');
let seq = 0;

// The route is the hash path before any `?`; pages own their query string.
async function route() {
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

addEventListener('hashchange', route);
route();

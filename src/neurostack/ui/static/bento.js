import { html, useState, useEffect, useRef } from './lib.js';

// Card effects ported from the React Bits MagicBento behaviour (issue #255).
// Web Animations and CSS custom properties stand in for gsap.
export const DEFAULTS = {
  textAutoHide: true,
  enableStars: true,
  enableSpotlight: true,
  enableBorderGlow: true,
  enableTilt: false,
  enableMagnetism: true,
  clickEffect: true,
  disableAnimations: false,
  spotlightRadius: 300,
  particleCount: 12,
  glowColor: '73, 79, 223',
};
const KEY = 'ns_bento';
const MOBILE = matchMedia('(max-width: 768px)');
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)');
// Cards holding a table or a field keep still, so rows and inputs stay easy to hit.
const STILL = 'table, input, select, textarea';
const NO_RIPPLE = 'a, button, input, select, textarea, label';

export function getSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY)) };
  } catch {
    return { ...DEFAULTS };
  }
}

function changed() {
  document.documentElement.style.setProperty('--glow-rgb', getSettings().glowColor);
  dispatchEvent(new Event('ns-bento'));
}

export function saveSettings(s) {
  localStorage.setItem(KEY, JSON.stringify(s));
  changed();
}

export function resetSettings() {
  localStorage.removeItem(KEY);
  changed();
}

document.documentElement.style.setProperty('--glow-rgb', getSettings().glowColor);

function star(card) {
  const p = document.createElement('div');
  p.className = 'particle';
  p.style.left = `${Math.random() * card.clientWidth}px`;
  p.style.top = `${Math.random() * card.clientHeight}px`;
  card.append(p);
  const drift = () => `${Math.random() * 100 - 50}px`;
  p.animate({ scale: [0, 1] }, { duration: 300, easing: 'cubic-bezier(.34, 1.56, .64, 1)', fill: 'forwards' });
  p.animate({ translate: ['0 0', `${drift()} ${drift()}`] },
    { duration: 2000 + Math.random() * 2000, iterations: Infinity, direction: 'alternate' });
  p.animate({ opacity: [1, 0.3] }, { duration: 1500, iterations: Infinity, direction: 'alternate', easing: 'ease-in-out' });
}

// A later animation overrides the running ones, so the star shrinks out from wherever it drifted.
function fadeOut(p) {
  p.animate({ scale: 0, opacity: 0 }, { duration: 300, easing: 'cubic-bezier(.36, 0, .66, -.56)', fill: 'forwards' })
    .onfinish = () => p.remove();
}

function ripple(card, e) {
  const r = card.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;
  const m = Math.max(Math.hypot(x, y), Math.hypot(x - r.width, y),
    Math.hypot(x, y - r.height), Math.hypot(x - r.width, y - r.height));
  const el = document.createElement('div');
  el.className = 'bento-ripple';
  Object.assign(el.style, { width: `${m * 2}px`, height: `${m * 2}px`, left: `${x - m}px`, top: `${y - m}px` });
  card.append(el);
  el.animate([{ transform: 'scale(0)', opacity: 1 }, { transform: 'scale(1)', opacity: 0 }],
    { duration: 800, easing: 'cubic-bezier(.33, 1, .68, 1)' }).onfinish = () => el.remove();
}

// Wires every effect onto one section through delegation, so cards that render
// later need no re-attach. Returns the cleanup.
function attach(section, s) {
  const cards = () => [...section.children].filter((c) => c.classList.contains('magic-bento-card'));
  const glowing = s.enableSpotlight || s.enableBorderGlow;
  const spotlight = s.enableSpotlight
    ? document.body.appendChild(Object.assign(document.createElement('div'), { className: 'bento-spotlight' }))
    : null;
  let card = null, still = false, frame = 0, last = null, timers = [];

  function leave() {
    timers.forEach(clearTimeout);
    timers = [];
    if (!card) return;
    for (const p of card.querySelectorAll(':scope > .particle')) fadeOut(p);
    card.style.transform = '';
    card = null;
  }

  function enter(c) {
    card = c;
    still = !!c.querySelector(STILL);
    if (!s.enableStars) return;
    for (let i = 0; i < s.particleCount; i++) timers.push(setTimeout(() => star(c), i * 100));
  }

  // Proximity and fade distances follow MagicBento: full glow within half the radius.
  function glow(e) {
    const near = s.spotlightRadius * 0.5, far = s.spotlightRadius * 0.75;
    const level = (d) => (d <= near ? 1 : d <= far ? (far - d) / (far - near) : 0);
    let min = Infinity;
    for (const c of cards()) {
      const r = c.getBoundingClientRect();
      const d = Math.max(0, Math.hypot(e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2)
        - Math.max(r.width, r.height) / 2);
      min = Math.min(min, d);
      c.style.setProperty('--glow-x', `${((e.clientX - r.left) / r.width) * 100}%`);
      c.style.setProperty('--glow-y', `${((e.clientY - r.top) / r.height) * 100}%`);
      c.style.setProperty('--glow-intensity', level(d));
      c.style.setProperty('--glow-radius', `${s.spotlightRadius}px`);
    }
    if (!spotlight) return;
    spotlight.style.transform = `translate(${e.clientX}px, ${e.clientY}px) translate(-50%, -50%)`;
    spotlight.style.opacity = level(min) * 0.8;
  }

  function move() {
    frame = 0;
    const c = last.target.closest('.magic-bento-card');
    const hit = c?.parentElement === section ? c : null;
    if (hit !== card) {
      leave();
      if (hit) enter(hit);
    }
    if (card && !still && (s.enableTilt || s.enableMagnetism)) {
      const r = card.getBoundingClientRect();
      const x = last.clientX - r.left - r.width / 2, y = last.clientY - r.top - r.height / 2;
      card.style.transform = 'perspective(1000px)'
        + (s.enableTilt ? ` rotateX(${(-y / (r.height / 2)) * 10}deg) rotateY(${(x / (r.width / 2)) * 10}deg)` : '')
        + (s.enableMagnetism ? ` translate(${x * 0.05}px, ${y * 0.05}px)` : '');
    }
    if (glowing) glow(last);
  }

  const onMove = (e) => {
    last = e;
    frame ||= requestAnimationFrame(move);
  };
  const onLeave = () => {
    cancelAnimationFrame(frame);
    frame = 0;
    leave();
    if (spotlight) spotlight.style.opacity = 0;
    for (const c of cards()) c.style.setProperty('--glow-intensity', 0);
  };
  const onClick = (e) => {
    const c = e.target.closest('.magic-bento-card');
    if (s.clickEffect && c?.parentElement === section && !e.target.closest(NO_RIPPLE)) ripple(c, e);
  };

  section.addEventListener('pointermove', onMove);
  section.addEventListener('pointerleave', onLeave);
  section.addEventListener('click', onClick);
  return () => {
    section.removeEventListener('pointermove', onMove);
    section.removeEventListener('pointerleave', onLeave);
    section.removeEventListener('click', onClick);
    cancelAnimationFrame(frame);
    timers.forEach(clearTimeout);
    spotlight?.remove();
    for (const c of cards()) {
      c.style.transform = '';
      c.style.removeProperty('--glow-intensity');
    }
    section.querySelectorAll(':scope > * > :is(.particle, .bento-ripple)').forEach((el) => el.remove());
  };
}

// The grid re-reads settings on `ns-bento` and on viewport or motion changes, and
// re-attaches the effects whenever the result changes.
export function BentoGrid({ children, className = '' }) {
  const ref = useRef();
  const [s, setS] = useState(getSettings);
  useEffect(() => {
    const sync = () => setS(getSettings());
    addEventListener('ns-bento', sync);
    MOBILE.addEventListener('change', sync);
    REDUCED.addEventListener('change', sync);
    return () => {
      removeEventListener('ns-bento', sync);
      MOBILE.removeEventListener('change', sync);
      REDUCED.removeEventListener('change', sync);
    };
  }, []);
  const live = !s.disableAnimations && !MOBILE.matches && !REDUCED.matches;
  useEffect(() => (live ? attach(ref.current, s) : undefined), [s, live]);
  const cls = ['bento-section card-grid', className, s.textAutoHide && 'bento-autohide',
    live && 'bento-live', live && s.enableBorderGlow && 'bento-glow'].filter(Boolean).join(' ');
  return html`<div ref=${ref} class=${cls}>${children}</div>`;
}

export function StatTile({ label, children }) {
  return html`<div class="card magic-bento-card">
    <div class="card-body">
      <div class="sub magic-bento-card__title">${label}</div>
      <div class="stat-value">${children}</div>
    </div>
  </div>`;
}

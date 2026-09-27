import { html, useState, useEffect, useRef } from './lib.js';
import { Card, CardContent, CardTitle } from './components/ui.js';

// Card effects ported from the React Bits MagicBento behaviour (issue #255).
// Web Animations and CSS custom properties stand in for gsap. Their colour is the
// daisyUI theme's accent (--effect in styles.css), so a theme change repaints them.
export const DEFAULTS = {
  textAutoHide: true,
  enableBorderGlow: true,
  enableTilt: false,
  clickEffect: true,
  disableAnimations: false,
};
// The border glow reaches full strength within 150px of a card and fades out by 225px.
const GLOW_RADIUS = 300;
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
  let card = null, still = false, frame = 0, last = null;

  function leave() {
    if (!card) return;
    card.style.transform = '';
    card = null;
  }

  function enter(c) {
    card = c;
    still = !!c.querySelector(STILL);
  }

  // Proximity and fade distances follow MagicBento: full glow within half the radius.
  function glow(e) {
    const near = GLOW_RADIUS * 0.5, far = GLOW_RADIUS * 0.75;
    const level = (d) => (d <= near ? 1 : d <= far ? (far - d) / (far - near) : 0);
    for (const c of cards()) {
      const r = c.getBoundingClientRect();
      const d = Math.max(0, Math.hypot(e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2)
        - Math.max(r.width, r.height) / 2);
      c.style.setProperty('--glow-x', `${((e.clientX - r.left) / r.width) * 100}%`);
      c.style.setProperty('--glow-y', `${((e.clientY - r.top) / r.height) * 100}%`);
      c.style.setProperty('--glow-intensity', level(d));
    }
  }

  function move() {
    frame = 0;
    const c = last.target.closest('.magic-bento-card');
    const hit = c?.parentElement === section ? c : null;
    if (hit !== card) {
      leave();
      if (hit) enter(hit);
    }
    if (card && !still && s.enableTilt) {
      const r = card.getBoundingClientRect();
      const x = last.clientX - r.left - r.width / 2, y = last.clientY - r.top - r.height / 2;
      card.style.transform = `perspective(1000px) rotateX(${(-y / (r.height / 2)) * 10}deg) rotateY(${(x / (r.width / 2)) * 10}deg)`;
    }
    if (s.enableBorderGlow) glow(last);
  }

  const onMove = (e) => {
    last = e;
    frame ||= requestAnimationFrame(move);
  };
  const onLeave = () => {
    cancelAnimationFrame(frame);
    frame = 0;
    leave();
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
    for (const c of cards()) {
      c.style.transform = '';
      c.style.removeProperty('--glow-intensity');
    }
    section.querySelectorAll(':scope > * > .bento-ripple').forEach((el) => el.remove());
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
  return html`<${Card} class="magic-bento-card"><${CardContent}>
    <${CardTitle} class="sub">${label}<//>
    <div class="stat-value">${children}</div>
  <//><//>`;
}

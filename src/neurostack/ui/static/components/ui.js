import { html, render, useState, useEffect, useRef, useMemo, createContext, useContext } from '../lib.js';

// shadcn/ui components (MIT, shadcn) ported to Preact + htm and plain CSS for
// issue #257. Names, variants and slots follow shadcn; styles.css holds the looks.
// Every component takes `class` and passes its other props to the root element.

const cx = (...c) => c.filter(Boolean).join(' ');
let ids = 0;
const useId = (prefix) => useMemo(() => `${prefix}-${++ids}`, []);
// A component that is only its root element and a base class.
const slot = (tag, base) => ({ class: c, ...props }) => html`<${tag} class=${cx(base, c)} ...${props} />`;

export function Button({ class: c, variant = 'default', size = 'default', href, ...props }) {
  const cls = cx('btn', `btn-${variant}`, size !== 'default' && `btn-${size}`, c);
  return href ? html`<a class=${cls} href=${href} ...${props} />` : html`<button type="button" class=${cls} ...${props} />`;
}

export function Badge({ class: c, variant = 'default', ...props }) {
  return html`<span class=${cx('badge', `badge-${variant}`, c)} ...${props} />`;
}

export const Card = slot('div', 'card');
export const CardHeader = slot('div', 'card-header');
export const CardTitle = slot('div', 'card-title');
export const CardDescription = slot('div', 'card-description');
export const CardAction = slot('div', 'card-action');
export const CardContent = slot('div', 'card-content');
export const CardFooter = slot('div', 'card-footer');

export const Input = slot('input', 'input');
export const Label = slot('label', 'label');

// The native select keeps the OS picker and keyboard; only the box and chevron are ours.
export function NativeSelect({ class: c, ...props }) {
  return html`<span class=${cx('native-select', c)}>
    <select class="input" ...${props} />
    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
  </span>`;
}

// A button, so Space and Enter toggle it natively.
export function Switch({ class: c, checked = false, onCheckedChange, ...props }) {
  return html`<button type="button" role="switch" aria-checked=${checked} class=${cx('switch', c)}
    onClick=${() => onCheckedChange?.(!checked)} ...${props}><span class="switch-thumb"></span></button>`;
}

// One thumb on a native range; --fill paints the track up to the value.
export function Slider({ class: c, value, min = 0, max = 100, onValueChange, ...props }) {
  return html`<input type="range" class=${cx('slider', c)} min=${min} max=${max} value=${value}
    style=${`--fill:${((value - min) / (max - min)) * 100}%`}
    onInput=${(e) => onValueChange?.(Number(e.target.value))} ...${props} />`;
}

export const Separator = ({ class: c, ...props }) => html`<div role="none" class=${cx('separator', c)} ...${props} />`;

export const Skeleton = ({ class: c, ...props }) => html`<div aria-hidden="true" class=${cx('skeleton', c)} ...${props} />`;
// Three pulsing lines; the hidden text keeps "Loading" for screen readers.
export const Loading = () => html`<div class="loading"><span class="sr-only">Loading</span>
  <${Skeleton} /><${Skeleton} /><${Skeleton} /></div>`;

export function Alert({ class: c, variant = 'default', ...props }) {
  return html`<div role="alert" class=${cx('alert', `alert-${variant}`, c)} ...${props} />`;
}
export const AlertTitle = slot('div', 'alert-title');
export const AlertDescription = slot('div', 'alert-description');

const TooltipCtx = createContext();
export function Tooltip({ children }) {
  const [open, setOpen] = useState(false);
  const id = useId('tooltip');
  const ref = useRef();
  return html`<${TooltipCtx.Provider} value=${{ open, setOpen, id, ref }}>${children}<//>`;
}
export function TooltipTrigger({ class: c, ...props }) {
  const t = useContext(TooltipCtx);
  const show = () => t.setOpen(true), hide = () => t.setOpen(false);
  return html`<span ref=${t.ref} tabindex="0" class=${cx('tooltip-trigger', c)} aria-describedby=${t.open ? t.id : undefined}
    onPointerEnter=${show} onPointerLeave=${hide} onFocus=${show} onBlur=${hide}
    onKeyDown=${(e) => e.key === 'Escape' && hide()} ...${props} />`;
}
// The bubble renders into <body>, so a card's overflow or hover transform cannot clip it.
let tipHost;
export function TooltipContent({ class: c, children }) {
  const { open, id, ref } = useContext(TooltipCtx);
  useEffect(() => {
    if (!open) return;
    tipHost ??= document.body.appendChild(Object.assign(document.createElement('div'), { style: 'display:contents' }));
    const r = ref.current.getBoundingClientRect();
    const below = r.top < 48;
    // The bubble is at most 240px wide, so a centre 128px from either edge keeps it on screen.
    const x = Math.min(Math.max(r.left + r.width / 2, 128), innerWidth - 128);
    render(html`<div role="tooltip" id=${id} class=${cx('tooltip-content', c)} data-side=${below ? 'bottom' : 'top'}
      style=${`left:${x}px;top:${below ? r.bottom + 6 : r.top - 6}px`}>${children}</div>`, tipHost);
    return () => render(null, tipHost);
  }, [open, children]);
  return null;
}

export const Table = ({ class: c, ...props }) => html`<div class="table-wrap"><table class=${cx('table', c)} ...${props} /></div>`;
export const TableHeader = slot('thead');
export const TableBody = slot('tbody');
export const TableRow = slot('tr');
export const TableHead = slot('th');
export const TableCell = slot('td');
export const TableCaption = slot('caption');

// Arrow keys, Home and End move focus along a list; returns the item focused.
function rove(e, selector) {
  const items = [...e.currentTarget.querySelectorAll(selector)];
  const i = items.indexOf(document.activeElement);
  const to = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: -1 }[e.key];
  if (to === undefined || i < 0) return null;
  e.preventDefault();
  const next = items[(to + items.length) % items.length];
  next.focus();
  return next;
}

const TabsCtx = createContext();
export function Tabs({ class: c, value, onValueChange, ...props }) {
  const id = useId('tabs');
  return html`<${TabsCtx.Provider} value=${{ value, onValueChange, id }}><div class=${cx('tabs', c)} ...${props} /><//>`;
}
// Only the selected tab is in the tab order, and a tab selects as it gains focus, as in shadcn.
export function TabsList({ class: c, ...props }) {
  return html`<div role="tablist" class=${cx('tabs-list', c)} onKeyDown=${(e) => rove(e, '[role=tab]')?.click()} ...${props} />`;
}
export function TabsTrigger({ class: c, value, ...props }) {
  const t = useContext(TabsCtx);
  const on = t.value === value;
  return html`<button type="button" role="tab" id=${`${t.id}-tab-${value}`} aria-controls=${`${t.id}-panel-${value}`}
    aria-selected=${on} tabindex=${on ? 0 : -1} class=${cx('tabs-trigger', c)}
    onClick=${() => t.onValueChange(value)} ...${props} />`;
}
export function TabsContent({ class: c, value, ...props }) {
  const t = useContext(TabsCtx);
  return t.value === value && html`<div role="tabpanel" id=${`${t.id}-panel-${value}`} aria-labelledby=${`${t.id}-tab-${value}`}
    tabindex="0" class=${cx('tabs-content', c)} ...${props} />`;
}

// Single-select only. Every item stays in the tab order, so a group with nothing
// pressed (a custom glow colour) is still reachable.
const ToggleCtx = createContext();
export function ToggleGroup({ class: c, value, onValueChange, ...props }) {
  return html`<${ToggleCtx.Provider} value=${{ value, onValueChange }}>
    <div role="group" class=${cx('toggle-group', c)} ...${props} /><//>`;
}
export function ToggleGroupItem({ class: c, value, ...props }) {
  const g = useContext(ToggleCtx);
  return html`<button type="button" aria-pressed=${g.value === value} class=${cx('toggle-group-item', c)}
    onClick=${() => g.onValueChange(value)} ...${props} />`;
}

const SheetCtx = createContext();
export function Sheet({ open, onOpenChange, children }) {
  const id = useId('sheet');
  return html`<${SheetCtx.Provider} value=${{ open, onOpenChange, id }}>${children}<//>`;
}
const FOCUSABLE = 'a[href], button:not(:disabled), input, select, textarea, [tabindex="0"]';
// A modal panel from the left: focus moves in and is kept there, Escape or the
// backdrop closes it, the page stops scrolling, and focus returns on close.
export function SheetContent({ class: c, children, ...props }) {
  const { open, onOpenChange, id } = useContext(SheetCtx);
  const ref = useRef();
  useEffect(() => {
    if (!open) return;
    const back = document.activeElement;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    ref.current.querySelector(FOCUSABLE)?.focus();
    const onKey = (e) => {
      if (e.key === 'Escape') return onOpenChange(false);
      if (e.key !== 'Tab') return;
      const f = ref.current.querySelectorAll(FOCUSABLE);
      const edge = e.shiftKey ? f[0] : f[f.length - 1];
      if (document.activeElement === edge) {
        e.preventDefault();
        (e.shiftKey ? f[f.length - 1] : f[0]).focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      back?.focus();
    };
  }, [open]);
  if (!open) return null;
  return html`
    <div class="sheet-overlay" onClick=${() => onOpenChange(false)}></div>
    <div ref=${ref} role="dialog" aria-modal="true" aria-labelledby=${id} class=${cx('sheet-content', c)} ...${props}>
      ${children}
      <${Button} variant="ghost" size="icon" class="sheet-close" aria-label="Close" onClick=${() => onOpenChange(false)}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      <//>
    </div>`;
}
export const SheetHeader = slot('div', 'sheet-header');
export function SheetTitle({ class: c, ...props }) {
  return html`<h2 id=${useContext(SheetCtx).id} class=${cx('sheet-title', c)} ...${props} />`;
}

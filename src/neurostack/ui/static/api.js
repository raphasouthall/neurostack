// GET /api/<path> as JSON, or POST `body` when given. The session cookie rides
// along; a 401 outside the login call tells the app to show the login page.
export async function api(path, body) {
  const res = await fetch(`/api/${path}`, body === undefined ? { credentials: 'same-origin' } : {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.status === 401 && path !== 'login') window.dispatchEvent(new Event('ns-auth'));
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

// "3m ago", or "in 3m" for a future time. A timestamp without a zone, as
// SQLite writes them, is UTC.
export function fmtAgo(iso) {
  if (!iso) return '';
  const t = Date.parse(/Z$|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso.replace(' ', 'T') + 'Z');
  if (Number.isNaN(t)) return iso;
  const sec = (Date.now() - t) / 1000;
  const a = Math.abs(sec);
  const v = a < 60 ? `${Math.round(a)}s`
    : a < 3600 ? `${Math.floor(a / 60)}m`
    : a < 86400 ? `${Math.floor(a / 3600)}h`
    : `${Math.floor(a / 86400)}d`;
  return sec < 0 ? `in ${v}` : `${v} ago`;
}

export function fmtNum(n) {
  return n == null ? '' : Number(n).toLocaleString();
}

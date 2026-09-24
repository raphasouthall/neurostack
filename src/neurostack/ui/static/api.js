let prompted = false;

// GET /api/<path> as JSON. On 401 the user is asked once per page load for the
// key; a request whose key has since changed retries with the new one.
export async function api(path) {
  const key = localStorage.getItem('ns_api_key');
  const res = await fetch(`/api/${path}`, key ? { headers: { Authorization: `Bearer ${key}` } } : {});
  if (res.status === 401) {
    if (!prompted) {
      prompted = true;
      const entered = window.prompt('NeuroStack API key');
      if (entered) localStorage.setItem('ns_api_key', entered);
    }
    if (localStorage.getItem('ns_api_key') !== key) return api(path);
  }
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

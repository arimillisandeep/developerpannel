import axios from 'axios';

const TOKEN_KEY = 'workcode_token';
// The token lives in memory first; localStorage only lets it survive a page reload.
// Storage can be blocked (embedded previews, strict privacy settings), so it is optional.
let memoryToken = null;
export const BUILD = 'build 34.16';
const PREVIEW = import.meta.env.VITE_QUERY_TOKEN === '1'; // hosted preview only, never production
export function getToken() {
  if (memoryToken) return memoryToken;
  try { memoryToken = localStorage.getItem(TOKEN_KEY); } catch { /* storage blocked */ }
  return memoryToken;
}
export function setToken(t) {
  memoryToken = t || null;
  try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ }
}

const api = axios.create({ baseURL: '/api' });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
    config.headers['X-Workcode-Token'] = token; // survives proxies that replace Authorization
  }
  if (PREVIEW) {
    // The preview gateway drops request headers, so the token also travels in the path.
    config.params = { ...(config.params || {}), _b: BUILD.replace(/\D/g, '') };
    if (token && !config.url.startsWith('/_t/')) config.url = `/_t/${token}${config.url}`;
  }
  return config;
});

/** Address and headers for requests that cannot go through axios (streamed answers). Same sign-in as every other call. */
export function rawRequest(path) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json' };
  if (token) { headers.Authorization = `Bearer ${token}`; headers['X-Workcode-Token'] = token; }
  const url = `/api${PREVIEW && token ? `/_t/${token}` : ''}${path}${PREVIEW ? `?_b=${BUILD.replace(/\D/g, '')}` : ''}`;
  return { url, headers };
}

/** Tell the server what the browser sees (build, token present or not). No secrets. */
export function report(where, extra = {}) {
  if (!PREVIEW) return;
  let storage = 'ok';
  try { localStorage.setItem('workcode_probe', '1'); localStorage.removeItem('workcode_probe'); } catch { storage = 'blocked'; }
  let embedded = false;
  try { embedded = window.top !== window.self; } catch { embedded = true; }
  const body = JSON.stringify({ where, build: BUILD, hasToken: !!memoryToken, tokenLength: (memoryToken || '').length, storage,
    embedded, href: window.location.href.slice(0, 120), agent: navigator.userAgent.slice(0, 120), ...extra });
  fetch('/api/debug/client', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }).catch(() => {});
}

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) report('401', { url: String(error.config?.url || '').replace(/\/_t\/[^/]+/, '/_t/…').slice(0, 80) });
    if (error.response?.status === 401 && getToken() && !error.config.url.includes('/auth/login')) {
      setToken(null);
      window.dispatchEvent(new Event('workcode:unauthorized'));
    }
    return Promise.reject(error);
  },
);

/** Where the WebSocket endpoints live.
 *
 *  Normally the browser connects to the address it loaded the page from and the dev server forwards /ws to FastAPI
 *  (relative -> works behind any reverse proxy). Vite's development proxy drops WebSocket upgrades now and then,
 *  which killed the second and third terminal tab with a bare "1006"; running the backend on its own address skips
 *  that hop. Set WORKCODE_WS in the frontend environment (docker-compose does) to use it.
 */
const INJECTED_WS = (() => {
  try { return __WC_WS_BASE__ || ''; } catch { return ''; }        // replaced at build time by vite.config.js
})();

export function wsBase() {
  const configured = (globalThis.__WC_WS_BASE__ ?? INJECTED_WS ?? '').toString().trim().replace(/\/+$/, '');
  return configured || `${window.location.protocol}//${window.location.host}`;
}

/** ws:// (or wss://) URL of one WebSocket endpoint, with the signed-in user's token. */
export function wsUrl(path, extra = {}) {
  const base = wsBase().replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'));
  const query = new URLSearchParams({ token: getToken() || '', ...extra }).toString();
  return `${base}${path}?${query}`;
}

/** Turn any API error into one readable sentence. */
export function errMsg(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    const d = detail[0];
    const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : '';
    return `${field ? `${field}: ` : ''}${d.msg}`;
  }
  if (error?.response) return `Request failed (${error.response.status})`;
  return 'Cannot reach the server. Check that the backend is running.';
}

export default api;

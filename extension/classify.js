// Pure decision logic (no browser APIs), so it can be tested with `node --test`.

/** "https://www.ChatGPT.com/c/123" -> { host: "www.chatgpt.com", hostname: "www.chatgpt.com" }; non-web pages -> null */
export function parse(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    return { host: u.host.toLowerCase(), hostname: u.hostname.toLowerCase() };
  } catch { return null; }
}

export const matches = (hostname, domain) => hostname === domain || hostname.endsWith(`.${domain}`);

/**
 * What kind of page is in front?
 *   focused      – is a browser window in front at all
 *   url          – address of the active tab (used here only; never sent)
 *   workcodeHost – host (with port) of the WORKCODE site, e.g. "localhost:5173"
 *   approved     – [{ domain, ignore_inactivity }]
 * Returns { category, domain } where domain is set only for approved websites.
 */
export function classify({ focused, url, workcodeHost, approved }) {
  if (!focused) return { category: 'unfocused', domain: null };
  const page = parse(url || '');
  if (!page) return { category: 'unapproved', domain: null };       // new tab, settings, files …
  if (page.host === workcodeHost) return { category: 'workcode', domain: null };
  const site = (approved || []).find((a) => matches(page.hostname, a.domain));
  if (site) return { category: 'approved', domain: site.domain };
  return { category: 'unapproved', domain: null };
}

/** "http://localhost:5173|eyJ…" -> { origin, token } or null */
export function parseCode(code) {
  const text = (code || '').trim();
  const i = text.indexOf('|');
  if (i < 0) return null;
  const token = text.slice(i + 1).trim();
  try {
    const u = new URL(text.slice(0, i).trim());
    if ((u.protocol !== 'http:' && u.protocol !== 'https:') || token.split('.').length !== 3) return null;
    return { origin: u.origin, token };
  } catch { return null; }
}

// ---- meeting timer (build 27) -------------------------------------------------------------
const TEAMS_HOSTS = ['teams.microsoft.com', 'teams.live.com', 'teams.cloud.microsoft'];
const isZoom = (hostname) => matches(hostname, 'zoom.us') || matches(hostname, 'zoom.com');
const isTeams = (hostname) => TEAMS_HOSTS.some((h) => matches(hostname, h));
const web = (url) => { try { const u = new URL(url); return u.protocol === 'https:' || u.protocol === 'http:' ? u : null; } catch { return null; } };
const zoomNumber = (u) => (u.pathname.match(/\/(?:j|s|w|wc|wc\/join)\/(\d{9,12})(?:\/|$)/) || [])[1] || null;

/**
 * Is this tab the page of that scheduled meeting?  (link = address stored with the meeting, url = address of a tab)
 *   Google Meet  same meeting code                      meet.google.com/abc-defg-hij
 *   Zoom         same meeting number, any Zoom address  zoom.us/j/123…, app.zoom.us/wc/123…/join
 *   Teams        any Teams tab (the address changes completely after joining, so the code cannot be compared)
 *   other        same host, and the tab address starts with the meeting path
 */
export function isMeetingTab(link, url) {
  const m = web(link), t = web(url);
  if (!m || !t) return false;
  const mh = m.hostname.toLowerCase(), th = t.hostname.toLowerCase();
  if (mh === 'meet.google.com') {
    const code = m.pathname.split('/')[1]?.toLowerCase();
    return !!code && th === 'meet.google.com' && t.pathname.split('/')[1]?.toLowerCase() === code;
  }
  if (isZoom(mh)) { const n = zoomNumber(m); return !!n && isZoom(th) && zoomNumber(t) === n; }
  if (isTeams(mh)) return isTeams(th);
  const path = m.pathname.replace(/\/+$/, '');
  return th === mh && (t.pathname === path || t.pathname.startsWith(`${path}/`) || path === '');
}

/** ids of the scheduled meetings that have a tab open:  meetings = [{ id, link }], urls = addresses of all tabs */
export function openMeetings(meetings, urls) {
  return (meetings || []).filter((m) => (urls || []).some((u) => isMeetingTab(m.link, u))).map((m) => m.id);
}

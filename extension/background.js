// WORKCODE Work Timer – background service worker (Manifest V3).
// Sends two small messages to the WORKCODE server: { category, domain (approved sites only), idle } for the work timer,
// and { open_ids } (ids of scheduled meetings whose page is open) for the meeting timer.
// It never reads page content, titles, form fields, cookies or history, and has no content scripts.
import { classify, openMeetings } from './classify.js';

const ALARM = 'workcode-report';
const CONFIG_MAX_AGE_MS = 5 * 60 * 1000;

const store = {
  get: (keys) => chrome.storage.local.get(keys),
  set: (obj) => chrome.storage.local.set(obj),
};

async function api(origin, token, path, body) {
  const r = await fetch(`${origin}/api/extension/${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { const e = new Error('signed out'); e.signedOut = true; throw e; }
  if (!r.ok) throw new Error(`server answered ${r.status}`);
  return r.json();
}

async function loadConfig(origin, token, force) {
  const { config, configAt } = await store.get(['config', 'configAt']);
  if (!force && config && Date.now() - (configAt || 0) < CONFIG_MAX_AGE_MS) return config;
  const fresh = await api(origin, token, 'config');
  await store.set({ config: fresh, configAt: Date.now() });
  return fresh;
}

// Meeting timer: which scheduled meetings of this person have their page open in a tab?
// The comparison happens here in the browser; only the meeting ids go to the server, never a tab address.
async function loadMeetings(origin, token, force) {
  const { meetings, meetingsAt } = await store.get(['meetings', 'meetingsAt']);
  if (!force && meetings && Date.now() - (meetingsAt || 0) < 60 * 1000) return meetings;
  const fresh = (await api(origin, token, 'meetings')).meetings || [];
  await store.set({ meetings: fresh, meetingsAt: Date.now() });
  return fresh;
}

async function reportMeetings(origin, token, force) {
  const meetings = await loadMeetings(origin, token, force);
  const { inMeeting } = await store.get(['inMeeting']);
  if (!meetings.length && !inMeeting) return null;                      // nothing scheduled now: no request at all
  const tabs = await chrome.tabs.query({});
  const answer = await api(origin, token, 'meetings', { open_ids: openMeetings(meetings, tabs.map((t) => t.url)) });
  await store.set({ inMeeting: answer.in_meeting || null });
  return answer.in_meeting || null;
}

async function report(force = false) {
  const { origin, token } = await store.get(['origin', 'token']);
  if (!origin || !token) return;
  try {
    const config = await loadConfig(origin, token, force);
    const win = await chrome.windows.getLastFocused().catch(() => null);
    const focused = !!(win && win.focused && win.state !== 'minimized');
    const [tab] = focused ? await chrome.tabs.query({ active: true, windowId: win.id }) : [];
    const { category, domain } = classify({ focused, url: tab?.url, workcodeHost: new URL(origin).host, approved: config.approved });
    const idle = await chrome.idle.queryState(Math.max(15, config.inactivity_seconds || 300));
    const answer = await api(origin, token, 'report', { category, domain, idle });
    const meeting = await reportMeetings(origin, token, force).catch(() => undefined);   // a meeting problem never disturbs the work timer report
    await store.set({ last: { category, domain, idle, mode: answer.mode, meeting, at: Date.now(), error: null } });
  } catch (e) {
    if (e.signedOut) await chrome.storage.local.remove(['token', 'config', 'configAt']);
    await store.set({ last: { at: Date.now(), error: e.signedOut ? 'Connection code expired or revoked. Create a new one in WORKCODE.' : `Cannot reach WORKCODE (${e.message}). The timer pauses when you leave the WORKCODE tab.` } });
  }
}

function schedule() {
  chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });     // every 30 seconds (Chrome 120+)
  chrome.idle.setDetectionInterval(300);
}

chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.alarms.onAlarm.addListener((a) => { if (a.name === ALARM) report(); });
chrome.tabs.onActivated.addListener(() => report());
chrome.tabs.onUpdated.addListener((_id, change) => { if (change.url) report(); });      // also background tabs: a meeting can run behind
chrome.tabs.onRemoved.addListener(() => report());                                         // closing the meeting tab = leaving
chrome.windows.onFocusChanged.addListener(() => report());
chrome.idle.onStateChanged.addListener(() => report());
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === 'report-now') { schedule(); report(true).then(() => reply(true)); return true; }
  return false;
});

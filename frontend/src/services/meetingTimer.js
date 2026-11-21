// Meeting timer (build 27): time in external meetings (Google Meet, Zoom, Teams ...).
// Separate from the work timer: this file does not use TimerContext or any /sessions call.
import { useEffect, useState, useSyncExternalStore } from 'react';
import api from './api';

const PING_MS = 30000;
let snapshot = { current: null, todaySeconds: 0, weekSeconds: 0, monthSeconds: 0, at: 0, ready: false };
const listeners = new Set();
let users = 0;
let interval = null;

function accept(data) {
  snapshot = { current: data.current || null, todaySeconds: data.today_seconds || 0,
    weekSeconds: data.week_seconds || 0, monthSeconds: data.month_seconds || 0, at: Date.now(), ready: true };
  listeners.forEach((fn) => fn());
}
const ping = () => api.post('/meetings/timer/ping').then((r) => accept(r.data)).catch(() => {});

export const meetingTimer = {
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  get: () => snapshot,
  refresh: ping,
  /** Fallback start: called by the Join button. The link itself is opened by the browser. */
  join: (meetingId) => api.post(`/meetings/${meetingId}/join`).then((r) => accept(r.data)),
  leave: (meetingId) => api.post(`/meetings/${meetingId}/leave`).then((r) => accept(r.data)),
  /** Keeps the timer alive while any part of the page shows it. */
  start() {
    users += 1;
    if (users === 1) { ping(); interval = setInterval(ping, PING_MS); document.addEventListener('visibilitychange', ping); }
    return () => {
      users -= 1;
      if (users === 0) { clearInterval(interval); document.removeEventListener('visibilitychange', ping); snapshot = { current: null, todaySeconds: 0, weekSeconds: 0, monthSeconds: 0, at: 0, ready: false }; }
    };
  },
};

/** { current, seconds, todaySeconds, weekSeconds, monthSeconds }: the running clock ticks every second between two
answers of the server; the daily, weekly and monthly totals are what the last answer reported. */
export function useMeetingTimer() {
  const s = useSyncExternalStore(meetingTimer.subscribe, meetingTimer.get);
  const [, tick] = useState(0);
  useEffect(() => meetingTimer.start(), []);
  useEffect(() => {
    if (!s.current) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [s.current]);
  const extra = s.current ? Math.max(0, (Date.now() - s.at) / 1000) : 0;
  return { ready: s.ready, current: s.current, seconds: s.current ? s.current.seconds + extra : 0,
    todaySeconds: s.todaySeconds + extra, weekSeconds: s.weekSeconds, monthSeconds: s.monthSeconds };
}

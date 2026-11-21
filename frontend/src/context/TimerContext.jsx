import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import api from '../services/api';
import { useAuth } from './AuthContext';

/**
 * One automatic timer for the whole app. It lives above the router, so moving between pages never
 * resets it. The server owns the state and the numbers; this file only reports what the tab sees
 * (active / away / idle) and shows what the server answered.
 *
 * Genuine input = trusted mouse, keyboard, scroll, touch and typing events (the code editor and the
 * terminal are inside this page, so their input counts). API calls and scripts are not input.
 */
const TimerContext = createContext(null);
export const useTimer = () => useContext(TimerContext);

export const INACTIVITY_TIMEOUT = 300000;   // 5 minutes; the server sends the same value
const TESTING = import.meta.env.MODE === 'test';   // jsdom cannot create trusted events; false in every real build
const INPUT_EVENTS = ['mousemove', 'mousedown', 'click', 'keydown', 'scroll', 'wheel', 'touchstart', 'touchmove', 'pointerdown', 'input'];
const STATUS = { RUNNING: 'working', PAUSED_INACTIVE: 'idle', PAUSED_EXTERNAL: 'away', PAUSED_MANUAL: 'paused' };
export const REASON_TEXT = {
  inactivity: 'no activity for 5 minutes', unapproved_site: 'a website that is not approved is open',
  left_browser: 'another program is in front', left_workcode: 'the WORKCODE tab is not in front',
  extension_lost: 'the browser extension stopped reporting', manual_pause: 'you pressed Pause',
  activity: 'activity', approved_site: 'approved website', start: 'started', auto_start: 'started automatically',
  stopped: 'stopped by you', logout: 'logout', no_heartbeat: 'connection lost', stale: 'connection lost',
  day_complete: 'the regular 8 hours were completed',
};

function tabId() {
  let id = sessionStorage.getItem('workcode_tab');
  if (!id) {
    id = `tab-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
    sessionStorage.setItem('workcode_tab', id);
  }
  return id;
}

export function TimerProvider({ children }) {
  const { user } = useAuth();
  const [data, setData] = useState(null);       // last server answer
  const [receivedAt, setReceivedAt] = useState(0);
  const [notice, setNotice] = useState(null);   // { text, tone }
  const [, setTick] = useState(0);
  const lastInput = useRef(Date.now());
  const clientId = useRef(tabId());
  const dataRef = useRef(null);
  const sentState = useRef('active');
  const taskRef = useRef(null);                 // task whose workspace is open; its time is booked on the task
  const timeoutMs = (data?.inactivity_timeout_seconds || INACTIVITY_TIMEOUT / 1000) * 1000;
  const warnMs = (data?.inactivity_warning_seconds || 240) * 1000;
  const limits = useRef({ timeoutMs, warnMs });
  limits.current = { timeoutMs, warnMs };

  const tabState = () => {
    if (document.visibilityState !== 'visible' || !document.hasFocus()) return 'away';
    return Date.now() - lastInput.current >= limits.current.timeoutMs ? 'idle' : 'active';
  };

  const apply = useCallback((d) => {
    const before = dataRef.current?.session?.mode;
    const after = d?.session?.mode;
    if (before && after && before !== after) {
      if (after === 'RUNNING' && before !== 'PAUSED_MANUAL') setNotice({ text: 'Timer resumed automatically.', tone: 'green' });
      else if (after === 'PAUSED_INACTIVE' || after === 'PAUSED_EXTERNAL') {
        setNotice({ text: `Timer paused automatically: ${REASON_TEXT[d.session.pause_reason] || 'not on an approved page'}.`, tone: 'amber' });
      }
    } else if (dataRef.current && d?.regular_completed && !dataRef.current.regular_completed) {
      setNotice({ text: 'Regular 8 hours complete. Press Continue Working if you want to go on — extra time is counted separately.', tone: 'green' });
    }
    dataRef.current = d;
    setData(d);
    setReceivedAt(Date.now());
  }, []);

  const beat = useCallback(async () => {
    const state = tabState();
    sentState.current = state;
    try { apply((await api.post('/sessions/heartbeat', { client_id: clientId.current, state, task_id: taskRef.current })).data); }
    catch (e) { if (e.response?.status === 409) apply({ ...dataRef.current, session: null }); }
  }, [apply]);

  const start = useCallback(async (auto = false) => {
    lastInput.current = Date.now();
    try { apply((await api.post('/sessions/start', { client_id: clientId.current, auto })).data); } catch { /* shown as stopped */ }
  }, [apply]);

  // Entering the app as a signed-in user starts the timer (the server refuses if you pressed Stop today).
  useEffect(() => {
    if (!user) { dataRef.current = null; setData(null); setNotice(null); return undefined; }
    start(true);
    return undefined;
  }, [user, start]);

  const sessionId = data?.session?.id;
  useEffect(() => {
    if (!user || !sessionId) return undefined;
    const interval = setInterval(beat, (dataRef.current?.heartbeat_seconds || 15) * 1000);
    const onChange = () => beat();
    const onInput = (e) => {
      if (e.isTrusted === false && !TESTING) return; // scripted events are not activity
      lastInput.current = Date.now();
      if (sentState.current === 'idle') beat();      // first input after an inactivity pause: resume at once
    };
    document.addEventListener('visibilitychange', onChange);
    window.addEventListener('focus', onChange);
    window.addEventListener('blur', onChange);
    INPUT_EVENTS.forEach((e) => window.addEventListener(e, onInput, { passive: true, capture: true }));
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onChange);
      window.removeEventListener('focus', onChange);
      window.removeEventListener('blur', onChange);
      INPUT_EVENTS.forEach((e) => window.removeEventListener(e, onInput, { capture: true }));
    };
  }, [user, sessionId, beat]);

  // One-second tick: moves the clock, shows the warning, and reports "idle" at exactly 5 minutes.
  useEffect(() => {
    const t = setInterval(() => {
      setTick((n) => n + 1);
      if (dataRef.current?.session && sentState.current === 'active' && tabState() === 'idle') beat();
    }, 1000);
    return () => clearInterval(t);
  }, [beat]);

  useEffect(() => { if (!notice) return undefined; const t = setTimeout(() => setNotice(null), 8000); return () => clearTimeout(t); }, [notice]);

  const action = async (name) => { lastInput.current = Date.now(); try { apply((await api.post(`/sessions/${name}`)).data); } catch { /* ignore */ } };

  const s = data?.session;
  const mode = s?.mode || (s ? (s.state === 'paused' ? 'PAUSED_MANUAL' : 'RUNNING') : 'STOPPED');
  // Between heartbeats the clock is advanced locally for display only (max one heartbeat gap).
  const extra = s && mode === 'RUNNING' ? Math.min((Date.now() - receivedAt) / 1000, 45) : 0;
  const status = !s ? 'stopped' : STATUS[mode] || 'away';
  const quietMs = Date.now() - lastInput.current;
  const focused = typeof document !== 'undefined' && document.visibilityState === 'visible' && document.hasFocus();
  const warning = s && mode === 'RUNNING' && focused && s.category !== 'approved_external' && quietMs >= warnMs && quietMs < timeoutMs
    ? Math.max(1, Math.ceil((timeoutMs - quietMs) / 1000)) : 0;
  const today = data?.today || {};

  const continueSchedule = useCallback(async () => {
    lastInput.current = Date.now();
    try { apply((await api.post('/sessions/continue', { client_id: clientId.current })).data); } catch { /* stays stopped */ }
  }, [apply]);

  const value = {
    setTask: (id) => { taskRef.current = id || null; },
    session: s, status, mode, notice, dismissNotice: () => setNotice(null),
    pauseReason: s?.pause_reason || null, warningSeconds: warning,
    manualStop: !s && !!data?.manual_stop, extensionConnected: !!s?.extension_connected, category: s?.category || null,
    // build 29: the regular 8 h schedule and the separate Continue schedule
    schedule: s?.schedule || null, regularCompleted: !!data?.regular_completed,
    targetSeconds: data?.schedule_target_seconds || 28800,
    regularRemainingSeconds: data?.regular_remaining_seconds ?? 0,
    extraTodaySeconds: data?.extra_seconds_today || 0,
    continueSchedule,
    activeSeconds: (s?.active_seconds || 0) + extra,
    pausedSeconds: (s?.away_seconds || 0) + (s?.idle_seconds || 0) + (s?.paused_seconds || 0),
    todayActiveSeconds: (today.active_seconds || 0) + extra,
    todayAwaySeconds: today.away_seconds || 0,
    todayPausedSeconds: (today.away_seconds || 0) + (today.paused_seconds || 0),   // away already includes inactive time
    isReportingTab: data?.is_reporting_tab ?? true,
    lastLogoutAt: data?.last_logout_at || null,
    sessionSeconds: s ? Math.max(0, (Date.now() - new Date(s.started_at).getTime()) / 1000) : 0,
    start: () => start(false), pause: () => action('pause'), resume: () => action('resume'), stop: () => action('stop'),
  };
  return <TimerContext.Provider value={value}>{children}</TimerContext.Provider>;
}

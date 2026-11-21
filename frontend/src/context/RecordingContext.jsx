import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import api, { errMsg } from '../services/api';
import { useAuth } from './AuthContext';

/** Screen recording. Lives above the router so it keeps running while you move between pages.
 *  The status shown is only "recording" while the browser is really capturing AND the server
 *  accepted the last chunk. A page reload ends a recording (browser rule); the server then
 *  marks it "interrupted".
 *  Build 29: opening the coding workspace starts the recording automatically once the employee
 *  has given consent (consent is remembered per person). "workspace" recordings stop when the
 *  workspace closes or the person signs out. Pausing uses the browser's own recorder pause.
 *  Build 31: stepping outside the tab is never filmed — the moment the workspace is not in front
 *  the recorder is paused (nothing at all is captured), and if the person does not come back
 *  within AWAY_GRACE_SECONDS the recording is closed. Coming back resumes it by itself.
 *  Statuses: off | starting | recording | paused. */
const Ctx = createContext(null);
export const useRecording = () => useContext(Ctx);
const CHUNK_MS = 5000;
const MIME = 'video/webm';
export const AWAY_GRACE_SECONDS = 60;      // how long you may stay outside the tab before the workspace recording ends
const HANDOFF_MS = 4000;                   // the share dialog / Chrome's "sharing" bar steals focus for a moment
const consentKey = (uid) => `workcode_recording_consent:${uid}`;

export function RecordingProvider({ children }) {
  const { user } = useAuth();
  const [status, setStatus] = useState('off');   // off | starting | recording | paused
  const [message, setMessage] = useState('');
  const [startedAt, setStartedAt] = useState(null);
  const [version, setVersion] = useState(0);
  const [retentionDays, setRetentionDays] = useState(30);
  const [needsConsent, setNeedsConsent] = useState(false);
  const ref = useRef({});                         // {recorder, stream, id, queue, failed, source}
  const busy = useRef(false);                     // a start attempt that is still waiting for the browser prompt
  const statusRef = useRef('off');
  statusRef.current = status;
  const startedAtRef = useRef(0);                 // when the browser really started capturing (the dialog time is not counted)
  const awayPaused = useRef(false);               // paused by us because the tab is not in front (a manual Pause is something else)
  const awayTimer = useRef(null);
  const [away, setAway] = useState(false);
  const [awaySince, setAwaySince] = useState(0);   // when the person left, so the workspace can count the remaining grace
  const [awayGrace, setAwayGrace] = useState(AWAY_GRACE_SECONDS);   // from the server, so the number shown is the number used
  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getDisplayMedia && typeof MediaRecorder !== 'undefined';

  // the promises shown in the consent dialog come from the server, so they are always true
  useEffect(() => {
    if (!user) return undefined;                                  // signed out there is nothing to promise; asking would 401
    api.get('/recordings/policy')
      .then((r) => {
        const d = r.data; if (!d || Array.isArray(d)) return;
        if (d.retention_days) setRetentionDays(d.retention_days);
        if (Number.isFinite(d.away_grace_seconds)) setAwayGrace(Math.max(0, d.away_grace_seconds));
      })
      .catch(() => {});
    return undefined;
  }, [user]);
  useEffect(() => { setNeedsConsent(!!user && !localStorage.getItem(consentKey(user.id))); }, [user]);

  /** Closes one recording. `which` names it; without it the recording that is currently on screen is meant.
   *  The browser hands over the last piece of video while it stops, so the queue of THIS recording is waited
   *  for before the server is told it ended — otherwise the tail (up to CHUNK_MS) and everything shorter than
   *  one timeslice would be thrown away, and the video would end before the person actually left. */
  const finish = useCallback(async (failed, text, skipQueue, which) => {
    const r = which || ref.current;
    const live = ref.current === r;
    if (live) {
      ref.current = {};
      busy.current = false;
      clearTimeout(awayTimer.current); awayTimer.current = null;
      awayPaused.current = false; setAway(false); setAwaySince(0);
    }
    if (r.recorder && r.recorder.state !== 'inactive') {
      await new Promise((res) => { r.recorder.addEventListener('stop', res, { once: true }); r.recorder.stop(); });
    }
    r.stream?.getTracks().forEach((t) => t.stop());
    if (r.id) {
      // skipQueue only when this finish was started by the queue itself (a chunk that failed for the third
      // time): waiting for the queue there would wait for this very call and leave the UI stuck on recording
      if (!skipQueue) { try { await r.queue; } catch { /* handled per chunk */ } }
      try { await api.post(`/recordings/${r.id}/stop`, null, { params: { failed: failed || r.failed || undefined } }); } catch { /* server marks it interrupted */ }
    }
    if (live) { setStatus('off'); setStartedAt(null); setMessage(text || ''); setVersion((v) => v + 1); }
  }, []);

  const upload = (rec, blob) => {
    rec.queue = (rec.queue || Promise.resolve()).then(async () => {
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        try { await api.post(`/recordings/${rec.id}/chunk`, blob, { headers: { 'Content-Type': 'application/octet-stream' } }); return; }
        catch (e) { if (attempt === 3) { rec.failed = true; finish(true, `Recording stopped: upload failed (${errMsg(e)}).`, true, rec); } else await new Promise((res) => setTimeout(res, 1500 * attempt)); }
      }
    });
  };

  const start = useCallback(async (taskId, source = 'manual') => {
    if (!supported) { setMessage('This browser cannot record the screen.'); return 'unsupported'; }
    if (ref.current.id || busy.current) return 'already';
    busy.current = true;
    setStatus('starting'); setMessage('');
    let stream;
    try { stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 8 }, audio: false }); }
    catch { busy.current = false; setStatus('off'); setMessage('Not recording: screen sharing was not allowed.'); return 'denied'; }
    try {
      const { data } = await api.post('/recordings/start', { consent: true, task_id: taskId || null, mime_type: MIME });
      const type = MediaRecorder.isTypeSupported('video/webm;codecs=vp8') ? 'video/webm;codecs=vp8' : MIME;
      const recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 500000 });
      const rec = { recorder, stream, id: data.id, source, queue: Promise.resolve(), failed: false };
      ref.current = rec;
      // every piece of video belongs to the recording it came from, not to whatever is on screen now
      recorder.ondataavailable = (e) => { if (e.data.size > 0) upload(rec, e.data); };
      recorder.onerror = () => finish(true, 'Recording stopped: the browser reported a recording error.', false, rec);
      stream.getVideoTracks()[0].addEventListener('ended', () => { if (ref.current === rec || rec.recorder.state !== 'inactive') finish(false, 'Recording stopped: screen sharing ended.', false, rec); });
      recorder.start(CHUNK_MS);
      startedAtRef.current = Date.now();
      setStartedAt(Date.now()); setStatus('recording');
      busy.current = false;
      return 'started';
    } catch (e) {
      stream.getTracks().forEach((t) => t.stop());
      ref.current = {};
      busy.current = false;
      setStatus('off'); setMessage(`Not recording: ${errMsg(e)}`);
      return 'failed';
    }
  }, [supported, finish]);

  /** The workspace calls this when it opens. Nothing is ever captured before the person agreed once
   *  in WORKCODE and the browser granted screen sharing — recording can never run secretly. */
  const autoStart = useCallback((taskId) => {
    if (!supported) return 'unsupported';
    if (ref.current.id || busy.current) return 'already';
    if (needsConsent) return 'needs-consent';
    start(taskId, 'workspace');
    return 'started';
  }, [supported, needsConsent, start]);

  const acceptConsent = useCallback(() => {
    if (user) localStorage.setItem(consentKey(user.id), new Date().toISOString());
    setNeedsConsent(false);
  }, [user]);

  const pause = useCallback(() => {
    const r = ref.current;
    if (r.recorder && r.recorder.state === 'recording') { r.recorder.pause(); setStatus('paused'); }
  }, []);
  const resume = useCallback(() => {
    const r = ref.current;
    if (r.recorder && r.recorder.state === 'paused') { r.recorder.resume(); setStatus('recording'); }
  }, []);

  /** "Leaving the tab is never filmed." When the page stops being what the person is looking at, the
   *  workspace recording is paused at once — the browser's own pause, so nothing is captured — and if
   *  they do not come back within AWAY_GRACE_SECONDS the recording is closed and saved. Coming back
   *  resumes it by itself, so a quick alt-tab costs nothing. A recording started with the Record button
   *  is left alone: that one the person controls.
   *  The browser's share dialog and its "sharing" bar take focus away for a moment, so the first few
   *  seconds after capture starts and the time while the dialog is open are not counted as leaving. */
  const awayWatch = useCallback(() => {
    const r = ref.current;
    if (!r.id || r.source !== 'workspace') return;
    if (busy.current || Date.now() - startedAtRef.current < HANDOFF_MS) return;
    const out = typeof document !== 'undefined' && (document.visibilityState !== 'visible' || !document.hasFocus());
    if (out && statusRef.current === 'recording' && !awayPaused.current) {
      if (!awayGrace) { finish(false, 'Recording stopped: you left the workspace. It starts again when you open it.'); return; }
      pause();
      awayPaused.current = true; setAway(true); setAwaySince(Date.now());
      clearTimeout(awayTimer.current);
      awayTimer.current = setTimeout(() => {
        if (awayPaused.current) finish(false, 'Recording stopped: you were outside the workspace for over '
          + `${Math.round(awayGrace)} s. It starts again when you open it.`);
      }, awayGrace * 1000);
    } else if (!out && awayPaused.current) {
      clearTimeout(awayTimer.current); awayTimer.current = null;
      awayPaused.current = false; setAway(false); setAwaySince(0);
      resume();
    }
  }, [pause, resume, finish, awayGrace]);

  useEffect(() => {
    if (!supported || typeof document === 'undefined') return undefined;
    document.addEventListener('visibilitychange', awayWatch);
    window.addEventListener('blur', awayWatch);
    window.addEventListener('focus', awayWatch);
    return () => {
      clearTimeout(awayTimer.current);
      document.removeEventListener('visibilitychange', awayWatch);
      window.removeEventListener('blur', awayWatch);
      window.removeEventListener('focus', awayWatch);
    };
  }, [supported, awayWatch]);

  /** Leaving the workspace ends the workspace's own recording; a manual Record keeps running. */
  const stopWorkspace = useCallback(() => {
    if (ref.current.source === 'workspace') finish(false, 'Recording stopped: the workspace was closed.');
  }, [finish]);

  const stop = useCallback(() => finish(false, 'Recording saved.'), [finish]);

  useEffect(() => { if (!user && ref.current.id) finish(false, ''); }, [user, finish]);

  return <Ctx.Provider value={{ status, message, startedAt, supported, version, retentionDays, needsConsent, acceptConsent,
    away, awaySince, awayGrace, start, stop, stopWorkspace, autoStart, pause, resume, clearMessage: () => setMessage('') }}>{children}</Ctx.Provider>;
}

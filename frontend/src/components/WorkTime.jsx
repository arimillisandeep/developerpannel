import { useEffect, useState } from 'react';
import api from '../services/api';
import { REASON_TEXT, useTimer } from '../context/TimerContext';
import { meetingTimer, useMeetingTimer } from '../services/meetingTimer';
import { dur, fmtDateTime, hms, stamp } from '../utils/format';

const STATE = { working: ['Active', 'green'], away: ['Paused · away', 'amber'], idle: ['Paused · inactive', 'amber'], paused: ['Paused', ''], stopped: ['Stopped', 'red'] };
export const MODE_LABEL = { RUNNING: 'Running', PAUSED_INACTIVE: 'Paused · inactive', PAUSED_EXTERNAL: 'Paused · away', PAUSED_MANUAL: 'Paused · manual',
  STOPPED: 'Stopped', SESSION_EXPIRED: 'Session expired', NO_SIGNAL: 'No signal' };
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const time = (d) => new Date(d).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

/** Pause / resume history of sessions, straight from the server's transition log. */
export function SessionHistory({ userId, start, end, refresh }) {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => {
    api.get('/timer/sessions', { params: { user_id: userId, start, end } }).then((r) => setRows(r.data)).catch(() => setRows([]));
  }, [userId, start, end, refresh]);
  if (!rows) return <p className="muted">Loading…</p>;
  if (rows.length === 0) return <p className="muted">No sessions in this period.</p>;
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Started</th><th>Ended</th><th>State</th><th>Active</th><th>Paused</th><th>Pauses</th><th /></tr></thead>
      <tbody>{rows.map((s) => {
        const pauses = s.events.filter((e) => e.to.startsWith('PAUSED')).length;
        return [
          <tr key={s.id}><td>{fmtDateTime(s.started_at)}</td><td>{s.ended_at ? fmtDateTime(s.ended_at) : '—'}</td>
            <td>{MODE_LABEL[s.state] || s.state}</td><td>{dur(s.active_seconds)}</td><td>{dur(s.paused_seconds)}</td><td>{pauses}</td>
            <td><button className="btn small" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? 'Hide' : 'History'}</button></td></tr>,
          open === s.id && (
            <tr key={`${s.id}-events`}><td colSpan={7}><ul className="events">{s.events.map((e, i) => (
              <li key={i}>{time(e.at)} · <b>{MODE_LABEL[e.to] || e.to}</b> · {REASON_TEXT[e.reason] || e.reason}</li>))}</ul></td></tr>),
        ];
      })}</tbody></table></div>
  );
}

/** "My working time": every number comes from the server-side timer. */
export default function WorkTime() {
  const t = useTimer();
  const [days, setDays] = useState([]);
  const [history, setHistory] = useState(false);
  const refreshKey = Math.floor(t.todayActiveSeconds / 60); // refetch the table about once a minute
  useEffect(() => { api.get('/attendance', { params: { days: 7 } }).then((r) => setDays(r.data)).catch(() => {}); }, [refreshKey, t.status]);
  const [text, tone] = STATE[t.status];
  const today = new Date().toLocaleDateString('en-CA');
  const mt = useMeetingTimer();
  // the server says which row is its "today"; the local date is only the fallback (a computer in another
  // timezone must never show empty cards for a day the server has already counted)
  const isToday = (d) => (typeof d.is_today === 'boolean' ? d.is_today : d.day === today);
  const row = days.find(isToday) || days.find((d) => d.day === today) || {};
  // between two answers of the server the cards may tick forward, never backwards: the larger of the two wins
  const regularNow = Math.max(t.todayActiveSeconds || 0, row.active_seconds || 0);
  const extraNow = Math.max(t.extraTodaySeconds || 0, row.extra_seconds || 0);
  const meetNow = Math.max(mt.todaySeconds || 0, row.meeting_seconds || 0);
  const actual = regularNow + extraNow;                       // what attendance uses: no minute twice
  const grand = actual + meetNow;                              // build 34 card: meetings added again
  const pct = t.targetSeconds ? Math.min(100, Math.round((regularNow / t.targetSeconds) * 100)) : 0;
  return (
    <div className="card">
      <div className="row spread" style={{ marginBottom: 14 }}>
        <div className="row"><h2 style={{ margin: 0 }}>My working time</h2><span className={`badge ${tone}`}>{text}</span>
          {t.pauseReason && <span className="muted">Reason: {REASON_TEXT[t.pauseReason] || t.pauseReason}</span>}</div>
        <span className="muted">{zone} · server timestamps</span>
      </div>
      {t.warningSeconds > 0 && <div className="notice" role="alert">No activity for 4 minutes. The timer pauses in {t.warningSeconds} seconds unless you move the mouse or type.</div>}
      <h3 style={{ margin: '16px 0 6px' }}>My Working Timers <span className={`badge ${tone}`}>{text}</span></h3>
      <div className="grid g4" style={{ gap: 12 }} data-testid="working-timers">
        <div className="stat" data-testid="card-regular">
          <div className="label">Regular Work Timer</div>
          <div className="value" style={{ whiteSpace: 'nowrap' }}>{hms(regularNow)}</div>
          <div style={{ height: 6, borderRadius: 4, background: 'var(--line, #22304d)', marginTop: 10 }}>
            <div data-testid="regular-progress" style={{ height: 6, width: `${pct}%`, borderRadius: 4, background: '#3fb950' }} /></div>
          <div className="sub">{pct}% completed of {hms(t.targetSeconds)} · <span className={`badge ${t.regularCompleted ? 'green' : ''}`}>{t.regularCompleted ? '8 h done' : (MODE_LABEL[t.mode] || t.status)}</span></div>
          <div className="row" style={{ gap: 6, marginTop: 10 }}>
            {t.session
              ? <><button className="btn small" onClick={t.mode === 'RUNNING' ? t.pause : t.resume}>{t.mode === 'RUNNING' ? 'Pause' : 'Resume'}</button>
                  <button className="btn small danger" onClick={t.stop}>Stop</button></>
              : <button className="btn small primary" onClick={t.start}>Start</button>}
          </div>
        </div>
        <div className="stat" data-testid="card-meeting">
          <div className="label">Meeting Timer</div>
          <div className="value">{hms(meetNow)}</div>
          <div className="sub">{row.meetings || 0} meeting(s) today · this week {dur(mt.weekSeconds || 0)} · this month {dur(mt.monthSeconds || 0)}</div>
          <div style={{ marginTop: 10 }}>{mt.current
            ? <span className="badge green" role="status">Running · {mt.current.title}</span>
            : <span className="badge">No meeting now</span>}</div>
          <div className="row" style={{ gap: 6, marginTop: 10 }}>
            {mt.current && <button className="btn small" onClick={() => meetingTimer.leave(mt.current.meeting_id).catch(() => {})}>Leave meeting</button>}
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Automatic: the browser extension or the Join / Leave button starts and stops it.
            There is no manual pause, so no time can be added by hand.</div>
        </div>
        <div className="stat" data-testid="card-extra">
          <div className="label">Extra Work Timer</div>
          <div className="value">{hms(extraNow)}</div>
          <div className="sub">After 8 hours · <span className={`badge ${t.schedule === 'extra' ? 'green' : ''}`}>{t.schedule === 'extra' ? 'Running' : (t.regularCompleted ? 'Ready' : 'Locked until 8 h')}</span></div>
          <div className="row" style={{ gap: 6, marginTop: 10 }}>
            {t.schedule === 'extra'
              ? <><button className="btn small" onClick={t.mode === 'RUNNING' ? t.pause : t.resume}>{t.mode === 'RUNNING' ? 'Pause' : 'Resume'}</button>
                  <button className="btn small danger" onClick={t.stop}>Stop</button></>
              : <button className="btn small primary" disabled={!t.regularCompleted || !!t.session} onClick={t.continueSchedule}>Continue Working</button>}
          </div>
        </div>
        <div className="stat" data-testid="card-total" style={{ borderColor: 'rgba(63,185,80,.45)' }}>
          <div className="label">Total Time (All)</div>
          <div className="value" style={{ color: '#3fb950' }} data-testid="grand-total-value">{hms(grand)}</div>
          <div className="sub">Regular + Meeting + Extra</div>
          <div className="muted" style={{ fontSize: 12, marginTop: 10 }} data-testid="actual-time">
            Actual working time (no double count): <b>{hms(actual)}</b></div>
        </div>
      </div>
      <div className="row inline" data-testid="today-summary" style={{ gap: 14, marginTop: 12, flexWrap: 'wrap' }}>
        <span><b>Today's Summary</b> <span className="muted">({today})</span></span>
        <span className="muted">Regular Work <b style={{ color: 'inherit' }}>{hms(regularNow)}</b></span>
        <span className="muted">Meeting Time <b style={{ color: 'inherit' }}>{hms(meetNow)}</b></span>
        <span className="muted">Extra Work <b style={{ color: 'inherit' }}>{hms(extraNow)}</b></span>
        <span className="muted">Total Time <span className="badge green" data-testid="summary-grand">{hms(grand)}</span></span>
      </div>
      <div className="grid g6 tiles6" style={{ gap: 12 }}>
        <div className="tile"><div className="label">Active</div><div className="value">{hms(t.activeSeconds)}</div></div>
        <div className="tile"><div className="label">Away</div><div className="value">{dur(t.pausedSeconds)}</div></div>
        <div className="tile"><div className="label">Session</div><div className="value">{t.session ? dur(t.sessionSeconds) : '—'}</div></div>
        <div className="tile"><div className="label">Login</div><div className="value">{stamp(t.session?.started_at)}</div></div>
        <div className="tile"><div className="label">Logout</div><div className="value">{stamp(t.lastLogoutAt)}</div></div>
        <div className="tile"><div className="label">Last return</div><div className="value">{stamp(t.session?.last_return_at)}</div></div>
      </div>
      {t.schedule === 'extra'
        ? <div className="notice" data-testid="extra-timer" role="status">Continue schedule is running: <b>{hms(t.extraTodaySeconds)}</b> extra today.
          Extra time is kept apart from the regular 8 hours; use the top-bar buttons to Pause, Resume or Stop.</div>
        : t.regularCompleted
          ? <div className="row spread" data-testid="extra-timer" style={{ marginTop: 12 }}>
              <span className="muted">Regular 8 hours complete · extra today <b>{hms(t.extraTodaySeconds)}</b>.</span>
              <button className="btn small primary" onClick={t.continueSchedule}>Continue Working</button></div>
          : null}
      <p className="muted" style={{ margin: '12px 0 0' }}>
        Today: <b>{dur(t.todayActiveSeconds)}</b> working · <b>{dur(t.todayPausedSeconds)}</b> paused
        {t.extraTodaySeconds > 0 ? <> · <b>{dur(t.extraTodaySeconds)}</b> extra</> : null} · Browser extension: {t.extensionConnected ? 'connected' : 'not connected'}</p>
      <h3 style={{ margin: '20px 0 4px' }}>Daily attendance</h3>
      {days.length === 0 ? <p className="muted">No working time recorded yet.</p> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Date</th><th>Regular Work</th><th>Meeting Time</th><th>8 h</th><th>Extra Work</th><th>Total Time</th><th>Away</th><th>Paused</th><th>Status</th></tr></thead>
          <tbody>{days.map((d) => {
            // the numbers in the row are the numbers in the cards: today's row ticks with the same live clock
            // and its Total is always the sum of its own three columns, so nothing contradicts anything else
            const live = isToday(d);
            const reg = Math.max(d.active_seconds || 0, live ? t.todayActiveSeconds || 0 : 0);
            const ext = Math.max(d.extra_seconds || 0, live ? t.extraTodaySeconds || 0 : 0);
            const mee = Math.max(d.meeting_seconds || 0, live ? meetNow : 0);
            return (
            <tr key={d.day} data-testid={live ? 'today-row' : undefined}><td>{d.day}</td>
              <td>{hms(reg)}</td>
              <td data-testid={`meeting-${d.day}`}>{hms(mee)}</td>
              <td>{d.regular_completed_at ? <span className="badge green">done</span> : '—'}</td>
              <td>{hms(ext)}</td>
              <td data-testid={`total-${d.day}`}><b>{hms(reg + ext + mee)}</b></td>
              <td>{dur(d.away_seconds)}</td><td>{dur(d.paused_seconds)}</td><td>{d.status}</td></tr>); })}
          </tbody></table></div>)}
      <div className="row spread" style={{ margin: '18px 0 4px' }}><h3 style={{ margin: 0 }}>Session history</h3>
        <button className="btn small" onClick={() => setHistory(!history)}>{history ? 'Hide' : 'Show today'}</button></div>
      {history && <SessionHistory refresh={t.mode} />}
      <p className="muted" style={{ margin: '12px 0 0', fontSize: 13 }} data-testid="total-time-note">
        Total Time = Regular Work + Meeting Time + Extra Work. Meeting hours are added again on purpose, also the ones that
        ran inside a work session — that is the Grand Total view. The attendance figure is <b>Actual working time</b>{' '}(Regular + Extra),
        which never counts a minute twice. Regular work target: {hms(t.targetSeconds)} (8 hours).
        After completion, the Extra Work timer can be used.
      </p>
      <p className="muted" style={{ margin: '12px 0 0', fontSize: 13 }}>
        The timer runs by itself while you work in WORKCODE and pauses after 5 minutes without mouse or keyboard input, or when you leave
        WORKCODE. With the WORKCODE browser extension, approved websites also count. A silent gap is never counted for more than 45 seconds.</p>
    </div>
  );
}

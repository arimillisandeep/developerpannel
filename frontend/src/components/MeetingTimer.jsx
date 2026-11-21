import { Fragment, useEffect, useState } from 'react';
import api, { errMsg } from '../services/api';
import { meetingTimer, useMeetingTimer } from '../services/meetingTimer';
import { ErrorBox } from './ui';
import { rangeFor } from './TimerAdmin';
import { ROLE_LABEL, dur, hms } from '../utils/format';

const time = (d) => (d ? new Date(d).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '');
const day = (d) => new Date(d).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
export const SOURCE_TEXT = { extension: 'Automatic (browser extension)', manual: 'Join / Leave button' };
const firstJoin = (r) => (r.stays.length ? `${day(r.stays[0].joined_at)} ${time(r.stays[0].joined_at)}` : '—');
const lastLeave = (r) => {
  const s = r.stays.filter((x) => x.left_at).slice(-1)[0];
  if (s) return `${day(s.left_at)} ${time(s.left_at)}`;
  return r.in_meeting ? 'still in the meeting' : '—';
};
export const END_TEXT = { left: 'Pressed Leave', tab_closed: 'Meeting tab closed', no_signal: 'No signal (browser closed or offline)',
  limit: 'Not left: ended 1 hour after the planned end', switched: 'Joined another meeting', cancelled: 'Meeting cancelled' };

/** Top bar: shown only while the person is in a meeting. Sits next to the work timer and never changes it. */
export function MeetingTimerPill() {
  const m = useMeetingTimer();
  if (!m.current) return null;
  return (
    <div className="timer meeting-timer" role="status" aria-label="Meeting timer" title={`Meeting timer · ${SOURCE_TEXT[m.current.source]}. It is separate from the work timer.`}>
      <span className="dot meeting" /><div><div className="clock">{hms(m.seconds)}</div><small>in meeting · {m.current.title}</small></div>
      <button className="btn small" onClick={() => meetingTimer.leave(m.current.meeting_id).catch(() => {})}>Leave meeting</button>
    </div>
  );
}

const RANGES = [['today', 'Today'], ['yesterday', 'Yesterday'], ['week', 'This week'], ['month', 'This month']];

/** Work timer and meeting timer side by side per person, with every join and leave. */
export function MeetingTimeReport({ title = 'Work time and meeting time' }) {
  const [key, setKey] = useState('today');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(null);
  useEffect(() => {
    const [start, end] = rangeFor(key);
    const load = () => api.get('/meetings/timer/report', { params: { start, end } })
      .then((r) => { setData({ ...r.data, at: Date.now() }); setError(''); }).catch((e) => setError(errMsg(e)));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [key]);
  const rows = data?.rows || [];
  const total = rows.reduce((n, r) => n + r.meeting_seconds, 0);
  /** The same rows, filters and totals as a file — the server writes it, so nothing is recomputed here. */
  const download = async () => {
    const [start, end] = rangeFor(key);
    try {
      const r = await api.get('/meetings/timer/report', { params: { start, end, format: 'csv' }, responseType: 'blob' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(r.data);
      a.download = `workcode-meetings-${start}-to-${end}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { setError(errMsg(e)); }
  };
  return (
    <div className="card" data-testid="meeting-report">
      <div className="row spread"><h2>{title}</h2>
        <span className="row inline" style={{ gap: 10 }}>
          <span className="muted">{rows.filter((r) => r.in_meeting).length} in a meeting now · {dur(total)} meeting time in range</span>
          <span className="muted" data-testid="meeting-counts">{rows.reduce((n, r) => n + r.meetings, 0)} meetings · {rows.reduce((n, r) => n + r.joins, 0)} joins</span>
          <button className="btn small" onClick={download}>Export CSV</button>
        </span></div>
      <p className="muted" style={{ marginTop: 0 }}>Two separate timers. <b>Work timer</b> = active time counted by the work timer. <b>Meeting timer</b> = time between joining and leaving scheduled external meetings (Google Meet, Zoom, Teams). Neither changes the other.</p>
      <div className="filters">{RANGES.map(([k, l]) => <button key={k} className={`btn small ${key === k ? 'on primary' : ''}`} onClick={() => setKey(k)}>{l}</button>)}</div>
      <ErrorBox error={error} />
      {data && rows.length === 0 && <div className="empty">Nobody to show.</div>}
      {rows.length > 0 && (
        <div className="table-wrap"><table><thead><tr><th>Employee</th><th>Work timer</th><th>Meeting timer</th><th>Meetings</th><th>Joins</th><th>Start</th><th>End</th><th>Now</th><th /></tr></thead>
          <tbody>{rows.map((r) => (
            <Fragment key={r.user_id}>
              <tr>
                <td><b>{r.full_name}</b><div className="muted">{ROLE_LABEL[r.role] || r.role}</div></td>
                <td>{dur(r.work_seconds)}</td>
                <td><b>{dur(r.meeting_seconds)}</b></td>
                <td>{r.meetings}</td><td>{r.joins}</td>
                <td>{firstJoin(r)}</td><td>{lastLeave(r)}</td>
                <td>{r.in_meeting ? <span className="badge green">In meeting · {r.in_meeting.title}</span> : <span className="muted">—</span>}</td>
                <td style={{ textAlign: 'right' }}>{r.joins > 0 && <button className="btn small" aria-expanded={open === r.user_id} onClick={() => setOpen(open === r.user_id ? null : r.user_id)}>{open === r.user_id ? 'Hide' : 'Join / leave details'}</button>}</td>
              </tr>
              {open === r.user_id && (
                <tr><td colSpan={9} style={{ background: 'rgba(255,255,255,.02)' }}>
                  <table aria-label={`Join and leave details of ${r.full_name}`}><thead><tr><th>Date</th><th>Meeting</th><th>Joined</th><th>Left</th><th>Duration</th><th>Detected by</th><th>Ended because</th></tr></thead>
                    <tbody>{r.stays.map((s) => (
                      <tr key={s.id}><td>{day(s.joined_at)}</td><td>{s.title}</td><td>{time(s.joined_at)}</td>
                        <td>{s.left_at ? time(s.left_at) : <span className="badge green">still in the meeting</span>}</td>
                        <td>{dur(s.seconds)}</td><td>{SOURCE_TEXT[s.source] || s.source}</td><td>{s.left_at ? (END_TEXT[s.end_reason] || s.end_reason) : '—'}</td></tr>))}
                      <tr><td colSpan={4} style={{ textAlign: 'right' }}><b>Total meeting duration</b></td><td colSpan={3}><b>{dur(r.meeting_seconds)}</b></td></tr>
                    </tbody></table>
                </td></tr>)}
            </Fragment>))}
          </tbody></table></div>)}
    </div>
  );
}

import { useEffect, useState } from 'react';
import api, { errMsg } from '../services/api';
import { ErrorBox, Modal, Stat } from './ui';
import { REASON_TEXT } from '../context/TimerContext';
import { MODE_LABEL, SessionHistory } from './WorkTime';
import { ROLE_LABEL, dur, fmtDateTime, hms, stamp } from '../utils/format';

const iso = (d) => d.toLocaleDateString('en-CA');
export function rangeFor(key, now = new Date()) {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (key === 'yesterday') { d.setDate(d.getDate() - 1); return [iso(d), iso(d)]; }
  if (key === 'week') { const m = new Date(d); m.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return [iso(m), iso(d)]; }
  if (key === 'month') return [iso(new Date(d.getFullYear(), d.getMonth(), 1)), iso(d)];
  return [iso(d), iso(d)];
}
const RANGES = [['today', 'Today'], ['yesterday', 'Yesterday'], ['week', 'This week'], ['month', 'This month'], ['custom', 'Custom']];
const TONE = { RUNNING: 'green', PAUSED_INACTIVE: 'amber', PAUSED_EXTERNAL: 'amber', NO_SIGNAL: 'red', SESSION_EXPIRED: 'red' };
const CATEGORY = { workcode: 'WORKCODE', approved_external: 'Approved website' };

/** Timer state and totals per person, with period filters, pause history and CSV export. */
export function TimerReport({ title = 'Automatic timer report' }) {
  const [key, setKey] = useState('today');
  const [[start, end], setRange] = useState(rangeFor('today'));
  const [role, setRole] = useState('');
  const [rows, setRows] = useState(null);
  const [totals, setTotals] = useState(null);
  const [error, setError] = useState('');
  const [person, setPerson] = useState(null);
  const pick = (k) => { setKey(k); if (k !== 'custom') setRange(rangeFor(k)); };
  useEffect(() => {
    if (!start || !end) return undefined;
    const load = () => api.get('/timer/overview', { params: { start, end, role: role || undefined } })
      .then((r) => { setRows(r.data.rows); setTotals(r.data.totals || null); setError(''); })
      .catch((e) => setError(errMsg(e)));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [start, end, role]);
  const download = async () => {
    try {
      const r = await api.get('/timer/overview', { params: { start, end, role: role || undefined, format: 'csv' }, responseType: 'blob' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(r.data);
      a.download = `workcode-timer-${start}-to-${end}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { setError(errMsg(e)); }
  };
  return (
    <div className="card">
      <div className="row spread"><h2>{title}</h2><button className="btn small" onClick={download}>Export CSV</button></div>
      <div className="filters">
        {RANGES.map(([k, l]) => <button key={k} className={`btn small ${key === k ? 'on primary' : ''}`} onClick={() => pick(k)}>{l}</button>)}
        {key === 'custom' && <>
          <input type="date" aria-label="From" value={start} max={end} onChange={(e) => setRange([e.target.value, end])} />
          <input type="date" aria-label="To" value={end} min={start} onChange={(e) => setRange([start, e.target.value])} /></>}
        <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">All roles</option>{Object.entries(ROLE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      </div>
      <ErrorBox error={error} />
      {rows && rows.length === 0 && <div className="empty">Nobody matches this filter.</div>}
      {rows && rows.length > 0 && (() => {
        const sum = (k) => rows.reduce((a, r) => a + (r[k] || 0), 0);
        const t = totals || { regular_seconds: sum('active_seconds'), extra_seconds: sum('extra_seconds'),
          meeting_seconds: sum('meeting_seconds'), meeting_work_seconds: sum('meeting_work_seconds'),
          meeting_outside_seconds: sum('meeting_outside_seconds'), active_seconds: sum('active_seconds') + sum('extra_seconds'),
          paused_seconds: sum('paused_seconds'), inactive_seconds: sum('inactive_seconds'),
          total_seconds: sum('active_seconds') + sum('extra_seconds'),
          grand_total_seconds: sum('active_seconds') + sum('extra_seconds') + sum('meeting_seconds'),
          meetings: sum('meetings'), meeting_joins: sum('meeting_joins') };
        const grand = t.grand_total_seconds ?? ((t.total_seconds || 0) + (t.meeting_seconds || 0));
        return (
          <>
            <div data-testid="range-totals">
              <div className="grid g4" style={{ gap: 12, marginBottom: 8 }}>
                <div data-testid="total-regular"><Stat title="Regular working hours" value={dur(t.regular_seconds)}
                  sub="on the 8 h schedule" /></div>
                <div data-testid="total-extra"><Stat title="Extra working hours" value={dur(t.extra_seconds)}
                  sub="after the day was completed" /></div>
                <div data-testid="total-meeting"><Stat title="Meeting hours" value={dur(t.meeting_seconds || 0)}
                  sub={`${t.meetings || 0} meeting(s) · ${dur(t.meeting_work_seconds || 0)} inside work`} /></div>
                <div data-testid="total-grand"><Stat title="Grand total hours" value={dur(grand)}
                  sub="regular + extra + meeting" /></div>
              </div>
              <div className="row inline muted" style={{ gap: 10, marginBottom: 8, fontSize: 13, flexWrap: 'wrap' }}>
                <span title="Active = regular + extra">Active: {dur(t.active_seconds)}</span>
                <span>Paused: {dur(t.paused_seconds)}</span>
                <span>Inactive: {dur(t.inactive_seconds)}</span>
                <span data-testid="range-total-hours" title="Actual working time: meetings that ran inside it are not added a second time">
                  Total working hours: {dur(t.total_seconds)}</span>
                {(t.meeting_outside_seconds || 0) > 0 && <span data-testid="range-meeting-outside"
                  title="Meeting time outside an active work session — reported, never counted as work">
                  Meeting outside work: {dur(t.meeting_outside_seconds)}</span>}
                <span data-testid="grand-total-note">Grand total adds the {dur(t.meeting_seconds || 0)} of meetings on
                  purpose, even the ones that ran inside regular or extra hours.</span>
              </div>
            </div>
            <div className="table-wrap"><table>
              <thead><tr><th>Name</th><th>Role</th><th>State</th><th>Today</th><th>Regular Work</th><th>Extra Working Time</th><th>Meeting Time</th><th>Grand Total</th><th>Schedule</th><th>Recording</th>
                <th>Active</th><th>Paused</th><th>Inactive</th>
                <th>Last activity</th><th>Session start</th><th>Last end</th><th>On</th><th /></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.user_id}><td>{r.full_name}</td><td>{ROLE_LABEL[r.role]}</td>
                  <td><span className={`badge ${TONE[r.state] || ''}`} title={r.pause_reason ? REASON_TEXT[r.pause_reason] || r.pause_reason : ''}>{MODE_LABEL[r.state] || r.state}</span></td>
                  <td>{dur(r.today_active_seconds)}</td>
                  <td data-testid="schedule-cell">{r.regular_completed
                    ? <span className="badge green" title={`regular day completed ${fmtDateTime(r.regular_completed_at)}`}>8 h done</span>
                    : <span title="active time today / regular target">{dur(r.today_active_seconds)} <span className="muted">/ {dur(r.schedule_target_seconds || 28800)}</span></span>}</td>
                  <td>{dur(r.extra_seconds_today || 0)}{r.extra_running ? <span className="badge green" title="the Continue timer is running now"> running</span> : ''}</td>
                  <td data-testid="meeting-cell" title={`${r.meetings || 0} meeting(s), ${r.meeting_joins || 0} join(s) · ${dur(r.meeting_work_seconds || 0)} inside a work session`}>
                    {dur(r.meeting_seconds || 0)}{r.in_meeting ? <span className="badge green" role="status"> in meeting</span> : ''}</td>
                  <td data-testid="grand-cell" title="regular + extra + meeting, meeting counted again on purpose">
                    <b>{dur(r.grand_total_seconds ?? (r.total_seconds || 0) + (r.meeting_seconds || 0))}</b></td>
                  <td data-testid="schedule-col">{r.schedule_label || 'Regular'}</td>
                  <td>{r.recording === 'recording' ? <span className="badge red" role="status">● live</span> : '—'}</td>
                  <td>{dur(r.active_seconds)}</td><td>{dur(r.paused_seconds)}</td>
                  <td title="Not active for this long right now">{dur(r.inactive_seconds)}{r.inactive_for_seconds > 0 ? ` (now ${dur(r.inactive_for_seconds)})` : ''}</td>
                  <td>{fmtDateTime(r.last_activity_at)}</td><td>{fmtDateTime(r.session_start)}</td><td>{fmtDateTime(r.session_end)}</td>
                  <td>{CATEGORY[r.category] || '—'}</td>
                  <td><button className="btn small" onClick={() => setPerson(r)}>History</button></td></tr>))}
              </tbody></table></div>
          </>);
      })()}
      <p className="muted" style={{ fontSize: 13, margin: '10px 0 0' }}>Active, Paused and Inactive are totals for the chosen period. Paused = inactive + away / unapproved site + manual pause.
        The regular 8 h schedule and the Continue schedule are counted apart: extra time never moves the regular totals.
        Total working hours is the actual time (an 8 h day with a 2 h Google Meet inside it reads Total 8 h), while the
        <b> Grand total</b> adds the meeting hours separately on purpose: Regular 8 h + Extra 2 h + Meeting 1 h 30m =
        Grand total 11 h 30m. Both numbers come from the server for the exact date range and role filter in use.</p>
      {person && <Modal wide title={`Pause and resume history · ${person.full_name}`} onClose={() => setPerson(null)}>
        <SessionHistory userId={person.user_id} start={start} end={end} /></Modal>}
    </div>
  );
}

/** Build 30: "Extra work today" — the regular 8 h status and the separate Continue schedule, one row per person. */
export function ExtraWorkToday() {
  const [rows, setRows] = useState(null);
  const [totals, setTotals] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const load = () => api.get('/timer/overview').then((r) => { setRows(r.data.rows); setError(''); }).catch((e) => setError(errMsg(e)));
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="card" data-testid="extra-work">
      <div className="row spread"><h2>Extra work today</h2><span className="muted">Regular 8 h and the Continue schedule, apart</span></div>
      <ErrorBox error={error} />
      {!rows && <p className="muted">Loading…</p>}
      {rows && rows.length === 0 && <div className="empty">Nobody to show.</div>}
      {rows && rows.length > 0 && (
        <div className="table-wrap"><table>
          <thead><tr><th>Employee</th><th>Regular time</th><th>Status</th><th>Extra time</th><th>Extra timer</th><th>Extra session</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.user_id}><td>{r.full_name}<div className="muted">{ROLE_LABEL[r.role]}</div></td>
              <td>{hms(r.today_active_seconds || 0)}<span className="muted"> / {hms(r.schedule_target_seconds || 28800)}</span></td>
              <td>{r.regular_completed ? <span className="badge green">Completed</span> : <span className="badge">In progress</span>}</td>
              <td>{hms(r.extra_seconds_today || 0)}</td>
              <td>{r.extra_running ? <span className="badge green" role="status">Running</span> : '—'}</td>
              <td className="muted">{r.extra_start
                ? `${stamp(r.extra_start)}${r.extra_end ? ` → ${stamp(r.extra_end)}` : ' → now'}` : '—'}</td></tr>))}
          </tbody></table></div>)}
    </div>);
}

/** Approved websites. Everyone can read the list; only admins can change it. */
export function AllowedSites({ canEdit }) {
  const [sites, setSites] = useState([]);
  const [form, setForm] = useState({ domain: '', label: '', ignore_inactivity: false });
  const [error, setError] = useState('');
  const load = () => api.get('/timer/allowlist').then((r) => setSites(r.data)).catch((e) => setError(errMsg(e)));
  useEffect(() => { load(); }, []);
  const add = async (e) => {
    e.preventDefault();
    try { await api.post('/timer/allowlist', form); setForm({ domain: '', label: '', ignore_inactivity: false }); setError(''); load(); }
    catch (x) { setError(errMsg(x)); }
  };
  const remove = async (id) => { try { await api.delete(`/timer/allowlist/${id}`); load(); } catch (x) { setError(errMsg(x)); } };
  return (
    <div className="card">
      <h2>Approved websites</h2>
      <p className="muted">With the WORKCODE browser extension, the timer keeps running on these websites. Every other website pauses it.</p>
      <ErrorBox error={error} />
      {sites.length === 0 ? <div className="empty">No approved websites.</div> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Website</th><th>Name</th><th>5-minute inactivity rule</th>{canEdit && <th />}</tr></thead>
          <tbody>{sites.map((s) => (
            <tr key={s.id}><td><a href={`https://${s.domain}/`} target="_blank" rel="noopener noreferrer">{s.domain} ↗</a></td><td>{s.label || '—'}</td>
              <td>{s.ignore_inactivity ? 'Off (meetings: listening counts)' : 'On'}</td>
              {canEdit && <td><button className="btn small danger" onClick={() => remove(s.id)} aria-label={`Remove ${s.domain}`}>Remove</button></td>}</tr>))}
          </tbody></table></div>)}
      {canEdit && (
        <form className="filters" onSubmit={add}>
          <input aria-label="Website domain" placeholder="example.com" value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} required />
          <input aria-label="Name" placeholder="Name (optional)" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={form.ignore_inactivity} onChange={(e) => setForm({ ...form, ignore_inactivity: e.target.checked })} />Meeting site (no inactivity pause)</label>
          <button className="btn primary small">Add website</button>
        </form>)}
    </div>
  );
}

/** Connects the Chrome extension: creates a code the user pastes into the extension popup. */
export function ExtensionCard() {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const create = async () => {
    try {
      const r = await api.post('/extension/token');
      setCode(`${window.location.origin}|${r.data.token}`); setError(''); setCopied(false);
    } catch (e) { setError(errMsg(e)); }
  };
  const copy = async () => { try { await navigator.clipboard.writeText(code); setCopied(true); } catch { setCopied(false); } };
  return (
    <div className="card">
      <h2>WORKCODE browser extension</h2>
      <p className="muted">Without the extension, WORKCODE cannot see other tabs, so the timer pauses whenever you leave the WORKCODE tab.
        The extension reports only the kind of page in front (WORKCODE, approved, not approved, or browser not in front) and the name of
        an approved website. It never reads page content, passwords, messages or the addresses of other websites.
        It also runs the <b>meeting timer</b>: when the page of one of your scheduled meetings (Google Meet, Zoom, Teams) is open in a tab the meeting timer runs, and it stops when you close that tab.</p>
      <ErrorBox error={error} />
      <ol className="muted" style={{ paddingLeft: 18, lineHeight: 1.7 }}>
        <li>Chrome → <b>chrome://extensions</b> → Developer mode → Load unpacked → choose the <b>extension</b> folder of the project.</li>
        <li>Create a connection code here and paste it into the extension popup.</li>
      </ol>
      <button className="btn primary" onClick={create}>Create connection code</button>
      {code && <div style={{ marginTop: 12 }}>
        <textarea readOnly aria-label="Connection code" value={code} rows={3} style={{ width: '100%', fontSize: 12 }} onFocus={(e) => e.target.select()} />
        <div className="row" style={{ marginTop: 6 }}><button className="btn small" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
          <span className="muted">Valid for 30 days, for your account only. Treat it like a password.</span></div></div>}
    </div>
  );
}

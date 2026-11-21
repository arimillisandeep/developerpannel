import { useCallback, useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, Field, Modal, PageHead } from '../../components/ui';
import { useNotifications } from '../../context/NotificationContext';
import { ROLE_LABEL, dur, fmtDateTime, hms } from '../../utils/format';
import { meetingTimer, useMeetingTimer } from '../../services/meetingTimer';
import { ExtensionCard } from '../../components/TimerAdmin';

function MeetingForm({ people, onDone, onClose }) {
  const [f, setF] = useState({ title: '', agenda: '', when: '', duration_minutes: 30, link: '' });
  const [picked, setPicked] = useState([]);
  const [error, setError] = useState('');
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const submit = async (e) => {
    e.preventDefault();
    if (!picked.length) { setError('Choose at least one participant'); return; }
    try {
      await api.post('/meetings', { title: f.title, agenda: f.agenda || null, starts_at: new Date(f.when).toISOString(),
        duration_minutes: Number(f.duration_minutes), link: f.link || null, participant_ids: picked });
      onDone();
    } catch (err) { setError(errMsg(err)); }
  };
  return (
    <Modal title="Schedule a meeting" onClose={onClose} wide>
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Title"><input required minLength={3} value={f.title} onChange={set('title')} /></Field>
        <div className="grid g2">
          <Field label="Date and time"><input type="datetime-local" required value={f.when} onChange={set('when')} /></Field>
          <Field label="Duration (minutes)"><input type="number" min="5" max="600" value={f.duration_minutes} onChange={set('duration_minutes')} /></Field>
        </div>
        <Field label="Meeting link (https://…, for example a Google Meet link)"><input type="url" placeholder="https://meet.google.com/…" value={f.link} onChange={set('link')} /></Field>
        <Field label="Agenda"><textarea value={f.agenda} onChange={set('agenda')} /></Field>
        <Field label={`Participants (${picked.length} selected)`}>
          <div className="tile" style={{ maxHeight: 180, overflow: 'auto' }}>{people.map((p) => (
            <label key={p.id} className="row" style={{ padding: '3px 0' }}>
              <input type="checkbox" style={{ width: 'auto' }} checked={picked.includes(p.id)} onChange={() => toggle(p.id)} />
              {p.full_name} <span className="muted">({ROLE_LABEL[p.role]})</span></label>))}</div></Field>
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary">Schedule</button></div>
      </form>
    </Modal>
  );
}

export default function Meetings() {
  const { version } = useNotifications();
  const [rows, setRows] = useState(null);
  const [people, setPeople] = useState([]);
  const [form, setForm] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(() => { api.get('/meetings').then((r) => setRows(r.data)).catch((e) => setError(errMsg(e))); }, []);
  useEffect(() => { load(); }, [load, version]);
  useEffect(() => { api.get('/meetings/invitable').then((r) => setPeople(r.data)).catch(() => {}); }, []);
  const mt = useMeetingTimer();
  // Fallback start of the meeting timer. With the browser extension the timer also starts and stops by itself.
  const joined = (m) => { meetingTimer.join(m.id).catch((e) => setError(`Meeting timer: ${errMsg(e)}`)); };
  const leave = (m) => { meetingTimer.leave(m.id).catch((e) => setError(errMsg(e))); };
  const cancel = async (m) => { try { await api.delete(`/meetings/${m.id}`); load(); } catch (e) { setError(errMsg(e)); } };
  const now = Date.now();
  const upcoming = (rows || []).filter((m) => !m.cancelled && new Date(m.starts_at).getTime() + m.duration_minutes * 60000 >= now).reverse();
  const past = (rows || []).filter((m) => !upcoming.includes(m));
  const Table = ({ list, history }) => (list.length === 0 ? <div className="empty">{history ? 'No past meetings.' : 'No upcoming meetings.'}</div> : (
    <div className="table-wrap"><table><thead><tr><th>When</th><th>Meeting</th><th>Organiser</th><th>Participants</th><th /></tr></thead>
      <tbody>{list.map((m) => (
        <tr key={m.id}><td>{fmtDateTime(m.starts_at)}<div className="muted">{m.duration_minutes} min</div></td>
          <td><b>{m.title}</b> {m.cancelled && <span className="badge red">cancelled</span>}{m.agenda && <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>{m.agenda}</div>}</td>
          <td>{m.created_by_name}</td><td>{m.participants.map((p) => p.full_name).join(', ')}</td>
          <td style={{ textAlign: 'right' }}><div className="row" style={{ justifyContent: 'flex-end' }}>
            {mt.current?.meeting_id === m.id && <span className="badge green" role="status">In meeting {hms(mt.seconds)}</span>}
            {mt.current?.meeting_id === m.id && <button className="btn small" onClick={() => leave(m)}>Leave meeting</button>}
            {!history && m.link && mt.current?.meeting_id !== m.id && <a className="btn small primary" href={m.link} target="_blank" rel="noopener noreferrer" onClick={() => joined(m)}>Join ↗</a>}
            {!history && m.can_cancel && <button className="btn small danger" onClick={() => cancel(m)}>Cancel</button>}</div></td></tr>))}
      </tbody></table></div>));
  return (
    <>
      <PageHead title="Meetings" sub="Meetings you organise or are invited to.">
        {people.length > 0 && <button className="btn primary" onClick={() => setForm(true)}>Schedule a meeting</button>}
      </PageHead>
      <ErrorBox error={error} />
      <div className="card" data-testid="my-meeting-time">
        <div className="row spread"><h2>Meeting timer</h2>
          <span className="row inline" style={{ gap: 10 }}>
            <span title="Meeting time counted today">Today: <b>{dur(mt.todaySeconds)}</b></span>
            <span title="Monday to Sunday">This week: <b>{dur(mt.weekSeconds)}</b></span>
            <span title="The 1st to the end of this month">This month: <b>{dur(mt.monthSeconds)}</b></span>
          </span></div>
        <p className="muted" style={{ margin: 0 }}>Separate from the work timer. It starts when you join a scheduled meeting and stops when you leave.
          With the WORKCODE browser extension this happens by itself when the meeting tab opens and closes. Without it, press <b>Join</b> here and <b>Leave meeting</b> when you are done.</p>
      </div>
      <div className="card"><h2>Upcoming</h2>{rows && <Table list={upcoming} />}</div>
      <div className="card"><h2>History</h2>{rows && <Table list={past} history />}</div>
      <ExtensionCard />
      {form && <MeetingForm people={people} onClose={() => setForm(false)} onDone={() => { setForm(false); load(); }} />}
    </>
  );
}

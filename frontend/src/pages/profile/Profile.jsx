import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import api, { errMsg, setToken } from '../../services/api';
import { Badge, ErrorBox, Field, PageHead } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { ROLE_LABEL, dur, fmtDate, fmtDateTime } from '../../utils/format';

export function ChangePassword() {
  const [f, setF] = useState({ current_password: '', new_password: '' });
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault(); setMsg(''); setError('');
    try {
      const { data } = await api.post('/auth/change-password', f);
      if (data.access_token) setToken(data.access_token);   // old tokens stop working after a password change
      setMsg('Password changed. Other browsers signed in with the old password are signed out.'); setF({ current_password: '', new_password: '' }); }
    catch (err) { setError(errMsg(err)); }
  };
  return (
    <form className="card" onSubmit={submit}><h2>Change password</h2>
      <ErrorBox error={error} />{msg && <div className="notice">{msg}</div>}
      <Field label="Current password"><input type="password" required value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></Field>
      <Field label="New password (min 8 characters)"><input type="password" required minLength={8} value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
      <button className="btn primary">Change password</button>
    </form>
  );
}

/** /profile shows the signed-in user; /people/:userId shows someone else (admin, or a team's developer). */
export default function Profile() {
  const { user: me } = useAuth();
  const { userId } = useParams();
  const id = userId ? Number(userId) : me.id;
  const self = id === me.id;
  const [u, setU] = useState(null);
  const [att, setAtt] = useState([]);
  const [hist, setHist] = useState([]);
  const [acts, setActs] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    setU(null);
    api.get(`/users/${id}`).then((r) => setU(r.data)).catch((e) => setError(errMsg(e)));
    api.get('/attendance', { params: { user_id: id, days: 30 } }).then((r) => setAtt(r.data)).catch(() => {});
    api.get(`/users/${id}/activity`, { params: { limit: 30 } }).then((r) => setActs(r.data)).catch(() => {});
    if (self || me.role === 'admin') api.get(`/users/${id}/history`).then((r) => setHist(r.data)).catch(() => {});
    if (!self) api.get('/tasks', { params: { assigned_to: id } }).then((r) => setTasks(r.data)).catch(() => {});
  }, [id, self, me.role]);

  if (!u) return <><ErrorBox error={error} /><div className="empty">Loading…</div></>;
  return (
    <>
      <PageHead title={u.full_name} sub={`${ROLE_LABEL[u.role]}${u.employee_code ? ` · ${u.employee_code}` : ''}`}>
        <Badge value={u.is_active ? 'active' : 'inactive'} />
      </PageHead>
      <div className="grid g2">
        <div className="card"><h2>Details</h2>
          <dl className="kv">
            <dt>Email</dt><dd>{u.email}</dd><dt>Department</dt><dd>{u.department || '—'}</dd>
            <dt>Teams</dt><dd>{u.teams.map((t) => t.name).join(', ') || '—'}</dd>
            <dt>Joined</dt><dd>{fmtDate(u.joining_date)}</dd><dt>Period ends</dt><dd>{fmtDate(u.contract_end)}</dd>
            {'phone' in u && <><dt>Phone</dt><dd>{u.phone || '—'}</dd><dt>Salary / stipend</dt><dd>{u.compensation ?? '—'}</dd>
              <dt>Last login</dt><dd>{fmtDateTime(u.last_login_at)}</dd></>}
          </dl>
        </div>
        {self ? <ChangePassword /> : (
          <div className="card"><h2>Tasks ({tasks.length})</h2>
            {tasks.length === 0 ? <p className="muted">No tasks.</p> : (
              <table><tbody>{tasks.slice(0, 12).map((t) => (
                <tr key={t.id}><td>{t.code} · {t.title}</td><td style={{ textAlign: 'right' }}><Badge value={t.status} /></td></tr>))}</tbody></table>)}
          </div>)}
        <div className="card"><h2>Attendance (30 days)</h2>
          {att.length === 0 ? <p className="muted">No working time recorded.</p> : (
            <table><thead><tr><th>Date</th><th>Active</th><th>8 h</th><th>Continue</th><th>Away / idle</th><th>Paused</th><th>First login</th></tr></thead>
              <tbody>{att.map((a) => (
                <tr key={a.day}><td>{fmtDate(a.day)}</td><td>{dur(a.active_seconds)}</td>
                  <td>{a.regular_completed_at ? <span className="badge green" title="regular schedule completed">done</span> : '—'}</td>
                  <td>{dur(a.extra_seconds || 0)}</td><td>{dur(a.away_seconds)}</td><td>{dur(a.paused_seconds)}</td>
                  <td>{fmtDateTime(a.first_login_at)}</td></tr>))}</tbody></table>)}
        </div>
        <div>
          {hist.length > 0 && <div className="card"><h2>Employment history</h2>
            {hist.map((h) => (<div key={h.id} style={{ marginBottom: 6 }}><b>{fmtDate(h.effective_date || h.created_at)}</b> · {h.event}
              {h.event === 'converted' && ` ${ROLE_LABEL[h.from_role]} → ${ROLE_LABEL[h.to_role]}`}{h.reason && <span className="muted"> — {h.reason}</span>}</div>))}</div>}
          <div className="card"><h2>Recent activity</h2>
            {acts.length === 0 ? <p className="muted">No activity.</p> : acts.map((a) => (
              <div key={a.id} className="row spread"><span>{a.kind}</span><span className="muted">{fmtDateTime(a.created_at)}</span></div>))}
          </div>
        </div>
      </div>
    </>
  );
}

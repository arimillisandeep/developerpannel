import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ErrorBox, Field, Modal, PageHead, PromptModal } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { ROLE_LABEL, fmtDate } from '../../utils/format';

const EMPTY = { full_name: '', email: '', password: '', role: 'intern', phone: '', department_id: '', joining_date: '', contract_end: '', compensation: '', responsibilities: '' };
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== '' && v != null));
const NEXT = { intern: ['offroll', 'onroll'], offroll: ['onroll'], onroll: [] };

function PersonForm({ person, departments, onDone, onClose }) {
  const editing = !!person;
  const [f, setF] = useState(editing ? { ...EMPTY, ...clean(person), password: '' } : EMPTY);
  const [error, setError] = useState('');
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const isEmployee = ['onroll', 'offroll', 'intern'].includes(f.role);
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (editing) {
        const body = clean({ full_name: f.full_name, email: f.email, phone: f.phone, joining_date: f.joining_date,
          contract_end: f.contract_end, compensation: f.compensation, responsibilities: f.responsibilities,
          department_id: f.department_id, new_password: f.password });
        await api.patch(`/users/${person.id}`, body);
      } else {
        await api.post('/users', clean(f));
      }
      onDone();
    } catch (err) { setError(errMsg(err)); }
  };
  return (
    <Modal title={editing ? `Edit ${person.full_name}` : 'Add person'} onClose={onClose}>
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        <div className="grid g2">
          <Field label="Full name"><input required value={f.full_name} onChange={set('full_name')} /></Field>
          <Field label="Email"><input required type="email" value={f.email} onChange={set('email')} /></Field>
          <Field label={editing ? 'New password (leave empty to keep)' : 'Password (min 8 characters)'}>
            <input type="password" required={!editing} minLength={8} value={f.password} onChange={set('password')} autoComplete="new-password" /></Field>
          <Field label="Role"><select value={f.role} onChange={set('role')} disabled={editing}>
            {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Phone"><input value={f.phone} onChange={set('phone')} /></Field>
          {f.role !== 'admin' && <Field label="Joining date"><input type="date" value={f.joining_date} onChange={set('joining_date')} /></Field>}
          {isEmployee && <Field label="Department"><select value={f.department_id} onChange={set('department_id')}>
            <option value="">—</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>}
          {isEmployee && f.role !== 'onroll' && <Field label="Contract / training end (default: 6 months)">
            <input type="date" value={f.contract_end} onChange={set('contract_end')} /></Field>}
          {f.role !== 'admin' && <Field label="Salary / stipend (visible to admins and the person)">
            <input type="number" min="0" value={f.compensation} onChange={set('compensation')} /></Field>}
        </div>
        {f.role === 'developer' && <Field label="Responsibilities"><textarea value={f.responsibilities} onChange={set('responsibilities')} /></Field>}
        {editing && <p className="muted">To change the role, use “Convert” so the history is kept.</p>}
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary">{editing ? 'Save changes' : 'Create account'}</button></div>
      </form>
    </Modal>
  );
}

function ConvertForm({ person, onDone, onClose }) {
  const [to, setTo] = useState(NEXT[person.role][0]);
  const [reason, setReason] = useState('');
  const [early, setEarly] = useState(false);
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try { await api.post(`/users/${person.id}/convert`, { to_role: to, reason: reason || null, confirm_early: early }); onDone(); }
    catch (err) { setError(errMsg(err)); }
  };
  return (
    <Modal title={`Convert ${person.full_name}`} onClose={onClose}>
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        <p>Currently <b>{ROLE_LABEL[person.role]}</b>. Tasks, workspaces, submissions and attendance stay with this person.</p>
        <Field label="New role"><select value={to} onChange={(e) => setTo(e.target.value)}>
          {NEXT[person.role].map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></Field>
        <Field label="Reason"><textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <label className="row"><input type="checkbox" style={{ width: 'auto' }} checked={early} onChange={(e) => setEarly(e.target.checked)} />
          Convert even if the person joined less than 60 days ago</label>
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary">Convert</button></div>
      </form>
    </Modal>
  );
}

export default function People() {
  const { user: me } = useAuth();
  const [rows, setRows] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [head, setHead] = useState(null);
  const [filter, setFilter] = useState({ q: '', role: '', active: '' });
  const [modal, setModal] = useState(null); // {type, person}
  const [error, setError] = useState('');

  const load = useCallback(() => {
    const params = clean(filter);
    api.get('/users', { params }).then((r) => setRows(r.data)).catch((e) => setError(errMsg(e)));
    api.get('/users/intern-headcount').then((r) => setHead(r.data)).catch(() => {});
  }, [filter]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get('/departments').then((r) => setDepartments(r.data)).catch(() => {}); }, []);

  const done = () => { setModal(null); setError(''); load(); };
  const act = async (fn) => { try { await fn(); done(); } catch (e) { setError(errMsg(e)); setModal(null); } };

  return (
    <>
      <PageHead title="People" sub={head ? `Interns: ${head.filled} of ${head.target} seats filled · ${head.vacant} vacant` : ''}>
        <button className="btn" onClick={() => setModal({ type: 'seats' })}>Intern seats</button>
        <button className="btn primary" onClick={() => setModal({ type: 'form' })}>Add person</button>
      </PageHead>
      <ErrorBox error={error} />
      <div className="card">
        <div className="row inline" style={{ marginBottom: 12 }}>
          <input placeholder="Search name or email" value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} aria-label="Search" />
          <select value={filter.role} onChange={(e) => setFilter({ ...filter, role: e.target.value })} aria-label="Role">
            <option value="">All roles</option>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <select value={filter.active} onChange={(e) => setFilter({ ...filter, active: e.target.value })} aria-label="Status">
            <option value="">Active and inactive</option><option value="true">Active</option><option value="false">Inactive</option></select>
        </div>
        <div className="table-wrap">
          {rows && rows.length === 0 && <div className="empty">No people match.</div>}
          {rows && rows.length > 0 && (
            <table><thead><tr><th>ID</th><th>Name</th><th>Role</th><th>Department</th><th>Joined</th><th>Period ends</th><th>Status</th><th /></tr></thead>
              <tbody>{rows.map((u) => (
                <tr key={u.id}>
                  <td>{u.employee_code || '—'}</td>
                  <td><Link to={`/people/${u.id}`}>{u.full_name}</Link><div className="muted">{u.email}</div></td>
                  <td>{ROLE_LABEL[u.role]}</td><td>{u.department || '—'}</td><td>{fmtDate(u.joining_date)}</td><td>{fmtDate(u.contract_end)}</td>
                  <td><Badge value={u.is_active ? 'active' : u.employment_status === 'active' ? 'inactive' : u.employment_status} /></td>
                  <td><div className="row" style={{ justifyContent: 'flex-end' }}>
                    <button className="btn small" onClick={() => setModal({ type: 'form', person: u })}>Edit</button>
                    {NEXT[u.role] && u.is_active && <button className="btn small" onClick={() => setModal({ type: 'convert', person: u })}>Convert</button>}
                    {u.id !== me.id && (u.is_active
                      ? <button className="btn small danger" onClick={() => setModal({ type: 'off', person: u })}>Deactivate</button>
                      : <button className="btn small" onClick={() => act(() => api.post(`/users/${u.id}/activate`))}>Activate</button>)}
                  </div></td>
                </tr>))}
              </tbody></table>)}
        </div>
      </div>
      {modal?.type === 'form' && <PersonForm person={modal.person} departments={departments} onDone={done} onClose={() => setModal(null)} />}
      {modal?.type === 'convert' && <ConvertForm person={modal.person} onDone={done} onClose={() => setModal(null)} />}
      {modal?.type === 'seats' && <PromptModal title="Intern seats" label="Target intern headcount" initial={String(head?.target ?? 10)}
        onClose={() => setModal(null)} onSubmit={(v) => act(() => api.put('/intern-vacancy', { target_headcount: Number(v) }))} />}
      {modal?.type === 'off' && (
        <Modal title={`Deactivate ${modal.person.full_name}`} onClose={() => setModal(null)}>
          <p>The person can no longer sign in. All tasks, submissions and attendance are kept.</p>
          <div className="modal-foot">
            <button className="btn" onClick={() => setModal(null)}>Cancel</button>
            {['inactive', 'left', 'completed'].map((s) => (
              <button key={s} className="btn danger" onClick={() => act(() => api.post(`/users/${modal.person.id}/deactivate`, { status: s }))}>
                Mark as {s}</button>))}
          </div>
        </Modal>)}
    </>
  );
}

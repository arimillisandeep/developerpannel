import { useCallback, useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, PageHead, PromptModal } from '../../components/ui';
import { ROLE_LABEL } from '../../utils/format';

export default function Teams() {
  const [teams, setTeams] = useState([]);
  const [people, setPeople] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [projects, setProjects] = useState([]);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    Promise.all([api.get('/teams'), api.get('/users', { params: { active: true } }), api.get('/departments'), api.get('/projects')])
      .then(([t, u, d, p]) => { setTeams(t.data); setPeople(u.data); setDepartments(d.data); setProjects(p.data); })
      .catch((e) => setError(errMsg(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = async (fn) => { try { await fn(); setError(''); setModal(null); load(); } catch (e) { setError(errMsg(e)); setModal(null); } };
  const developers = people.filter((p) => p.role === 'onroll');
  const employees = people.filter((p) => ['onroll', 'offroll', 'intern'].includes(p.role));
  const create = { team: ['New team', 'Team name', (v) => api.post('/teams', { name: v })],
    department: ['New department', 'Department name', (v) => api.post('/departments', { name: v })],
    project: ['New project', 'Project name', (v) => api.post('/projects', { name: v })] };

  return (
    <>
      <PageHead title="Teams & projects" sub="The On-Roll lead of a team reviews the work of its Off-Roll and Intern members.">
        <button className="btn primary" onClick={() => setModal('team')}>New team</button>
      </PageHead>
      <ErrorBox error={error} />
      {teams.length === 0 && <div className="card empty">No teams yet. Create a team, choose its On-Roll lead, then add members.</div>}
      <div className="grid g2">
        {teams.map((t) => {
          const free = employees.filter((e) => !t.members.some((m) => m.id === e.id));
          return (
            <div className="card" key={t.id}>
              <div className="row spread"><h2>{t.name}</h2>
                <select style={{ width: 'auto' }} aria-label="Team lead" value={t.lead_developer_id || ''}
                  onChange={(e) => act(() => api.patch(`/teams/${t.id}`, { lead_developer_id: e.target.value ? Number(e.target.value) : null }))}>
                  <option value="">No team lead</option>{developers.map((d) => <option key={d.id} value={d.id}>Lead: {d.full_name}</option>)}
                </select></div>
              {t.members.length === 0 && <p className="muted">No members.</p>}
              <table><tbody>{t.members.map((m) => (
                <tr key={m.id}><td>{m.full_name}</td><td>{ROLE_LABEL[m.role]}</td>
                  <td style={{ textAlign: 'right' }}><button className="btn small danger" onClick={() => act(() => api.delete(`/teams/${t.id}/members/${m.id}`))}>Remove</button></td></tr>))}
              </tbody></table>
              <select style={{ marginTop: 10 }} value="" aria-label="Add member" onChange={(e) => e.target.value && act(() => api.post(`/teams/${t.id}/members`, { user_id: Number(e.target.value) }))}>
                <option value="">Add member…</option>{free.map((e) => <option key={e.id} value={e.id}>{e.full_name} ({ROLE_LABEL[e.role]})</option>)}
              </select>
            </div>);
        })}
      </div>
      <div className="grid g2">
        <div className="card"><div className="row spread"><h2>Departments</h2><button className="btn small" onClick={() => setModal('department')}>Add</button></div>
          {departments.length === 0 ? <p className="muted">None yet.</p> : departments.map((d) => <div key={d.id}>{d.name}</div>)}</div>
        <div className="card"><div className="row spread"><h2>Projects</h2><button className="btn small" onClick={() => setModal('project')}>Add</button></div>
          {projects.length === 0 ? <p className="muted">None yet.</p> : projects.map((p) => <div key={p.id}>{p.name}</div>)}</div>
      </div>
      {modal && <PromptModal title={create[modal][0]} label={create[modal][1]} onClose={() => setModal(null)} onSubmit={(v) => act(() => create[modal][2](v))} />}
    </>
  );
}

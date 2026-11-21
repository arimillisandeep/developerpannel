import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ErrorBox, PageHead } from '../../components/ui';
import { fmtDate } from '../../utils/format';

/** "Coding workspace" menu entry: pick one of my tasks and open its workspace. */
export default function WorkspaceIndex() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  useEffect(() => { api.get('/tasks', { params: { scope: 'mine' } }).then((r) => setRows(r.data)).catch((e) => setError(errMsg(e))); }, []);
  const open = async (t) => {
    try { if (t.status === 'assigned') await api.post(`/tasks/${t.id}/accept`);
      if (['assigned', 'accepted'].includes(t.status)) await api.post(`/tasks/${t.id}/start`);
      navigate(`/workspace/${t.id}`); }
    catch (e) { setError(errMsg(e)); }
  };
  return (
    <>
      <PageHead title="Coding workspace" sub="Every task has its own workspace. Files are stored on the server." />
      <ErrorBox error={error} />
      <div className="card table-wrap">
        {rows && rows.length === 0 && <div className="empty">No tasks are assigned to you, so there is no workspace to open yet.</div>}
        {rows && rows.length > 0 && (
          <table><thead><tr><th>Task</th><th>Project</th><th>Deadline</th><th>Status</th><th /></tr></thead>
            <tbody>{rows.map((t) => (
              <tr key={t.id}><td>{t.code} · {t.title}</td><td>{t.project || '—'}</td><td>{fmtDate(t.deadline)}</td><td><Badge value={t.status} /></td>
                <td style={{ textAlign: 'right' }}><button className="btn small primary" onClick={() => open(t)}>
                  {t.status === 'assigned' ? 'Accept and start' : t.status === 'accepted' ? 'Start task' : 'Open workspace'}</button></td></tr>))}
            </tbody></table>)}
      </div>
    </>
  );
}

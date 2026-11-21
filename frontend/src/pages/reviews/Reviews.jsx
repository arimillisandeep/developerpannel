import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ErrorBox, PageHead } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useNotifications } from '../../context/NotificationContext';
import { ROLE_LABEL, fmtDateTime, label } from '../../utils/format';

/** [key, label, API view, client-side filter]. The API already limits every view to what the user may see. */
const TABS = {
  admin: [['queue', 'Pending final approval', 'queue'], ['with_onroll', 'With On-Roll reviewer', 'all', (s) => s.stage === 'onroll_review'],
    ['approved', 'Approved', 'all', (s) => s.status === 'approved'], ['rejected', 'Rejected / rework', 'all', (s) => ['rejected', 'changes_requested'].includes(s.status)],
    ['all', 'All versions', 'all'], ['reviewed', 'My review history', 'reviewed']],
  onroll: [['queue', 'Pending reviews', 'queue'], ['intern', 'Intern submissions', 'all', (s) => s.submitter_role === 'intern'],
    ['offroll', 'Off-Roll submissions', 'all', (s) => s.submitter_role === 'offroll'],
    ['approved', 'Approved', 'reviewed', (s) => s.my_decision === 'approved'], ['rejected', 'Rejected', 'reviewed', (s) => s.my_decision !== 'approved'],
    ['reviewed', 'Review history', 'reviewed'], ['mine', 'My own submissions', 'mine']],
  employee: [['mine', 'My submissions', 'mine']],
};

export default function Reviews() {
  const { user } = useAuth();
  const { version } = useNotifications();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const reviewer = user.role === 'admin' || user.role === 'onroll' || user.role === 'developer';
  const tabs = user.role === 'admin' ? TABS.admin : reviewer ? TABS.onroll : TABS.employee;
  const [tab, setTab] = useState(tabs.some(([k]) => k === params.get('tab')) ? params.get('tab') : tabs[0][0]);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const current = tabs.find(([k]) => k === tab) || tabs[0];
  useEffect(() => {
    setRows(null);
    api.get('/submissions', { params: { view: current[2] } }).then((r) => setRows(current[3] ? r.data.filter(current[3]) : r.data)).catch((e) => setError(errMsg(e)));
  }, [tab, version]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <PageHead title={user.role === 'admin' ? 'Final review' : reviewer ? 'Reviews' : 'My submissions'}
        sub={user.role === 'admin' ? 'Only your approval completes a task. Intern and Off-Roll work arrives here after an On-Roll reviewer approved it; On-Roll work arrives directly.'
          : reviewer ? 'First review of Intern and Off-Roll work. Your approval sends it to Admin for the final decision.'
            : 'Every version you submitted, with reviewer feedback.'} />
      <ErrorBox error={error} />
      <div className="card">
        {tabs.length > 1 && <div className="tabs" style={{ flexWrap: 'wrap' }}>{tabs.map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>}
        <div className="table-wrap">
          {rows && rows.length === 0 && <div className="empty">{tab === 'queue' ? 'Nothing is waiting for you.' : 'Nothing here yet.'}</div>}
          {rows && rows.length > 0 && (
            <table><thead><tr><th>Task</th><th>Submitted by</th><th>Version</th><th>Changes</th><th>Submitted</th><th>Status</th></tr></thead>
              <tbody>{rows.map((s) => (
                <tr key={s.id} className="click" onClick={() => navigate(`/reviews/${s.id}`)}>
                  <td>{s.task_code} · {s.task_title}</td><td>{s.submitted_by_name} <span className="muted">({ROLE_LABEL[s.submitter_role]})</span></td>
                  <td>v{s.version}</td><td className="muted">{s.file_count} files · +{s.changes.added.length} ~{s.changes.modified.length} −{s.changes.deleted.length}</td>
                  <td>{fmtDateTime(s.submitted_at)}</td>
                  <td><Badge value={s.status} />{s.my_decision && <div className="muted">you: {label(s.my_decision)}</div>}</td>
                </tr>))}</tbody></table>)}
        </div>
      </div>
    </>
  );
}

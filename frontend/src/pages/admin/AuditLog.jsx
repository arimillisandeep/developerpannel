import { useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, PageHead } from '../../components/ui';
import { fmtDateTime } from '../../utils/format';

const show = (v) => (v == null ? '—' : Object.entries(v).map(([k, x]) => `${k}: ${x}`).join(', '));

export default function AuditLog() {
  const [rows, setRows] = useState(null);
  const [action, setAction] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    api.get('/audit-logs', { params: action ? { action } : {} }).then((r) => setRows(r.data)).catch((e) => setError(errMsg(e)));
  }, [action]);
  return (
    <>
      <PageHead title="Audit log" sub="Every administrative and review action, with who, when, from where and what changed.">
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter by action">
          <option value="">All actions</option><option value="user.">People</option><option value="team.">Teams</option>
          <option value="task.">Tasks</option><option value="submission.">Submissions</option><option value="review.">Reviews</option>
        </select>
      </PageHead>
      <ErrorBox error={error} />
      <div className="card table-wrap">
        {rows && rows.length === 0 && <div className="empty">No entries.</div>}
        {rows && rows.length > 0 && (
          <table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Record</th><th>Previous</th><th>New</th><th>IP</th></tr></thead>
            <tbody>{rows.map((a) => (
              <tr key={a.id}><td>{fmtDateTime(a.created_at)}</td><td>{a.actor || '—'}</td><td>{a.action}</td>
                <td>{a.entity} #{a.record_id}</td><td>{show(a.previous_value)}</td><td>{show(a.new_value)}</td><td>{a.ip_address}</td></tr>))}
            </tbody></table>)}
      </div>
    </>
  );
}

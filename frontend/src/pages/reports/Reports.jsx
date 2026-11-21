import { useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, PageHead, Stat } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { ROLE_LABEL } from '../../utils/format';

const iso = (d) => d.toLocaleDateString('en-CA');

export default function Reports() {
  const { user } = useAuth();
  const wide = ['admin', 'onroll', 'developer'].includes(user.role);
  const [range, setRange] = useState({ start: iso(new Date(Date.now() - 29 * 86400000)), end: iso(new Date()) });
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.get('/reports/summary', { params: range }).then((r) => { setRows(r.data.rows); setError(''); }).catch((e) => setError(errMsg(e)));
  }, [range]);
  const preset = (days) => setRange({ start: iso(new Date(Date.now() - (days - 1) * 86400000)), end: iso(new Date()) });
  const download = async (format) => {
    try {
      const r = await api.get('/reports/summary', { params: { ...range, format }, responseType: 'blob' });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a'); a.href = url; a.download = `workcode-report-${range.start}-to-${range.end}.${format}`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(errMsg(e)); }
  };
  const total = (k) => (rows || []).reduce((a, r) => a + r[k], 0);
  return (
    <>
      <PageHead title={wide ? 'Reports' : 'My reports'} sub="Attendance, working hours and task completion from the database.">
        <span className="row inline">
          <button className="btn small" onClick={() => preset(1)}>Today</button><button className="btn small" onClick={() => preset(7)}>7 days</button>
          <button className="btn small" onClick={() => preset(30)}>30 days</button>
          <input type="date" aria-label="From" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} />
          <input type="date" aria-label="To" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} />
          <button className="btn" onClick={() => download('csv')}>Export CSV</button>
          <button className="btn primary" onClick={() => download('xlsx')}>Export Excel</button>
        </span>
      </PageHead>
      <ErrorBox error={error} />
      {rows && (<>
        <div className="grid g4" style={{ marginBottom: 18 }}>
          <Stat ico="◷" title="Active hours" value={`${total('active_hours').toFixed(2)}h`}
            sub={`${total('away_hours').toFixed(2)}h away · ${total('extra_hours').toFixed(2)}h extra`} />
          <Stat ico="▦" title="Days present" value={total('days_present')} />
          <Stat ico="✓" title="Tasks completed" value={total('tasks_completed')} sub={`of ${total('tasks_assigned')} assigned (all time)`} />
          <Stat ico="⌥" title="Submissions" value={total('submissions')} sub={`${total('recordings')} recordings`} />
        </div>
        <div className="card table-wrap">
          {rows.length === 0 ? <div className="empty">No people in this report.</div> : (
            <table><thead><tr><th>ID</th><th>Name</th><th>Role</th><th>Days present</th><th>Active h</th><th>Extra h (Continue)</th><th>Total h</th><th>Away h</th><th>Avg h/day</th>
              <th>Tasks</th><th>Completed</th><th>Open</th><th>Rejected</th><th>Done %</th><th>Submissions</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.user_id}><td>{r.employee_code}</td><td>{r.full_name}</td><td>{ROLE_LABEL[r.role]}</td><td>{r.days_present}</td>
                  <td>{r.active_hours}</td><td>{r.extra_hours ?? 0}</td>
                  <td data-testid="total-hours">{r.total_hours ?? r.active_hours}</td>
                  <td>{r.away_hours}</td><td>{r.avg_hours_per_day}</td><td>{r.tasks_assigned}</td><td>{r.tasks_completed}</td>
                  <td>{r.tasks_open}</td><td>{r.tasks_rejected}</td><td>{r.completion_percent}%</td><td>{r.submissions}</td></tr>))}
              </tbody></table>)}
          <p className="muted" style={{ marginBottom: 0 }}>Hours, days, submissions and recordings are for the chosen dates. Task counts are all-time.
            <b>Active h</b> is the regular schedule, <b>Extra h</b> is the Continue schedule after the 8 hours, <b>Total h</b> is both added up.</p>
        </div>
      </>)}
    </>
  );
}

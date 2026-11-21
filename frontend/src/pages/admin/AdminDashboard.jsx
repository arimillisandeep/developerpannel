import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Distribution, ErrorBox, HoursChart, PageHead, Stat } from '../../components/ui';
import { useNotifications } from '../../context/NotificationContext';
import { MeetingTimeReport } from '../../components/MeetingTimer';
import { ExtraWorkToday } from '../../components/TimerAdmin';

export default function AdminDashboard() {
  const [d, setD] = useState(null);
  const [range, setRange] = useState({ start: '', end: '' });
  const [error, setError] = useState('');
  const { version } = useNotifications();

  useEffect(() => {
    const params = {};
    if (range.start) params.start = range.start;
    if (range.end) params.end = range.end;
    api.get('/dashboard/admin', { params }).then((r) => { setD(r.data); setError(''); }).catch((e) => setError(errMsg(e)));
  }, [range, version]);

  if (!d) return <><ErrorBox error={error} /><div className="empty">Loading…</div></>;
  const { people: p, tasks: t, hours: h, live } = d;
  return (
    <>
      <PageHead eyebrow="Administration" title="Platform overview" sub="Live state of every employee, task and coding session.">
        <span className="row inline">
          <input type="date" aria-label="From" value={range.start || d.range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} />
          <span className="muted">to</span>
          <input type="date" aria-label="To" value={range.end || d.range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} />
        </span>
      </PageHead>
      <ErrorBox error={error} />
      <h3>People</h3>
      <div className="grid g6" style={{ marginBottom: 16 }}>
        <Stat title="Employees" value={p.total_employees} sub={`${p.active} active · ${p.inactive} inactive `} />
        <Stat title="On-Roll" value={p.onroll} />
        <Stat title="Off-Roll" value={p.offroll} />
        <Stat title="Interns" value={p.interns} sub={`${d.intern_headcount.vacant} of ${d.intern_headcount.target} seats vacant`} />
        <Stat title="Working now" value={live.working} sub={`${live.idle} idle or paused`} />
      </div>
      <h3>Tasks</h3>
      <div className="grid g6" style={{ marginBottom: 16 }}>
        <Stat title="Total assigned" value={t.total} />
        <Stat title="Pending" value={t.pending} />
        <Stat title="Under review" value={t.under_review} sub={`${d.review_queue.onroll} with On-Roll · ${d.review_queue.admin} with Admin`} />
        <Stat title="Completed" value={t.completed} />
        <Stat title="Rejected" value={t.rejected} />
        <Stat title="Projects" value={d.projects} sub={`${d.teams} teams`} />
      </div>
      <div className="grid g3">
        <div className="card" style={{ gridColumn: 'span 2' }}>
          <div className="row spread"><h2>Working hours per day</h2>
            <span className="muted">{h.range_total} h in range · {h.today} h today</span></div>
          <HoursChart data={h.daily} />
        </div>
        <div className="card"><h2>Task status</h2><Distribution rows={Object.entries(t.by_status)} /></div>
      </div>
      <ExtraWorkToday />
      <MeetingTimeReport />
      <div className="card">
        <div className="row spread"><span>Active screen recordings: <b>{d.active_recordings}</b>
          <span className="muted"> (workspace recordings run with the employee's consent)</span></span>
          <span className="row"><Link className="btn" to="/reviews">Final reviews ({d.review_queue.admin})</Link>
            <Link className="btn" to="/recordings">Recordings</Link>
            <Link className="btn" to="/monitoring">Monitoring</Link></span></div>
      </div>
    </>
  );
}

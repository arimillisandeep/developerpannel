import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ErrorBox, HoursChart, Stat } from '../../components/ui';
import WorkTime from '../../components/WorkTime';
import { useAuth } from '../../context/AuthContext';
import { useNotifications } from '../../context/NotificationContext';
import { fmtDate, fmtDateTime } from '../../utils/format';

/** Dashboard for On-Roll, Off-Roll and Intern. What differs per role:
 *  On-Roll sees employment + "assigned by me"; Off-Roll and Intern see when their period ends. */
const EYEBROW = { onroll: 'Developer · On-Roll', offroll: 'Developer · Off-Roll', intern: 'Intern' };
const OPEN = ['assigned', 'accepted', 'in_progress', 'rework_required', 'onroll_rejected', 'admin_rejected'];

export default function EmployeeDashboard() {
  const { user } = useAuth();
  const { version } = useNotifications();
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.get('/dashboard/me').then((r) => setD(r.data)).catch((e) => setError(errMsg(e))); }, [version]);
  if (!d) return <><ErrorBox error={error} /><div className="empty">Loading…</div></>;
  const t = d.tasks;
  const next = d.recent_tasks.find((x) => OPEN.includes(x.status));
  const open = t.pending;
  return (
    <>
      <WorkTime />
      <div className="hello">
        <div><div className="eyebrow">{EYEBROW[user.role]}</div><h1>Hi {user.full_name.split(' ')[0]} 👋</h1>
          <p>{user.employee_code} · joined {fmtDate(user.joining_date)}</p></div>
        <div className="row"><Link className="btn big" to="/tasks">My tasks</Link>
          <Link className="btn big primary" to={next ? `/workspace/${next.id}` : '/workspace'}>Open workspace</Link></div>
      </div>
      <div className="grid g4" style={{ marginBottom: 18 }}>
        <Stat ico="☑" title="Open tasks" value={open} sub={`${(t.rework || 0) + (t.rejected || 0)} need rework · ${t.under_review} under review`} />
        <Stat ico="✓" title="Completed" value={t.completed} sub={`${d.overdue} overdue`} />
        <Stat ico="◷" title="Hours (30d)" value={`${d.hours.month}h`} sub={`avg ${(d.hours.month / 30).toFixed(2)}h/day`} />
        {user.role === 'onroll'
          ? <Stat ico="◆" title="Employment" value="On-Roll" sub={`${d.assigned_by_me} tasks assigned by me · ${d.active_projects} active projects`} />
          : d.training_period
            ? <Stat ico="◆" title="Period ends in" value={`${d.training_period.days_left}d`} sub={`${fmtDate(d.training_period.end)} · ${d.training_period.progress_percent}% done`} />
            : <Stat ico="◆" title="Period ends in" value="—" sub="no end date set" />}
      </div>
      <div className="grid g2">
        <div className="card"><div className="row spread" style={{ marginBottom: 8 }}><h2 style={{ margin: 0 }}>My tasks</h2><Link className="btn small" to="/tasks">View all</Link></div>
          {d.recent_tasks.length === 0 ? <div className="empty">No tasks assigned yet.</div> : (
            <table><tbody>{d.recent_tasks.map((x) => (
              <tr key={x.id}><td><Link to={`/tasks/${x.id}`}>{x.code} · {x.title}</Link><div className="muted">due {fmtDate(x.deadline)}</div></td>
                <td style={{ textAlign: 'right' }}><Badge value={x.status} /></td></tr>))}</tbody></table>)}
        </div>
        <div className="card"><div className="row spread"><h2>Attendance</h2><span className="badge">last 14 days</span></div>
          <HoursChart data={d.hours.daily} /><p className="muted" style={{ marginBottom: 0 }}>Active hours per day · {d.hours.week} h in the last 7 days</p></div>
        <div className="card"><div className="row spread" style={{ marginBottom: 8 }}><h2 style={{ margin: 0 }}>Recent submissions</h2><Link className="btn small" to="/reviews">View all</Link></div>
          {d.recent_submissions.length === 0 ? <div className="empty">Nothing submitted yet.</div> : (
            <table><tbody>{d.recent_submissions.map((s) => (
              <tr key={s.id}><td><Link to={`/reviews/${s.id}`}>Submission #{s.id} · v{s.version_no}</Link><div className="muted">{fmtDateTime(s.submitted_at)}</div></td>
                <td style={{ textAlign: 'right' }}><Badge value={s.status} /></td></tr>))}</tbody></table>)}
        </div>
      </div>
    </>
  );
}

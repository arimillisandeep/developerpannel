import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ErrorBox, PageHead } from '../../components/ui';
import { AllowedSites, ExtensionCard, TimerReport } from '../../components/TimerAdmin';
import { ROLE_LABEL, dur, fmtDateTime } from '../../utils/format';

/** Live sessions. Also used by developers for their own team (the API filters by role). */
export function LiveSessions({ title = 'Live sessions' }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const load = () => api.get('/sessions/live').then((r) => { setRows(r.data); setError(''); }).catch((e) => setError(errMsg(e)));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="card">
      <div className="row spread"><h2>{title}</h2><span className="muted">refreshes every 15 s</span></div>
      <ErrorBox error={error} />
      {rows && rows.length === 0 && <div className="empty">Nobody has a running session right now.</div>}
      {rows && rows.length > 0 && (
        <div className="table-wrap"><table>
          <thead><tr><th>Person</th><th>Role</th><th>State</th><th>Session started</th><th>Active</th><th>Away</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.user_id}><td><Link to={`/people/${r.user_id}`}>{r.full_name}</Link></td><td>{ROLE_LABEL[r.role]}</td>
              <td><Badge value={r.state} /></td><td>{fmtDateTime(r.started_at)}</td><td>{dur(r.active_seconds)}</td><td>{dur(r.away_seconds)}</td></tr>))}
          </tbody></table></div>)}
    </div>
  );
}

export default function Monitoring() {
  return (<><PageHead title="Monitoring" sub="Who is working right now. Open a person to see attendance, tasks and login history." />
    <LiveSessions /><TimerReport /><AllowedSites canEdit /><ExtensionCard /></>);
}

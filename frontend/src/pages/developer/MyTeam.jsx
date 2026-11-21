import { TimerReport } from '../../components/TimerAdmin';
import { MeetingTimeReport } from '../../components/MeetingTimer';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ErrorBox, PageHead } from '../../components/ui';
import { LiveSessions } from '../admin/Monitoring';
import { ROLE_LABEL } from '../../utils/format';

export default function MyTeam() {
  const [teams, setTeams] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.get('/teams').then((r) => setTeams(r.data)).catch((e) => setError(errMsg(e))); }, []);
  return (
    <>
      <PageHead title="My team" sub="People in the teams you lead. Open a person to see tasks, attendance and activity." />
      <ErrorBox error={error} />
      {teams && teams.length === 0 && <div className="card empty">You do not lead a team yet.</div>}
      {teams && teams.map((t) => (
        <div className="card" key={t.id}><h2>{t.name}</h2>
          {t.members.length === 0 ? <p className="muted">No members.</p> : (
            <table><thead><tr><th>Name</th><th>Role</th><th>Status</th></tr></thead><tbody>{t.members.map((m) => (
              <tr key={m.id}><td><Link to={`/people/${m.id}`}>{m.full_name}</Link></td><td>{ROLE_LABEL[m.role]}</td>
                <td><Badge value={m.is_active ? 'active' : 'inactive'} /></td></tr>))}</tbody></table>)}
        </div>))}
      <LiveSessions title="Team members working now" />
      <TimerReport title="Team timer report" />
      <MeetingTimeReport title="Team work time and meeting time" />
    </>
  );
}

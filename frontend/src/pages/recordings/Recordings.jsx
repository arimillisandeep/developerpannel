import { useCallback, useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, Modal, PageHead } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useRecording } from '../../context/RecordingContext';
import { dur, fmtDateTime } from '../../utils/format';

const TONE = { completed: 'green', recording: 'blue', interrupted: 'amber', failed: 'red' };
const mb = (b) => `${(b / 1048576).toFixed(1)} MB`;

function Player({ rec, onClose }) {
  const [url, setUrl] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let made;
    api.get(`/recordings/${rec.id}/file`, { responseType: 'blob' })
      .then((r) => { made = URL.createObjectURL(r.data); setUrl(made); })
      .catch(() => setError('The video could not be loaded.'));
    return () => { if (made) URL.revokeObjectURL(made); };
  }, [rec.id]);
  return (
    <Modal title={`${rec.user} · ${fmtDateTime(rec.started_at)}`} onClose={onClose} wide>
      <ErrorBox error={error} />
      {!url && !error && <div className="empty">Loading video…</div>}
      {url && <video src={url} controls controlsList="nodownload" disablePictureInPicture onContextMenu={(e) => e.preventDefault()}
        style={{ width: '100%', borderRadius: 10, background: '#000' }} />}
    </Modal>
  );
}

export default function Recordings() {
  const { user } = useAuth();
  const recording = useRecording();
  const [rows, setRows] = useState(null);
  const [day, setDay] = useState('');
  const [person, setPerson] = useState('');
  const [play, setPlay] = useState(null);
  const [error, setError] = useState('');
  const wide = ['admin', 'onroll', 'developer'].includes(user.role);
  const load = useCallback(() => {
    const params = {}; if (day) params.day = day;
    api.get('/recordings', { params }).then((r) => setRows(r.data)).catch((e) => setError(errMsg(e)));
  }, [day]);
  useEffect(() => { load(); }, [load, recording.version, recording.status]);
  const people = [...new Map((rows || []).map((r) => [r.user_id, r.user])).entries()];
  const shown = (rows || []).filter((r) => !person || String(r.user_id) === person);
  return (
    <>
      <PageHead title={wide ? 'Recordings' : 'My recordings'}
        sub={wide ? 'Screen recordings you are allowed to watch. Every time you open someone else’s recording it is written to the audit log.'
          : 'Your screen recordings. Opening a coding workspace starts a recording automatically (once you consented); the Record button at the top starts one anywhere else.'}>
        <span className="row inline">
          {wide && <select value={person} onChange={(e) => setPerson(e.target.value)} aria-label="Person"><option value="">Everyone</option>
            {people.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>}
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} aria-label="Date" />
          {day && <button className="btn" onClick={() => setDay('')}>All dates</button>}
        </span>
      </PageHead>
      <ErrorBox error={error} />
      {!recording.supported && <div className="notice">This browser cannot record the screen. Use a current desktop version of Chrome or Edge.</div>}
      <div className="card table-wrap">
        {rows && shown.length === 0 && <div className="empty">No recordings.</div>}
        {rows && shown.length > 0 && (
          <table><thead><tr>{wide && <th>Person</th>}<th>Started</th><th>Length</th><th>Size</th><th>Task</th><th>Status</th><th /></tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.id}>{wide && <td>{r.user}</td>}<td>{fmtDateTime(r.started_at)}</td><td>{dur(r.duration_seconds)}</td><td>{mb(r.size_bytes)}</td>
                <td>{r.task || '—'}</td><td><span className={`badge ${TONE[r.status] || ''}`}>{r.status}</span></td>
                <td style={{ textAlign: 'right' }}>{r.size_bytes > 0 && r.status !== 'recording' &&
                  <button className="btn small primary" onClick={() => setPlay(r)}>Play</button>}</td></tr>))}
            </tbody></table>)}
      </div>
      {play && <Player rec={play} onClose={() => setPlay(null)} />}
      <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Recordings and their upload status live on the company server, private to the people listed above.
        Finished videos are deleted automatically after {recording.retentionDays} days. The Recording Paused state appears while the browser's pause button is used.</p>
    </>
  );
}

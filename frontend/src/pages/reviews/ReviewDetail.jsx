import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ConfirmModal, ErrorBox, Field, PageHead } from '../../components/ui';
import DiffView from '../../components/DiffView';
import { useAuth } from '../../context/AuthContext';
import { ROLE_LABEL, fmtDateTime, label } from '../../utils/format';
import { downloadFile } from '../../utils/download';

const STAGE = { onroll_review: 'On-Roll review', admin_review: 'Admin final review', closed: 'Closed' };
const CHANGE = { added: 'green', modified: 'amber' };

/** One submitted version: the frozen snapshot, what changed, run, compare, download, restore and the review decision. */
export default function ReviewDetail() {
  const { subId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [s, setS] = useState(null);
  const [file, setFile] = useState(0);
  const [tab, setTab] = useState('files');
  const [comment, setComment] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [against, setAgainst] = useState('');
  const [cmp, setCmp] = useState(null);
  const [out, setOut] = useState(null);
  const [running, setRunning] = useState(false);
  const [stdin, setStdin] = useState('');
  const [confirm, setConfirm] = useState(false);

  const load = useCallback(() => {
    api.get(`/submissions/${subId}`).then((r) => {
      setS(r.data); setError('');
      const older = r.data.versions.filter((v) => v.id < r.data.id);
      setAgainst(older.length ? String(older[older.length - 1].id) : '');
    }).catch((e) => setError(errMsg(e)));
  }, [subId]);
  useEffect(() => { setCmp(null); setOut(null); setFile(0); setTab('files'); load(); }, [load]);

  const decide = async (decision) => {
    try { setS((await api.post(`/submissions/${subId}/review`, { decision, comment: comment || null })).data); setComment(''); setError(''); }
    catch (e) { setError(errMsg(e)); }
  };
  const addNote = async (e) => {
    e.preventDefault();
    try { await api.post(`/submissions/${subId}/comments`, { body: note, file_path: s.files[file]?.path || null }); setNote(''); load(); }
    catch (err) { setError(errMsg(err)); }
  };
  const compare = async () => {
    const [a, b] = [Number(against), s.id].sort((x, y) => x - y);
    try { setCmp((await api.get(`/tasks/${s.task_id}/compare`, { params: { a, b } })).data); setError(''); }
    catch (e) { setError(errMsg(e)); }
  };
  const runFile = async () => {
    setRunning(true); setOut(null);
    try { setOut((await api.post(`/submissions/${subId}/run`, { path: s.files[file].path, stdin })).data); setError(''); }
    catch (e) { setOut({ status: 'error', stdout: '', stderr: errMsg(e) }); }
    finally { setRunning(false); }
  };
  const restore = async () => {
    setConfirm(false);
    try { await api.post(`/submissions/${subId}/restore`); setError(''); load(); }
    catch (e) { setError(errMsg(e)); }
  };

  if (!s) return <><PageHead title="Review" /><ErrorBox error={error} /></>;
  const current = s.files[file];
  const mark = (p) => (s.changes.added.includes(p) ? 'added' : s.changes.modified.includes(p) ? 'modified' : null);
  return (
    <>
      <PageHead title={`${s.task_code} · ${s.task_title}`} sub={`Version ${s.version} by ${s.submitted_by_name} (${ROLE_LABEL[s.submitter_role]}) · ${fmtDateTime(s.submitted_at)}`}>
        <Badge value={s.status} />
        <select style={{ width: 'auto' }} aria-label="Version" value={s.id} onChange={(e) => navigate(`/reviews/${e.target.value}`)}>
          {s.versions.map((v) => <option key={v.id} value={v.id}>v{v.version} · {label(v.status)}</option>)}</select>
        <button className="btn" onClick={() => downloadFile(`/submissions/${s.id}/download`, `${s.task_code}-v${s.version}.zip`).catch((e) => setError(errMsg(e)))}>Download version</button>
        {s.can_restore && <button className="btn" onClick={() => setConfirm(true)}>Restore to workspace</button>}
        <Link className="btn" to={`/tasks/${s.task_id}`}>Task</Link><Link className="btn" to="/reviews">Back</Link>
      </PageHead>
      <ErrorBox error={error} />
      <div className="grid g3">
        <div className="card" style={{ gridColumn: 'span 2', minWidth: 0 }}>
          <div className="tabs">{[['files', `Submitted files (${s.files.length})`], ['changes', 'Changes'], ['compare', 'Compare versions']].map(([k, l]) => (
            <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>))}</div>
          {tab === 'files' && (<>
            <div className="row" style={{ marginBottom: 10, flexWrap: 'wrap' }}>{s.files.map((f, i) => (
              <button key={f.path} className={`btn small ${i === file ? 'primary' : ''}`} onClick={() => { setFile(i); setOut(null); }}>
                {f.path}{mark(f.path) && <span className={`badge ${CHANGE[mark(f.path)]}`} style={{ marginLeft: 6 }}>{mark(f.path)}</span>}</button>))}</div>
            {current && <p className="muted" style={{ margin: '0 0 6px' }}>Last modified by {s.authors[current.path]?.name || s.submitted_by_name}
              {s.authors[current.path]?.at ? ` · ${fmtDateTime(s.authors[current.path].at)}` : ''}</p>}
            {current && <pre className="code">{current.content.split('\n').map((line, i) => <span className="l" key={i}>{line || ' '}</span>)}</pre>}
            {current && (
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn" disabled={running} onClick={runFile}>{running ? 'Running…' : `▶ Run ${current.path}`}</button>
                <input style={{ flex: 1 }} placeholder="Program input (optional)" aria-label="Program input" value={stdin} onChange={(e) => setStdin(e.target.value)} />
              </div>)}
            {out && <pre className="code" aria-label="Run output" style={{ marginTop: 8, maxHeight: 220 }}>{`[${out.status}${out.exit_code != null ? ` · exit ${out.exit_code}` : ''}]\n${out.stdout || ''}${out.stderr ? `\n${out.stderr}` : ''}`}</pre>}
            <p className="muted">This is the exact copy frozen at submission; later edits by the employee do not change it. Run uses the isolated Docker runner on the server.</p>
          </>)}
          {tab === 'changes' && (<>
            <p className="muted">Compared with the version before it.</p>
            {['added', 'modified', 'deleted'].map((k) => (
              <div key={k} style={{ marginBottom: 10 }}><b style={{ textTransform: 'capitalize' }}>{k} ({s.changes[k].length})</b>
                {s.changes[k].length === 0 ? <div className="muted">None</div> : s.changes[k].map((p) => <div key={p}>{p}</div>)}</div>))}
            {s.note && <><b>Submission note</b><div style={{ whiteSpace: 'pre-wrap' }}>{s.note}</div></>}
            {s.attachments.length > 0 && <><b>Attached files</b>{s.attachments.map((a) => (
              <div key={a.id}><button className="btn small" onClick={() => downloadFile(`/tasks/${s.task_id}/attachments/${a.id}`, a.filename).catch((e) => setError(errMsg(e)))}>{a.filename}</button> <span className="muted">{a.kind}</span></div>))}</>}
          </>)}
          {tab === 'compare' && (s.versions.length < 2 ? <div className="empty">This is the only version so far.</div> : (<>
            <div className="row" style={{ marginBottom: 10 }}>
              <span>v{s.version} compared with</span>
              <select style={{ width: 'auto' }} aria-label="Compare with" value={against} onChange={(e) => setAgainst(e.target.value)}>
                <option value="">Choose…</option>{s.versions.filter((v) => v.id !== s.id).map((v) => <option key={v.id} value={v.id}>v{v.version}</option>)}</select>
              <button className="btn" disabled={!against} onClick={compare}>Compare</button>
            </div>
            <DiffView data={cmp} />
          </>))}
        </div>
        <div style={{ minWidth: 0 }}>
          {(s.task_requirements || s.task_deliverables) && <div className="card"><h2>Requirements</h2><div style={{ whiteSpace: 'pre-wrap' }}>{s.task_requirements}</div>
            {s.task_deliverables && <><h2 style={{ marginTop: 12 }}>Expected deliverables</h2><div style={{ whiteSpace: 'pre-wrap' }}>{s.task_deliverables}</div></>}</div>}
          {s.can_review && (
            <div className="card"><h2>Your decision · {STAGE[s.stage]}</h2>
              <Field label="Comment (required to reject or ask for rework)"><textarea value={comment} onChange={(e) => setComment(e.target.value)} aria-label="Review comment" /></Field>
              <div className="row">
                <button className="btn primary" onClick={() => decide('approved')}>{s.stage === 'admin_review' ? 'Final approve' : 'Approve → send to Admin'}</button>
                <button className="btn" onClick={() => decide('changes_requested')}>Request rework</button>
                <button className="btn danger" onClick={() => decide('rejected')}>Reject</button>
              </div>
            </div>)}
          {!s.can_review && s.stage !== 'closed' && <div className="card muted">Waiting for: {STAGE[s.stage]}.</div>}
          <div className="card"><h2>Review history</h2>
            {s.reviews.length === 0 && <p className="muted">No review yet.</p>}
            {s.reviews.map((r) => (
              <div key={r.id} style={{ marginBottom: 10 }}><b>{r.reviewer}</b> · {STAGE[r.stage]} · <Badge value={r.decision} />
                {r.comment && <div style={{ whiteSpace: 'pre-wrap' }}>{r.comment}</div>}<div className="muted">{fmtDateTime(r.created_at)}</div></div>))}
          </div>
          <div className="card"><h2>Comments</h2>
            {s.comments.length === 0 && <p className="muted">No comments.</p>}
            {s.comments.map((c) => (
              <div key={c.id} style={{ marginBottom: 10 }}><b>{c.author}</b>{c.file_path && <span className="muted"> on {c.file_path}</span>}
                <div style={{ whiteSpace: 'pre-wrap' }}>{c.body}</div><div className="muted">{fmtDateTime(c.created_at)}</div></div>))}
            <form onSubmit={addNote}><textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder={`Comment on ${current?.path || 'this submission'}`} aria-label="Comment" />
              <button className="btn" style={{ marginTop: 8 }} disabled={!note.trim()}>Add comment</button></form>
          </div>
          {s.submitted_by === user.id && ['changes_requested', 'rejected'].includes(s.status) &&
            <Link className="btn primary" to={`/workspace/${s.task_id}`}>Open workspace to fix and resubmit</Link>}
        </div>
      </div>
      {confirm && <ConfirmModal title="Restore this version" confirmLabel="Restore" onClose={() => setConfirm(false)} onConfirm={restore}
        text={`Your workspace files are replaced by version ${s.version}. The current files stay in each file's saved versions, and no submitted version is changed.`} />}
    </>
  );
}

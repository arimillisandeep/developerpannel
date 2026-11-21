import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { Badge, ConfirmModal, ErrorBox, Field, Modal, PageHead } from '../../components/ui';
import DiffView from '../../components/DiffView';
import { useAuth } from '../../context/AuthContext';
import { useNotifications } from '../../context/NotificationContext';
import { ROLE_LABEL, STATUS_LABEL, TASK_GROUPS, TASK_STATUSES, dur, fmtDate, fmtDateTime, label } from '../../utils/format';
import { downloadFile } from '../../utils/download';

const EMPTY = { title: '', description: '', requirements: '', deliverables: '', assigned_to: '', reviewer_id: '', project_id: '', priority: 'medium', start_date: '', deadline: '', estimated_hours: '' };
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== '' && v != null));
const EDITABLE = ['accepted', 'in_progress', 'rework_required', 'onroll_rejected', 'admin_rejected'];
// "Open" on a reference file: the server decides the mode (editor / preview / download) per attachment.
const extOf = (name) => (String(name || '').includes('.') ? String(name).split('.').pop().toLowerCase() : '');

const IN_REVIEW = TASK_GROUPS.submitted;
const size = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/** Tabs of the task list, per role. Each tab is a real filter on GET /tasks. */
const TABS = {
  admin: [['all', 'All assignments', {}], ['pending', 'Pending approvals', { status: TASK_GROUPS.pending_approval }],
    ['onroll', 'With On-Roll reviewer', { status: TASK_GROUPS.onroll_review }], ['rework', 'Rework / rejected', { status: TASK_GROUPS.rework }],
    ['completed', 'Completed', { status: TASK_GROUPS.completed }], ['closed', 'Cancelled / archived', { status: TASK_GROUPS.closed }]],
  onroll: [['mine', 'My tasks', { scope: 'mine' }], ['assigned_by_me', 'Assigned by me', { scope: 'assigned_by_me' }],
    ['all', 'All I can see', {}], ['rework', 'My rework', { scope: 'mine', status: TASK_GROUPS.rework }],
    ['completed', 'Completed', { status: TASK_GROUPS.completed }]],
  employee: [['mine', 'My tasks', { scope: 'mine' }], ['in_progress', 'In progress', { scope: 'mine', status: TASK_GROUPS.in_progress }],
    ['submitted', 'Submitted', { scope: 'mine', status: TASK_GROUPS.submitted }], ['rework', 'Rework required', { scope: 'mine', status: TASK_GROUPS.rework }],
    ['completed', 'Completed', { scope: 'mine', status: TASK_GROUPS.completed }]],
};

function TaskForm({ task, assignable, reviewers, projects, onDone, onClose }) {
  const [f, setF] = useState(task ? { ...EMPTY, ...clean(task) } : EMPTY);
  const [people, setPeople] = useState([]);       // new task: one task is created per ticked person
  const [files, setFiles] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const tick = (id) => setPeople((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const chosen = task ? [Number(f.assigned_to)] : people;
  const needsReviewer = assignable.some((u) => chosen.includes(u.id) && u.role !== 'onroll');
  const submit = async (e) => {
    e.preventDefault();
    if (!task && people.length === 0) { setError('Choose at least one person.'); return; }
    const body = clean({ title: f.title, description: f.description, requirements: f.requirements, deliverables: f.deliverables,
      priority: f.priority, start_date: f.start_date, deadline: f.deadline, estimated_hours: f.estimated_hours,
      reviewer_id: f.reviewer_id && Number(f.reviewer_id), project_id: f.project_id && Number(f.project_id) });
    setBusy(true);
    try {
      let ids;
      if (task) {
        const edit = { ...body, reviewer_id: f.reviewer_id ? Number(f.reviewer_id) : null };
        if (Number(f.assigned_to) !== task.assigned_to) edit.assigned_to = Number(f.assigned_to);
        await api.patch(`/tasks/${task.id}`, edit); ids = [task.id];
      }
      else { const { data } = await api.post('/tasks', { ...body, assigned_to_ids: people }); ids = (data.created || [data]).map((t) => t.id); }
      for (const id of ids) for (const file of files) {
        const fd = new FormData(); fd.append('file', file);
        await api.post(`/tasks/${id}/attachments`, fd);
      }
      onDone();
    } catch (err) { setError(errMsg(err)); } finally { setBusy(false); }
  };
  return (
    <Modal title={task ? `Edit ${task.code}` : 'Assign a task'} onClose={onClose} wide>
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Title"><input required minLength={3} value={f.title} onChange={set('title')} aria-label="Title" /></Field>
        {task ? (
          <Field label="Assigned to (change to reassign)"><select required value={f.assigned_to} onChange={set('assigned_to')}>
            {!assignable.some((u) => u.id === task.assigned_to) && <option value={task.assigned_to}>{task.assigned_to_name}</option>}
            {assignable.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({ROLE_LABEL[u.role]})</option>)}</select></Field>
        ) : (
          <Field label={`Assign to (${people.length} selected — each person gets their own task and workspace)`}>
            <div className="checks" role="group" aria-label="Assign to">{assignable.map((u) => (
              <label key={u.id}><input type="checkbox" checked={people.includes(u.id)} onChange={() => tick(u.id)} />{u.full_name} ({ROLE_LABEL[u.role]})</label>))}</div>
          </Field>)}
        <div className="grid g2">
          <Field label="On-Roll reviewer (first review of Intern / Off-Roll work)"><select value={f.reviewer_id} onChange={set('reviewer_id')} aria-label="On-Roll reviewer">
            <option value="">{needsReviewer ? 'Automatic: team lead, else any On-Roll' : 'Not needed (On-Roll work goes to Admin)'}</option>
            {reviewers.filter((r) => !chosen.includes(r.id)).map((r) => <option key={r.id} value={r.id}>{r.full_name}</option>)}</select></Field>
          <Field label="Project"><select value={f.project_id} onChange={set('project_id')}>
            <option value="">No project</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Priority"><select value={f.priority} onChange={set('priority')}>
            {['low', 'medium', 'high', 'urgent'].map((p) => <option key={p}>{p}</option>)}</select></Field>
          <Field label="Estimated hours"><input type="number" min="0" step="0.5" value={f.estimated_hours} onChange={set('estimated_hours')} /></Field>
          <Field label="Start date"><input type="date" value={f.start_date} onChange={set('start_date')} /></Field>
          <Field label="Deadline"><input type="date" value={f.deadline} onChange={set('deadline')} /></Field>
        </div>
        <Field label="Description"><textarea value={f.description} onChange={set('description')} /></Field>
        <Field label="Requirements"><textarea value={f.requirements} onChange={set('requirements')} /></Field>
        <Field label="Expected deliverables"><textarea value={f.deliverables} onChange={set('deliverables')} aria-label="Expected deliverables" /></Field>
        <Field label="Reference files (max 10 MB each)"><input type="file" multiple aria-label="Reference files" onChange={(e) => setFiles([...e.target.files])} /></Field>
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy}>{busy ? 'Saving…' : task ? 'Save changes' : 'Assign task'}</button></div>
      </form>
    </Modal>
  );
}

/** A reason is required by the backend for cancel and reopen. */
function ReasonModal({ title, text, confirmLabel, onSubmit, onClose }) {
  const [v, setV] = useState('');
  return (
    <Modal title={title} onClose={onClose}>
      <p>{text}</p>
      <Field label="Reason"><textarea autoFocus value={v} onChange={(e) => setV(e.target.value)} aria-label="Reason" /></Field>
      <div className="modal-foot"><button className="btn" onClick={onClose}>Back</button>
        <button className="btn primary" disabled={v.trim().length < 3} onClick={() => onSubmit(v.trim())}>{confirmLabel}</button></div>
    </Modal>
  );
}

function History({ id }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get(`/tasks/${id}/history`).then((r) => setRows(r.data)).catch(() => setRows([])); }, [id]);
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <ul className="timeline" aria-label="Task history">{rows.map((h) => (
      <li key={h.id}><b>{label(h.action)}</b>{h.version && <span className="muted"> · v{h.version}</span>}
        {h.to_status && h.to_status !== h.from_status && <span className="muted"> · {label(h.from_status)} → {label(h.to_status)}</span>}
        <div className="muted">{h.user || 'System'}{h.user_role ? ` (${ROLE_LABEL[h.user_role] || h.user_role})` : ''} · {fmtDateTime(h.at)}</div>
        {h.comment && <div style={{ whiteSpace: 'pre-wrap' }}>{h.comment}</div>}</li>))}
    </ul>
  );
}

export function Versions({ id }) {
  const [rows, setRows] = useState(null);
  const [a, setA] = useState(''); const [b, setB] = useState('');
  const [cmp, setCmp] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.get(`/tasks/${id}/versions`).then((r) => {
      setRows(r.data);
      if (r.data.length > 1) { setA(String(r.data[1].id)); setB(String(r.data[0].id)); }   // newest first: previous vs latest
    }).catch((e) => { setRows([]); setError(errMsg(e)); });
  }, [id]);
  const compare = async () => {
    try { setCmp((await api.get(`/tasks/${id}/compare`, { params: { a: Math.min(Number(a), Number(b)), b: Math.max(Number(a), Number(b)) } })).data); setError(''); }
    catch (e) { setError(errMsg(e)); }
  };
  if (!rows) return <p className="muted">Loading…</p>;
  if (rows.length === 0) return <div className="empty">Nothing has been submitted yet. Every submission becomes a version here.</div>;
  return (
    <>
      <ErrorBox error={error} />
      <div className="table-wrap"><table><thead><tr><th>Version</th><th>Submitted</th><th>By</th><th>Changes</th><th>Result</th><th /></tr></thead>
        <tbody>{rows.map((v) => (
          <tr key={v.id}><td><b>v{v.version}</b></td><td>{fmtDateTime(v.submitted_at)}</td>
            <td>{v.submitted_by_name} <span className="muted">({ROLE_LABEL[v.submitter_role]})</span></td>
            <td>{v.file_count} files<div className="muted">+{v.changes.added.length} added · {v.changes.modified.length} modified · {v.changes.deleted.length} deleted</div>
              {v.note && <div className="muted">Note: {v.note}</div>}</td>
            <td><Badge value={v.status} />{v.reviews.map((r, i) => <div className="muted" key={i}>{r.reviewer}: {label(r.decision)}{r.comment ? ` — ${r.comment}` : ''}</div>)}</td>
            <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}><Link className="btn small" to={`/reviews/${v.id}`}>Open</Link>{' '}
              <button className="btn small" onClick={() => downloadFile(`/submissions/${v.id}/download`, `v${v.version}.zip`).catch((e) => setError(errMsg(e)))}>Download</button></td>
          </tr>))}</tbody></table></div>
      {rows.length > 1 && (
        <div className="row" style={{ margin: '12px 0' }}>
          <select style={{ width: 'auto' }} value={a} onChange={(e) => setA(e.target.value)} aria-label="Older version">{rows.map((v) => <option key={v.id} value={v.id}>v{v.version}</option>)}</select>
          <span className="muted">compared with</span>
          <select style={{ width: 'auto' }} value={b} onChange={(e) => setB(e.target.value)} aria-label="Newer version">{rows.map((v) => <option key={v.id} value={v.id}>v{v.version}</option>)}</select>
          <button className="btn" disabled={a === b} onClick={compare}>Compare versions</button>
        </div>)}
      <DiffView data={cmp} />
    </>
  );
}

function TaskDetail({ id, onClose, onEdit, onChanged }) {
  const { user } = useAuth();
  const [t, setT] = useState(null);
  const [tab, setTab] = useState('details');
  const [error, setError] = useState('');
  const [ask, setAsk] = useState(null);       // delete | archive | cancel | reopen
  const fileRef = useRef(null);
  const navigate = useNavigate();
  const load = useCallback(() => api.get(`/tasks/${id}`).then((r) => { setT(r.data); setError(''); }).catch((e) => setError(errMsg(e))), [id]);
  useEffect(() => { load(); }, [load]);
  const act = async (fn, close) => { try { await fn(); setAsk(null); onChanged(); if (close) onClose(); else await load(); } catch (e) { setError(errMsg(e)); setAsk(null); } };
  const open = () => act(async () => { if (t.status === 'accepted') await api.post(`/tasks/${id}/start`); navigate(`/workspace/${id}`); });
  const upload = (e) => {
    const file = e.target.files[0]; e.target.value = '';
    if (!file) return;
    const fd = new FormData(); fd.append('file', file);
    act(() => api.post(`/tasks/${id}/attachments`, fd));
  };
  const [preview, setPreview] = useState(null);      // {name, url, type} | {name, content} | {name, detail}
  const [opening, setOpening] = useState(0);
  const openAttachment = async (a) => {
    setOpening(a.id); setError('');
    try {
      const { data } = await api.post(`/tasks/${id}/attachments/${a.id}/open`);
      if (data.mode === 'editor') navigate(data.url);              // the workspace opens on that file
      else if (data.mode === 'preview') setPreview({ id: a.id, name: a.filename, url: data.url, type: data.content_type });
      else if (data.mode === 'read_only') setPreview({ id: a.id, name: a.filename, content: data.content, detail: data.detail });
      else setPreview({ id: a.id, name: a.filename, detail: data.detail });
    } catch (e) { setError(errMsg(e)); }
    finally { setOpening(0); }
  };
  const admin = user.role === 'admin';
  const inReview = t && IN_REVIEW.includes(t.status);
  const closed = t && ['completed', 'cancelled', 'archived'].includes(t.status);
  const canUpload = t && ((t.is_assignee && EDITABLE.includes(t.status)) || (t.can_manage && !t.is_assignee && !['cancelled', 'archived'].includes(t.status)));
  return (
    <Modal title={t ? `${t.code} · ${t.title}` : 'Task'} onClose={onClose} wide>
      <ErrorBox error={error} />
      {t && (<>
        <div className="tabs">{[['details', 'Details'], ['versions', 'Version history'], ['history', 'Task history']].map(([k, l]) => (
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>))}</div>
        {tab === 'details' && (<>
          <dl className="kv">
            <dt>Status</dt><dd><Badge value={t.status} /></dd>
            <dt>Assigned to</dt><dd>{t.assigned_to_name}</dd><dt>Assigned by</dt><dd>{t.assigned_by_name}</dd>
            <dt>On-Roll reviewer</dt><dd>{t.reviewer_name || 'Automatic (team lead / any On-Roll; On-Roll work goes straight to Admin)'}</dd>
            <dt>Project</dt><dd>{t.project || '—'}</dd><dt>Priority</dt><dd><Badge value={t.priority}>{t.priority}</Badge></dd>
            <dt>Start – deadline</dt><dd>{fmtDate(t.start_date)} – {fmtDate(t.deadline)}</dd>
            <dt>Estimated hours</dt><dd>{t.estimated_hours ?? '—'}</dd>
            <dt>Time on task</dt><dd>{dur(t.time.active_seconds)} active · {dur(t.time.paused_seconds)} paused · {dur(t.time.total_seconds)} total
              {t.time.review_seconds > 0 && ` · ${dur(t.time.review_seconds)} in review`}</dd>
            <dt>Started</dt><dd>{fmtDateTime(t.started_at)}</dd><dt>Submitted</dt><dd>{fmtDateTime(t.submitted_at)}</dd>
            <dt>Completed</dt><dd>{fmtDateTime(t.completed_at)}</dd>
            <dt>Description</dt><dd style={{ whiteSpace: 'pre-wrap' }}>{t.description || '—'}</dd>
            <dt>Requirements</dt><dd style={{ whiteSpace: 'pre-wrap' }}>{t.requirements || '—'}</dd>
            <dt>Deliverables</dt><dd style={{ whiteSpace: 'pre-wrap' }}>{t.deliverables || '—'}</dd>
            <dt>Files</dt><dd>
              {t.attachments.length === 0 && <span className="muted">No files attached.</span>}
              {t.attachments.map((a) => (
                <div key={a.id} className="row" style={{ marginBottom: 4 }}>
                  <button className="btn small" onClick={() => downloadFile(`/tasks/${id}/attachments/${a.id}`, a.filename).catch((e) => setError(errMsg(e)))}>{a.filename}</button>
                  {['editor', 'preview'].includes(a.open_mode) && (
                    <button className="btn small primary" disabled={opening === a.id}
                      title={a.open_mode === 'editor' ? 'Open a copy of this file in the coding workspace' : 'View this file here'}
                      onClick={() => openAttachment(a)}>
                      {opening === a.id ? 'Opening…' : 'Open'}
                    </button>)}
                  <span className="muted">{a.kind} · {size(a.size_bytes)} · {a.uploaded_by_name}</span>
                  {!a.submission_id && (a.uploaded_by === user.id || admin) && !closed && !inReview &&
                    <button className="btn small danger" aria-label={`Remove ${a.filename}`} onClick={() => act(() => api.delete(`/tasks/${id}/attachments/${a.id}`))}>✕</button>}
                </div>))}
              {canUpload && <><input ref={fileRef} type="file" hidden onChange={upload} aria-label="Upload file" />
                <button className="btn small" onClick={() => fileRef.current.click()}>{t.is_assignee ? 'Upload deliverable' : 'Upload reference file'}</button></>}
            </dd>
            {t.group && t.group.length > 1 && <><dt>Same assignment</dt><dd>{t.group.filter((g) => g.id !== t.id).map((g) => (
              <Link key={g.id} to={`/tasks/${g.id}`} className="btn small" style={{ marginRight: 6 }}>{g.code} · {label(g.status)}</Link>))}</dd></>}
          </dl>
          {t.is_assignee && t.status === 'assigned' && <div className="notice">Accept this task to open its workspace and start the work.</div>}
          {t.is_assignee && inReview && <div className="notice">Submitted. The project is locked until the reviewer decides.</div>}
        </>)}
        {tab === 'versions' && <Versions id={id} />}
        {tab === 'history' && <History id={id} />}
        <div className="modal-foot">
          {t.can_manage && <button className="btn danger" disabled={inReview} title={inReview ? 'Not while it is under review' : ''} onClick={() => setAsk('delete')}>Delete</button>}
          {t.can_manage && ['completed', 'cancelled'].includes(t.status) && <button className="btn" onClick={() => setAsk('archive')}>Archive</button>}
          {t.can_manage && !closed && (!inReview || admin) && <button className="btn" onClick={() => setAsk('cancel')}>Cancel task</button>}
          {admin && t.status === 'completed' && <button className="btn" onClick={() => setAsk('reopen')}>Reopen for a new version</button>}
          {t.can_manage && !closed && !inReview && <button className="btn" onClick={() => onEdit(t)}>Edit / reassign</button>}
          {t.is_assignee && t.status === 'assigned' && <button className="btn primary" onClick={() => act(() => api.post(`/tasks/${id}/accept`))}>Accept task</button>}
          {t.is_assignee && t.status !== 'assigned' && t.status !== 'cancelled' &&
            <button className="btn primary" onClick={open}>{t.status === 'accepted' ? 'Start task' : EDITABLE.includes(t.status) ? 'Open workspace' : 'View workspace'}</button>}
          {!t.is_assignee && t.started_at && <Link className="btn" to={`/workspace/${id}`}>View workspace (read-only)</Link>}
        </div>
      </>)}
      {preview && (
        <Modal title={`${preview.name} · reference file`} onClose={() => setPreview(null)} wide>
          {preview.url && extOf(preview.name) === 'pdf' && (
            <iframe title={preview.name} src={preview.url} style={{ width: '100%', height: '70vh', border: 0 }} />)}
          {preview.url && extOf(preview.name) !== 'pdf' && (
            <img src={preview.url} alt={preview.name} style={{ maxWidth: '100%', maxHeight: '70vh' }} />)}
          {preview.content != null && (<>
            {preview.detail && <div className="notice">{preview.detail}</div>}
            <pre style={{ maxHeight: '60vh', overflow: 'auto', whiteSpace: 'pre-wrap' }}>{preview.content}</pre>
          </>)}
          {!preview.url && preview.content == null && <div className="notice">{preview.detail}</div>}
          <div className="modal-foot">
            <button className="btn" onClick={() => downloadFile(`/tasks/${id}/attachments/${preview.id}`, preview.name).catch((e) => setError(errMsg(e)))}>Download</button>
            <button className="btn primary" onClick={() => setPreview(null)}>Close preview</button>
          </div>
        </Modal>)}
      {ask === 'delete' && <ConfirmModal danger title="Delete task" confirmLabel="Delete" text="The task is hidden from all lists. Its workspace, versions and history stay in the database." onConfirm={() => act(() => api.delete(`/tasks/${id}`), true)} onClose={() => setAsk(null)} />}
      {ask === 'archive' && <ConfirmModal title="Archive task" confirmLabel="Archive" text="The task moves to the archive. Versions and history are kept and stay readable." onConfirm={() => act(() => api.post(`/tasks/${id}/archive`))} onClose={() => setAsk(null)} />}
      {ask === 'cancel' && <ReasonModal title="Cancel task" confirmLabel="Cancel task" text="The assignee is told and the workspace becomes read-only." onSubmit={(comment) => act(() => api.post(`/tasks/${id}/cancel`, { comment }))} onClose={() => setAsk(null)} />}
      {ask === 'reopen' && <ReasonModal title="Reopen task" confirmLabel="Reopen" text="The assignee can edit again. The next submission becomes a new major version (2.0, 3.0 …)." onSubmit={(comment) => act(() => api.post(`/tasks/${id}/reopen`, { comment }))} onClose={() => setAsk(null)} />}
    </Modal>
  );
}

export default function Tasks() {
  const { user } = useAuth();
  const { version } = useNotifications();
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [assignable, setAssignable] = useState([]);
  const [reviewers, setReviewers] = useState([]);
  const [projects, setProjects] = useState([]);
  const tabs = TABS[user.role] || TABS.employee;
  const [tab, setTab] = useState(tabs.some(([k]) => k === params.get('tab')) ? params.get('tab') : tabs[0][0]);
  const [status, setStatus] = useState('');
  const [form, setForm] = useState(null); // null | {} | task
  const [error, setError] = useState('');
  const canAssign = ['admin', 'onroll'].includes(user.role);

  const load = useCallback(() => {
    const f = (tabs.find(([k]) => k === tab) || tabs[0])[2];
    const q = clean({ scope: f.scope, status: status || (f.status && f.status.join(',')) });
    api.get('/tasks', { params: q }).then((r) => setRows(r.data)).catch((e) => setError(errMsg(e)));
  }, [tab, status, tabs]);
  useEffect(() => { load(); }, [load, version]);
  useEffect(() => {
    if (!canAssign) return;
    api.get('/users/assignable').then((r) => setAssignable(r.data)).catch(() => {});
    api.get('/users/reviewers').then((r) => setReviewers(r.data)).catch(() => {});
    api.get('/projects').then((r) => setProjects(r.data)).catch(() => {});
  }, [canAssign]);

  return (
    <>
      <PageHead title={user.role === 'admin' ? 'Task management' : 'Tasks'} sub={user.role === 'admin' ? 'Assign work, follow it and give the final approval.'
        : canAssign ? 'Your own tasks and the work you assigned.' : 'Work assigned to you.'}>
        {canAssign && <button className="btn primary" onClick={() => setForm({})} disabled={assignable.length === 0}
          title={assignable.length === 0 ? 'There is nobody you are allowed to assign to yet' : ''}>Assign a task</button>}
      </PageHead>
      <ErrorBox error={error} />
      <div className="card">
        <div className="row spread" style={{ marginBottom: 10 }}>
          <div className="tabs" style={{ margin: 0, border: 0, flexWrap: 'wrap' }}>{tabs.map(([k, l]) => (
            <button key={k} className={tab === k ? 'on' : ''} onClick={() => { setTab(k); setStatus(''); }}>{l}</button>))}</div>
          <select style={{ width: 'auto' }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status filter">
            <option value="">All statuses</option>{TASK_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select>
        </div>
        <div className="table-wrap">
          {rows && rows.length === 0 && <div className="empty">No tasks here.</div>}
          {rows && rows.length > 0 && (
            <table><thead><tr><th>ID</th><th>Title</th><th>Assigned to</th><th>Reviewer</th><th>Priority</th><th>Deadline</th><th>Status</th></tr></thead>
              <tbody>{rows.map((t) => (
                <tr key={t.id} className="click" onClick={() => navigate(`/tasks/${t.id}`)}>
                  <td>{t.code}</td><td>{t.title}<div className="muted">{t.project || ''}</div></td><td>{t.assigned_to_name}<div className="muted">by {t.assigned_by_name}</div></td>
                  <td>{t.reviewer_name || <span className="muted">auto</span>}</td>
                  <td><Badge value={t.priority}>{t.priority}</Badge></td><td>{fmtDate(t.deadline)}</td><td><Badge value={t.status} /></td>
                </tr>))}</tbody></table>)}
        </div>
      </div>
      {taskId && !form && <TaskDetail key={taskId} id={taskId} onClose={() => navigate('/tasks')} onChanged={load} onEdit={(t) => setForm(t)} />}
      {form && <TaskForm task={form.id ? form : null} assignable={assignable} reviewers={reviewers} projects={projects} onClose={() => setForm(null)}
        onDone={() => { setForm(null); load(); }} />}
    </>
  );
}

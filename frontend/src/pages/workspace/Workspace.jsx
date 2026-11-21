import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import { langOf, languageFor } from './monacoSetup';
import TerminalTabs from './TerminalTabs';
import FileTree from './FileTree';
import Palette from './Palette';
import SearchPanel from './SearchPanel';
import ProjectWizard from './ProjectWizard';
import AIPanel from './AIPanel';
import { setGuardEditor } from '../../services/copyGuard';
import { buildPreview, pickHtml } from './preview';
import api, { errMsg } from '../../services/api';
import { Badge, ConfirmModal, ErrorBox, Field, Modal, PromptModal } from '../../components/ui';
import { fmtDateTime, label as statusLabel } from '../../utils/format';
import { useTimer } from '../../context/TimerContext';
import { useRecording } from '../../context/RecordingContext';
import { useAuth } from '../../context/AuthContext';

const AUTOSAVE_MS = 1500;
const time = () => new Date().toLocaleTimeString();
const TEXT_UPLOAD_LIMIT = 1_000_000;
// Layout preferences only (panel sizes, theme). Project data is always stored on the server.
const pref = (k, d) => { try { const v = JSON.parse(localStorage.getItem(`wc.ide.${k}`)); return v ?? d; } catch { return d; } };
const setPref = (k, v) => { try { localStorage.setItem(`wc.ide.${k}`, JSON.stringify(v)); } catch { /* private mode */ } };
// AI panel width: a saved value that is not a sensible number falls back to the default
const clampAi = (w) => (Number.isFinite(w) ? Math.max(280, Math.min(640, Math.round(w))) : 380);
const parentOf = (p) => (p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '');
const baseOf = (p) => p.split('/').pop();
const mb = (b) => (b / 1_000_000).toFixed(b < 10_000_000 ? 2 : 0);

/** Build 29: the workspace's own recording indicator — Recording Active / Paused / Stopped, honest about the browser state.
 *  Build 31: says so when the tab is not in front — nothing is captured then, and the recording closes if the wait runs out. */
function RecordingPill({ rec, onStart }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!rec.away || !rec.awaySince) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);   // the countdown on a second monitor, where the tab is still visible
    return () => clearInterval(t);
  }, [rec.away, rec.awaySince]);
  if (!rec.supported) return null;
  if (rec.status === 'recording' || rec.status === 'paused') {
    const paused = rec.status === 'paused';
    const left = paused && rec.away;
    const secsLeft = left ? Math.max(0, Math.ceil((rec.awaySince + rec.awayGrace * 1000 - Date.now()) / 1000)) : 0;
    return <span data-testid="workspace-recording" role="status" className={`badge ${paused ? 'amber' : 'red'}`}
      title={left ? 'Your screen is not being recorded while this tab is not the window you are looking at.' : undefined}>
      <span className="dot" style={{ background: paused ? '#f0b429' : '#f04f5f', marginRight: 6 }} />
      {left ? `Paused — you left the tab (${secsLeft} s)` : paused ? 'Recording Paused' : 'Recording Active'}
      {!left && <>
        {' '}<button type="button" className="btn small" onClick={paused ? rec.resume : rec.pause}>{paused ? 'Resume' : 'Pause'}</button>
      </>}
    </span>;
  }
  if (rec.status === 'starting') return <span data-testid="workspace-recording" className="badge" role="status">Waiting for screen permission…</span>;
  return <button type="button" data-testid="workspace-recording" className="btn small" onClick={onStart}
    title={rec.message || 'The workspace records your screen (with your consent) so work time can be verified.'}>
    <span className="dot" style={{ background: '#e7ebf3', marginRight: 6 }} />{rec.message ? 'Record screen again' : 'Record screen'}</button>;
}

function NewFileModal({ langs, folder, onSubmit, onClose }) {
  const [langId, setLangId] = useState('');
  const [path, setPath] = useState(folder ? `${folder}/` : '');
  const lang = langs.find((l) => l.id === langId);
  const pick = (id) => { setLangId(id); const l = langs.find((x) => x.id === id); if (l) setPath((folder ? `${folder}/` : '') + l.file); };
  const sorted = [...langs].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <Modal title="New file" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (path.trim()) onSubmit(path.trim(), lang?.template || ''); }}>
        <Field label={`Language (${langs.length} available)`}>
          <select aria-label="Language" value={langId} onChange={(e) => pick(e.target.value)}>
            <option value="">Empty file</option>
            {sorted.map((l) => <option key={l.id} value={l.id}>{l.name}{l.kind === 'run' ? ' · runnable' : l.kind === 'preview' ? ' · preview' : ''}</option>)}
          </select></Field>
        <Field label="File path"><input autoFocus aria-label="File path" value={path} onChange={(e) => setPath(e.target.value)} />
          <small className="muted">Example: src/app.js — folders are created from the path.</small></Field>
        {lang?.note && <p className="muted">{lang.note}</p>}
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!path.trim()}>Create</button></div>
      </form>
    </Modal>
  );
}

/** Drag handle that resizes a panel. */
function Splitter({ vertical, onDrag, label }) {
  const start = (e) => {
    e.preventDefault();
    const move = (ev) => onDrag(vertical ? ev.clientX : ev.clientY);
    const stop = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', stop); document.body.style.userSelect = ''; };
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', stop);
  };
  return <div className={vertical ? 'split-v' : 'split-h'} role="separator" aria-label={label} aria-orientation={vertical ? 'vertical' : 'horizontal'} onMouseDown={start} />;
}

export default function Workspace() {
  const { taskId } = useParams();
  const [query] = useSearchParams();
  const wantFile = query.get('file');   // "Open" on a task reference file lands here with ?file=<path>
  const { user } = useAuth();
  const timer = useTimer();
  const rec = useRecording();
  const [recAsk, setRecAsk] = useState(false);
  const [ws, setWs] = useState(null);
  const [events, setEvents] = useState(null);   // file change log (side panel)
  const [note, setNote] = useState('');         // submission note
  const [files, setFiles] = useState([]);       // [{id, path, content}]
  const [tabs, setTabs] = useState([]);         // open file ids
  const [activeId, setActiveId] = useState(null);
  const [dirty, setDirty] = useState({});       // id -> true while unsaved
  const [log, setLog] = useState([]);
  const [panel, setPanel] = useState('log');    // terminal | output | problems | preview | log
  const [problems, setProblems] = useState([]);
  const [modal, setModal] = useState(null);
  const [versions, setVersions] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState('');
  // ---- layout ----
  const [side, setSide] = useState('explorer');             // explorer | search | null (hidden)
  const [sideW, setSideW] = useState(() => pref('sideW', 250));
  const [bottomH, setBottomH] = useState(() => pref('bottomH', 230));
  const [bottomOpen, setBottomOpen] = useState(true);
  const [theme, setTheme] = useState(() => pref('theme', 'dark'));
  const [palette, setPalette] = useState(null);             // 'files' | 'commands'
  const [filter, setFilter] = useState('');
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const [consoleLines, setConsoleLines] = useState([]);
  const [previewKey, setPreviewKey] = useState(0);
  const [termPorts, setTermPorts] = useState(null);   // {container port: port on this computer} while a terminal is open
  const [devPort, setDevPort] = useState('');         // port of the dev server shown in the Preview tab
  const [previewSrc, setPreviewSrc] = useState('files');   // files | server
  const [listening, setListening] = useState(null);   // answer of the server: what listens in the terminal container
  const wasUp = useRef(false);
  const ideRef = useRef(null);
  const bodyRef = useRef(null);
  const editorRef = useRef(null);
  // ---- AI assistant (right side) ----
  const [aiOpen, setAiOpen] = useState(() => pref('aiOpen', false));
  const [aiW, setAiW] = useState(() => clampAi(pref('aiW', 380)));
  const [monacoApi, setMonacoApi] = useState(null);
  const [inject, setInject] = useState(null);          // commands the assistant suggested for the terminal
  const termText = useRef('');
  useEffect(() => setPref('aiOpen', aiOpen), [aiOpen]);
  useEffect(() => setPref('aiW', aiW), [aiW]);
  // Small window (or browser zoom): the file list, the editor and the AI panel do not fit side by side.
  // Then only one of the two side panels is shown: opening AI hides the file list, opening the file list hides AI.
  const [bodyW, setBodyW] = useState(0);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return undefined;
    const measure = () => setBodyW(el.getBoundingClientRect().width);
    measure();
    if (typeof ResizeObserver === 'undefined') { window.addEventListener('resize', measure); return () => window.removeEventListener('resize', measure); }
    const ro = new ResizeObserver(measure); ro.observe(el);
    return () => ro.disconnect();
  }, [ws?.id]);
  const tight = bodyW > 0 && bodyW < 48 + sideW + 420 + 320 + 8;
  const lastPanels = useRef({ ai: aiOpen, side });
  useEffect(() => {
    const before = lastPanels.current;
    if (tight && aiOpen && side) {
      if (side !== before.side && before.ai) setAiOpen(false);   // the file list was just opened
      else setSide(null);                                         // AI was just opened, or the window became small
    }
    lastPanels.current = { ai: aiOpen, side };
  }, [tight, aiOpen, side]);
  const frameRef = useRef(null);
  const pendingReveal = useRef(null);
  useEffect(() => setPref('sideW', sideW), [sideW]);
  useEffect(() => setPref('bottomH', bottomH), [bottomH]);
  useEffect(() => setPref('theme', theme), [theme]);

  const [full, setFull] = useState(false);       // editor covers the whole window (menu and top bar hidden)
  const toggleFull = useCallback(() => {
    setFull((on) => {
      // also ask the browser for real full screen; if it refuses (e.g. inside an iframe) the editor still fills the window
      try {
        if (!on) document.documentElement.requestFullscreen?.()?.catch?.(() => {});
        else if (document.fullscreenElement) document.exitFullscreen?.()?.catch?.(() => {});
      } catch { /* not supported */ }
      return !on;
    });
  }, []);
  useEffect(() => {  // leaving browser full screen with Esc also restores the normal layout
    const onChange = () => { if (!document.fullscreenElement) setFull(false); };
    document.addEventListener('fullscreenchange', onChange);
    return () => { document.removeEventListener('fullscreenchange', onChange); if (document.fullscreenElement) document.exitFullscreen?.()?.catch?.(() => {}); };
  }, []);
  const [langs, setLangs] = useState({ runner: { available: false, reason: '' }, languages: [] });
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState(null);    // last run result
  const [stdin, setStdin] = useState('');
  useEffect(() => { api.get('/languages').then((r) => setLangs(r.data)).catch(() => {}); }, []);
  const timers = useRef({});
  const filesRef = useRef(files);
  filesRef.current = files;
  const uploadRef = useRef(null);
  const uploadFolder = useRef('');

  const say = useCallback((text) => setLog((l) => [...l.slice(-200), `[${time()}] ${text}`]), []);
  const active = files.find((f) => f.id === activeId) || null;
  const readOnly = !ws || ws.read_only;
  // While my own task is open and editable, the work timer books its time on this task.
  const mine = !!ws && ws.user_id === user.id && !ws.read_only;
  useEffect(() => {
    timer?.setTask?.(mine ? Number(taskId) : null);
    return () => timer?.setTask?.(null);
  }, [mine, taskId]); // eslint-disable-line react-hooks/exhaustive-deps
  // Build 29: opening the workspace starts the screen recording (browser permission + one consent per person).
  // Closing the workspace or signing out stops it. A page refresh ends it (browser rule) — the pill can restart it.
  // Build 31: leaving the tab pauses the recording at once and closes it if the person stays away too long;
  // coming back resumes it. Restarting after a close needs a click, because the browser only shares a screen
  // on a real user gesture — so the pill asks for it instead of pretending it is still recording.
  useEffect(() => {
    if (mine && rec.status === 'off') {
      const res = rec.autoStart(Number(taskId));
      if (res === 'needs-consent') setRecAsk(true);
    }
    return () => rec.stopWorkspace();
  }, [mine, taskId]); // eslint-disable-line react-hooks/exhaustive-deps
  const askRecording = () => {
    if (rec.needsConsent) setRecAsk(true);
    else rec.start(Number(taskId), 'workspace');
  };
  const loadEvents = useCallback(async () => {
    if (!ws) return;
    try { setEvents((await api.get(`/workspaces/${ws.id}/history`)).data); } catch (e) { setEvents([]); setError(errMsg(e)); }
  }, [ws?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (side === 'changes') loadEvents(); }, [side, loadEvents]);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/tasks/${taskId}/workspace`);
      setWs(data); setFiles(data.files); setError('');
      setTabs((t) => (t.length ? t.filter((id) => data.files.some((f) => f.id === id)) : data.files.slice(0, 1).map((f) => f.id)));
      setActiveId((id) => (data.files.some((f) => f.id === id) ? id : data.files[0]?.id ?? null));
      return data;
    } catch (e) { setError(errMsg(e)); return null; }
  }, [taskId]);
  useEffect(() => { load(); }, [load]);

  // ?file=<path> — the task screen asked for this file: show it once the workspace has loaded.
  useEffect(() => {
    if (!wantFile || !files.length) return;
    const hit = files.find((f) => f.path === wantFile);
    if (!hit) return;
    setTabs((t) => (t.includes(hit.id) ? t : [...t, hit.id]));
    setActiveId(hit.id);
  }, [wantFile, files]);

  // The terminal created / changed / deleted files: take them over. Files with unsaved edits in the editor keep the editor's text.
  const dirtyRef = useRef({});
  dirtyRef.current = dirty;
  const onTermPorts = useCallback((map) => { setTermPorts(map); if (!map) { setDevPort(''); setPreviewSrc('files'); setListening(null); } }, []);
  const onDevServer = useCallback((port) => {
    setDevPort((old) => {
      if (old !== port) setLog((l) => [...l, `[${new Date().toLocaleTimeString()}] Server on port ${port} started in the terminal. Open the Preview tab to see it.`]);
      return port;
    });
    setPreviewSrc('server');
  }, []);
  const syncFromTerminal = useCallback(async () => {
    try {
      const { data } = await api.get(`/tasks/${taskId}/workspace`);
      const mine = dirtyRef.current;
      setFiles((prev) => data.files.map((f) => (mine[f.id] ? prev.find((x) => x.id === f.id) || f : f)));
      setWs((w) => (w ? { ...w, last_saved_at: data.last_saved_at, usage: data.usage ?? w.usage } : w));
      setTabs((t) => t.filter((id) => data.files.some((f) => f.id === id)));
      setActiveId((id) => (data.files.some((f) => f.id === id) ? id : data.files[0]?.id ?? null));
    } catch { /* the next change tries again */ }
  }, [taskId]);

  const saveFile = useCallback(async (id, manual = false) => {
    clearTimeout(timers.current[id]);
    const f = filesRef.current.find((x) => x.id === id);
    if (!f) return true;
    try {
      const { data } = await api.put(`/workspaces/${ws.id}/files`, { path: f.path, content: f.content, manual });
      setDirty((d) => { const n = { ...d }; if (filesRef.current.find((x) => x.id === id)?.content === f.content) delete n[id]; return n; });
      setWs((w) => ({ ...w, last_saved_at: data.last_saved_at, task_status: data.task_status }));
      say(`${manual ? 'Saved' : 'Auto-saved'} ${f.path}`);
      return true;
    } catch (e) { say(`SAVE FAILED for ${f.path}: ${errMsg(e)}`); setError(errMsg(e)); return false; }
  }, [ws?.id, say]);

  const onEdit = (value) => {
    if (!active || readOnly) return;
    const id = active.id;
    setFiles((fs) => fs.map((f) => (f.id === id ? { ...f, content: value ?? '' } : f)));
    setDirty((d) => ({ ...d, [id]: true }));
    clearTimeout(timers.current[id]);
    timers.current[id] = setTimeout(() => saveFile(id), AUTOSAVE_MS);
  };

  const saveAll = async (manual = true) => {
    setSaving(true);
    const ids = manual && active ? [...new Set([...Object.keys(dirty).map(Number), active.id])] : Object.keys(dirty).map(Number);
    const results = await Promise.all(ids.map((id) => saveFile(id, manual)));
    setSaving(false);
    return results.every(Boolean);
  };

  useEffect(() => {  // warn before leaving with unsaved edits
    const warn = (e) => { if (Object.keys(dirty).length) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), []);
  useEffect(() => () => setGuardEditor(null), []);

  const reveal = (line, column = 1) => {
    const ed = editorRef.current;
    if (!ed || !line) return;
    ed.revealLineInCenter(line); ed.setPosition({ lineNumber: line, column }); ed.focus();
  };
  const openFile = (id, line, column) => {
    setTabs((t) => (t.includes(id) ? t : [...t, id]));
    if (line) { if (id === activeId) reveal(line, column); else pendingReveal.current = { id, line, column }; }
    setActiveId(id);
  };
  useEffect(() => {  // jump to the search hit once the file is showing
    const p = pendingReveal.current;
    if (p && p.id === activeId) { pendingReveal.current = null; setTimeout(() => reveal(p.line, p.column), 60); }
  }, [activeId]);
  const closeTab = (id) => {
    setTabs((t) => { const n = t.filter((x) => x !== id); if (id === activeId) setActiveId(n[n.length - 1] ?? null); return n; });
  };

  const run = async (fn) => { try { await fn(); setError(''); } catch (e) { setError(errMsg(e)); } setModal(null); };
  /** Save everything, run a server-side explorer operation, then reload the file list. */
  const fileOp = (label, fn) => run(async () => {
    setBusy(label);
    try {
      if (Object.keys(dirty).length && !(await saveAll(false))) throw new Error('save failed');
      await fn();
      await load();
      say(label);
    } finally { setBusy(''); }
  });
  const createFile = (path, content = '') => run(async () => {
    const { data } = await api.put(`/workspaces/${ws.id}/files`, { path, content, manual: true });
    setFiles((fs) => [...fs.filter((f) => f.id !== data.file.id), data.file].sort((a, b) => a.path.localeCompare(b.path)));
    openFile(data.file.id); say(`Created ${data.file.path}`);
  });
  const runCode = async () => {
    if (!active || running) return;
    // A file the runner cannot execute (a .jsx, a .md, a .gitignore): say so in the Output panel. Doing nothing
    // when the button is pressed looks like a broken program.
    if (!canRun) { setPanel('output'); setBottomOpen(true);
      setOutput({ status: 'not_started', file: active.path,
        message: `${runHint}${activeLang?.kind === 'preview' ? '' : ' — use the Terminal + Preview tab for a project like this.'}` });
      return; }
    setPanel('output'); setBottomOpen(true); setRunning(true); setOutput({ status: 'running', file: active.path });
    try {
      if (!readOnly && !(await saveAll(false))) throw new Error('Could not save your files, so nothing was run.');
      const { data } = await api.post(`/workspaces/${ws.id}/run`, { file_id: active.id, stdin }, { timeout: 120000 });
      setOutput(data); say(`Ran ${data.file}: ${data.status} in ${data.duration_ms} ms`);
    } catch (e) { setOutput({ status: 'not_started', file: active.path, message: errMsg(e) }); }
    setRunning(false);
  };
  const stopCode = () => api.post(`/workspaces/${ws.id}/run/stop`).catch(() => {});
  const movePath = (from, to) => fileOp(`Moved ${from} → ${to}`, () => api.post(`/workspaces/${ws.id}/move`, { from_path: from, to_path: to }));
  const copyPath = (from, to) => fileOp(`Copied ${from} → ${to}`, () => api.post(`/workspaces/${ws.id}/copy`, { from_path: from, to_path: to }));
  const deleteFolder = (path) => fileOp(`Deleted folder ${path}`, () => api.delete(`/workspaces/${ws.id}/folder?path=${encodeURIComponent(path)}`));
  const deleteFile = (f) => run(async () => {
    clearTimeout(timers.current[f.id]);
    await api.delete(`/workspaces/${ws.id}/files/${f.id}`);
    setFiles((fs) => fs.filter((x) => x.id !== f.id)); closeTab(f.id);
    setDirty((d) => { const n = { ...d }; delete n[f.id]; return n; });
    say(`Deleted ${f.path}`);
  });
  const uploadFiles = async (list, folder = '') => {
    let done = 0;
    for (const file of Array.from(list)) {
      if (file.size > TEXT_UPLOAD_LIMIT) { say(`Skipped ${file.name}: larger than 1 MB`); continue; }
      const text = await file.text();
      if (text.includes('\u0000')) { say(`Skipped ${file.name}: not a text file`); continue; }
      const rel = (file.webkitRelativePath || file.name).split('/').map((p) => p.replace(/[^A-Za-z0-9_\-. @+()[\]]/g, '_')).join('/');
      try { await api.put(`/workspaces/${ws.id}/files`, { path: (folder ? `${folder}/` : '') + rel, content: text, manual: true }); done += 1; }
      catch (e) { say(`Upload failed for ${file.name}: ${errMsg(e)}`); setError(errMsg(e)); }
    }
    await load(); say(`Uploaded ${done} file(s)`);
  };
  const upload = async (e) => { await uploadFiles(e.target.files, uploadFolder.current); e.target.value = ''; };
  const saveBlob = (blob, name) => { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url); };
  const download = () => saveBlob(new Blob([active.content], { type: 'text/plain' }), baseOf(active.path));
  const downloadProject = async () => {
    try {
      if (!readOnly && Object.keys(dirty).length) await saveAll(false);
      const r = await api.get(`/workspaces/${ws.id}/download`, { responseType: 'blob' });
      saveBlob(r.data, `${ws.task_code}.zip`); say('Downloaded the project as a zip');
    } catch (e) { setError(errMsg(e)); }
  };
  const showVersions = async () => {
    try { if (dirty[active.id]) await saveFile(active.id); setVersions((await api.get(`/workspaces/${ws.id}/files/${active.id}/versions`)).data); }
    catch (e) { setError(errMsg(e)); }
  };
  const restore = async (v) => {
    try {
      const { data } = await api.post(`/workspaces/${ws.id}/files/${active.id}/versions/${v.id}/restore`);
      setFiles((fs) => fs.map((f) => (f.id === active.id ? { ...f, content: data.content } : f)));
      setVersions(null); say(`Restored ${active.path} to version ${v.version_no}`);
    } catch (e) { setError(errMsg(e)); }
  };
  const submit = () => run(async () => {
    if (!(await saveAll(true))) throw new Error('save failed');
    const { data } = await api.post(`/workspaces/${ws.id}/submit`, { note: note.trim() || null });
    setNote('');
    say(`Submitted version ${data.version} → ${data.stage === 'onroll_review' ? 'On-Roll review' : 'Admin final review'}`);
    await load();
  });
  const onTemplate = async (data, t) => {
    setModal(null);
    const fresh = await load();
    const f = (fresh?.files || data.files).find((x) => x.path === data.open);
    if (f) openFile(f.id);
    say(`Created ${t.name} project files`);
  };
  // New File / New Folder typed into the explorer. A folder is stored as a hidden .gitkeep file inside it.
  const treeRef = useRef(null);
  const treeCreate = (mode, path) => (mode === 'file' ? createFile(path) : run(async () => {
    const { data } = await api.put(`/workspaces/${ws.id}/files`, { path: `${path}/.gitkeep`, content: '', manual: true });
    setFiles((fs) => [...fs.filter((f) => f.id !== data.file.id), data.file].sort((x, y) => x.path.localeCompare(y.path)));
    say(`Created folder ${path}`);
  }));
  const newInExplorer = (what) => { setSide('explorer'); setTimeout(() => treeRef.current?.[what](''), 0); };
  const treeAction = (type, node) => {
    if (type === 'new') setModal({ type: 'new', folder: node.path });
    else if (type === 'newFolder') setModal({ type: 'newFolder', folder: node.path });
    else if (type === 'rename') setModal({ type: 'rename', node });
    else if (type === 'copy') setModal({ type: 'copy', node });
    else if (type === 'delete') setModal({ type: 'delete', file: node });
    else if (type === 'deleteFolder') setModal({ type: 'deleteFolder', node });
  };

  const onMount = (editor, monaco) => {
    editorRef.current = editor;
    setGuardEditor(editor);
    setMonacoApi(monaco);
    const update = () => setProblems(monaco.editor.getModelMarkers({}).filter((m) => m.severity >= 4)
      .map((m) => ({ path: m.resource.path.replace(/^\//, ''), line: m.startLineNumber, column: m.startColumn, level: m.severity === 8 ? 'error' : 'warning', message: m.message })));
    monaco.editor.onDidChangeMarkers(update);
    editor.onDidChangeCursorPosition((e) => setCursor({ line: e.position.lineNumber, column: e.position.column }));
    editor.addCommand(monaco.KeyMod.Alt | monaco.KeyMod.Shift | monaco.KeyCode.KeyF, () => editor.getAction('editor.action.formatDocument')?.run());
  };
  const htmlFile = useMemo(() => pickHtml(active, files), [active, files]);
  const devUrl = termPorts && devPort && termPorts[devPort] ? `${window.location.protocol}//${window.location.hostname}:${termPorts[devPort]}/` : '';
  const showDev = Boolean(termPorts && previewSrc === 'server' && devUrl);
  // state of the chosen port inside the terminal container: unknown | none | local | noanswer | up
  const probe = listening && listening.port === devPort ? listening : null;
  const serverState = !probe ? 'unknown' : !probe.listening[devPort] ? 'none' : probe.listening[devPort] === 'local' ? 'local'
    : probe.http === 'fail' ? 'noanswer' : 'up';
  useEffect(() => {          // the server came up after the frame was loaded: load it again
    if (serverState === 'up' && !wasUp.current) setPreviewKey((k) => k + 1);
    if (serverState !== 'unknown') wasUp.current = serverState === 'up';
  }, [serverState]);
  const otherPorts = probe ? Object.keys(probe.listening).filter((p) => p !== devPort) : [];
  const preview = useMemo(() => (htmlFile ? buildPreview(htmlFile, files, String(previewKey)) : null), [htmlFile, files, previewKey]);
  useEffect(() => { setConsoleLines([]); }, [preview]);
  useEffect(() => {  // console output and runtime errors from the preview frame
    const onMsg = (e) => {
      if (!e.data || e.data.wcPreview === undefined || e.source !== frameRef.current?.contentWindow) return;
      setConsoleLines((l) => [...l.slice(-300), { level: String(e.data.level), text: String(e.data.text).slice(0, 4000) }]);
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const showPanel = (p) => { setPanel(p); setBottomOpen(true); };
  const commands = [
    { label: 'File: Save all', hint: 'Ctrl+S', disabled: readOnly, run: () => saveAll(true) },
    { label: 'File: New file…', disabled: readOnly, run: () => newInExplorer('newFile') },
    { label: 'File: New file from language template…', disabled: readOnly, run: () => setModal({ type: 'new', folder: '' }) },
    { label: 'File: New folder…', disabled: readOnly, run: () => newInExplorer('newFolder') },
    { label: 'File: New project from template…', disabled: readOnly, run: () => setModal({ type: 'wizard' }) },
    { label: 'File: Upload files…', disabled: readOnly, run: () => { uploadFolder.current = ''; uploadRef.current?.click(); } },
    { label: 'File: Download project as zip', run: downloadProject },
    { label: 'File: Version history of this file', disabled: !active, run: showVersions },
    { label: 'Go to file…', hint: 'Ctrl+P', run: () => setPalette('files') },
    { label: 'Search: Find in files', hint: 'Ctrl+Shift+F', run: () => setSide('search') },
    { label: 'View: Toggle sidebar', hint: 'Ctrl+B', run: () => setSide((s) => (s ? null : 'explorer')) },
    { label: 'View: Toggle bottom panel', run: () => setBottomOpen((o) => !o) },
    { label: 'View: Terminal', hint: 'Ctrl+`', run: () => showPanel('terminal') },
    { label: 'View: Output', run: () => showPanel('output') },
    { label: 'View: Problems', run: () => showPanel('problems') },
    { label: 'View: Preview', run: () => showPanel('preview') },
    { label: `View: Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`, run: () => setTheme(theme === 'dark' ? 'light' : 'dark') },
    { label: 'View: Toggle full screen', hint: 'F11', run: toggleFull },
    { label: 'View: Toggle AI assistant', hint: 'Ctrl+I', run: () => setAiOpen((o) => !o) },
    { label: 'Run: Run the open file', disabled: !active, run: runCode },
    { label: 'Editor: Format document', hint: 'Shift+Alt+F', disabled: !active, run: () => editorRef.current?.getAction('editor.action.formatDocument')?.run() },
    { label: 'Task: Submit for review…', disabled: readOnly, run: () => setModal({ type: 'submit' }) },
  ];

  useEffect(() => {  // keyboard shortcuts (capture phase, so they also work while typing in the editor)
    const onKey = (e) => {
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      const hit = (fn) => { e.preventDefault(); e.stopPropagation(); fn(); };
      if (e.key === 'F11') hit(toggleFull);
      else if (!mod) return;
      else if (k === 's') hit(() => { if (!readOnly) saveAll(true); });
      else if (k === 'p' && e.shiftKey) hit(() => setPalette('commands'));
      else if (k === 'p') hit(() => setPalette('files'));
      else if (k === 'f' && e.shiftKey) hit(() => setSide('search'));
      else if (k === 'b') hit(() => setSide((s) => (s ? null : 'explorer')));
      else if (k === 'i' && !e.shiftKey && !e.altKey) hit(() => setAiOpen((o) => !o));
      else if (e.key === '`') hit(() => { if (bottomOpen && panel === 'terminal') setBottomOpen(false); else showPanel('terminal'); });
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  });

  if (!ws) return <div className="main"><ErrorBox error={error} />{!error && <div className="empty">Loading workspace…</div>}<Link to="/tasks">Back to tasks</Link></div>;
  const unsaved = Object.keys(dirty).length;
  const activeLang = active ? langOf(active.path, langs.languages) : null;
  const canRun = activeLang?.kind === 'run';
  const runHint = !active ? 'Open a file first' : canRun ? `Run ${active.path} in an isolated ${activeLang.name} container`
    : activeLang?.kind === 'preview' ? 'Use the Preview tab for this file' : activeLang?.note || 'This file type cannot be run';
  const usage = ws.usage;
  const errorCount = problems.filter((p) => p.level === 'error').length;
  const dragAi = (x) => { const r = bodyRef.current?.getBoundingClientRect(); if (r) setAiW(clampAi(r.right - x)); };
  // What the assistant may do in the editor. Edits go through Monaco, so Ctrl+Z undoes them and autosave stores them.
  const editorApi = {
    getSelection: () => { const ed = editorRef.current; const sel = ed?.getSelection?.(); return ed && sel && !sel.isEmpty() ? ed.getModel().getValueInRange(sel) : ''; },
    insert: (mode, code) => {
      const ed = editorRef.current;
      if (!ed || !active) return 'Open a file in the editor first.';
      if (readOnly) return 'This project is read-only right now.';
      const sel = ed.getSelection();
      let range; let text = code;
      if (mode === 'replace') {
        if (!sel || sel.isEmpty()) return 'Select the code you want to replace first.';
        range = sel;
      } else if (mode === 'below') {
        const line = sel ? sel.endLineNumber : ed.getPosition().lineNumber;
        const col = ed.getModel().getLineMaxColumn(line);
        range = { startLineNumber: line, startColumn: col, endLineNumber: line, endColumn: col };
        text = `\n${code}`;
      } else {
        const p = ed.getPosition();
        range = { startLineNumber: p.lineNumber, startColumn: p.column, endLineNumber: p.lineNumber, endColumn: p.column };
      }
      ed.pushUndoStop(); ed.executeEdits('ai-assistant', [{ range, text, forceMoveMarkers: true }]); ed.pushUndoStop(); ed.focus();
      say(`AI code ${mode === 'replace' ? 'replaced the selection' : 'inserted'} in ${active.path}`);
      return true;
    },
  };
  const aiRunOutput = [
    output && output.status !== 'running' ? `[run ${output.file || ''}: ${output.status}${output.exit_code != null ? `, exit code ${output.exit_code}` : ''}]\n${output.stdout || ''}${output.stderr ? `\n${output.stderr}` : ''}${output.message ? `\n${output.message}` : ''}` : '',
    consoleLines.filter((l) => l.level === 'error' || l.level === 'warn').map((l) => `[preview ${l.level}] ${l.text}`).join('\n'),
    problems.slice(0, 40).map((p) => `[editor ${p.level}] ${p.path}:${p.line}:${p.column} ${p.message}`).join('\n'),
  ].filter((s) => s.trim()).join('\n\n');
  const sendToTerminal = (cmds) => { showPanel('terminal'); setInject({ n: Date.now(), cmds }); };
  const aiCreateFile = async (path, content) => {
    if (readOnly) return 'This project is read-only right now.';
    if (files.some((f) => f.path === path.trim())) return `${path} already exists. Use “Preview changes” to change an existing file.`;
    try {
      const { data } = await api.put(`/workspaces/${ws.id}/files`, { path: path.trim(), content, manual: true });
      setFiles((fs) => [...fs.filter((f) => f.id !== data.file.id), data.file].sort((a, b) => a.path.localeCompare(b.path)));
      openFile(data.file.id); say(`Created ${data.file.path} from an AI answer`);
      return true;
    } catch (e) { return errMsg(e); }
  };
  const aiApplied = (res) => {
    if (!res.applied.length) return;
    const ids = new Set(res.applied.map((f) => f.id));
    setFiles((fs) => [...fs.filter((f) => !ids.has(f.id)), ...res.applied.map((f) => ({ id: f.id, path: f.path, content: f.content }))].sort((a, b) => a.path.localeCompare(b.path)));
    setDirty((d) => Object.fromEntries(Object.entries(d).filter(([id]) => !ids.has(Number(id)))));
    setWs((w) => ({ ...w, last_saved_at: res.last_saved_at, task_status: res.task_status }));
    res.applied.forEach((f) => say(`AI change applied and saved: ${f.path}`));
    openFile(res.applied[0].id);
  };
  const dragSide = (x) => setSideW(Math.max(160, Math.min(600, x - (bodyRef.current?.getBoundingClientRect().left || 0) - 48)));
  const dragBottom = (y) => { const r = bodyRef.current?.getBoundingClientRect(); if (r) setBottomH(Math.max(90, Math.min(r.height - 120, r.bottom - y))); };
  const actBtn = (id, label, ico) => (
    <button type="button" className={`act ${side === id ? 'on' : ''}`} title={label} aria-label={label} aria-pressed={side === id}
      onClick={() => setSide((s) => (s === id ? null : id))}>{ico}</button>);

  return (
    <div ref={ideRef} className={`ide ${full ? 'full' : ''} ${theme === 'light' ? 'light' : ''}`.replace(/\s+/g, ' ').trim()}>
      <div className="ide-bar">
        <Link to={`/tasks/${taskId}`} className="btn small">← {ws.task_code}</Link>
        <b>{ws.task_title}</b><Badge value={ws.task_status} />
        <span className="muted">{unsaved ? `${unsaved} unsaved file(s)…` : ws.last_saved_at ? `All changes saved to server · ${fmtDateTime(ws.last_saved_at)}` : 'Nothing saved yet'}</span>
        <span style={{ flex: 1 }} />
        {busy && <span className="muted">{busy}…</span>}
        {!readOnly && <RecordingPill rec={rec} onStart={askRecording} />}
        {readOnly && <span className="badge amber">Read-only · {ws.task_status === 'assigned' ? 'accept the task first' : statusLabel(ws.task_status)}</span>}
        {recAsk && <ConfirmModal title="Screen recording while you work" confirmLabel="I agree, record my screen"
          onClose={() => setRecAsk(false)}
          onConfirm={() => { setRecAsk(false); rec.acceptConsent(); rec.start(Number(taskId), 'workspace'); }}
          text={`Your screen is recorded while this workspace is open, so your working time can be verified. Videos are stored privately on the company server and only you, your lead and Admins can watch them; they are deleted automatically after ${rec.retentionDays} days. Nothing is recorded secretly: the browser will ask which screen to share, you can pause or stop at any time, and recording ends when the workspace closes or you sign out. The recording also pauses the moment this tab is not the window you are looking at — nothing is captured while you are outside — and it is closed and saved if you stay away more than ${Math.round(rec.awayGrace)} seconds.`}
        />}
        <button className="btn small" disabled={readOnly || saving} onClick={() => saveAll(true)}>Save</button>
        {running
          ? <button className="btn small danger" onClick={stopCode}>■ Stop</button>
          : <button className="btn small" disabled={!active} title={runHint} onClick={runCode}>▶ Run</button>}
        <button className="btn small" disabled={!active} onClick={showVersions}>History</button>
        <button className="btn small" disabled={!active} onClick={download}>Download file</button>
        <button className="btn small primary" disabled={readOnly} onClick={() => setModal({ type: 'submit' })}>Submit</button>
        <button className="btn small" onClick={() => setAiOpen((o) => !o)} aria-pressed={aiOpen} title="AI assistant (Ctrl+I)">✦ AI</button>
        <button className="btn small" onClick={toggleFull} aria-pressed={full} title="Full screen (F11)">{full ? '⤡ Exit full screen' : '⛶ Full screen'}</button>
      </div>

      <div className="ide-body" ref={bodyRef}>
        <div className="ide-act" role="toolbar" aria-label="Activity bar">
          {actBtn('explorer', 'Explorer (Ctrl+B)', '🗂')}
          {actBtn('search', 'Search in files (Ctrl+Shift+F)', '🔍')}
          {actBtn('task', 'Task details', '☑')}
          {actBtn('changes', 'File history', '🕘')}
          <button type="button" className="act" title="New project from template" aria-label="New project from template" disabled={readOnly} onClick={() => setModal({ type: 'wizard' })}>✚</button>
          <button type="button" className="act" title="Command palette (Ctrl+Shift+P)" aria-label="Command palette" onClick={() => setPalette('commands')}>⌘</button>
          <span style={{ flex: 1 }} />
          <button type="button" className="act" title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} aria-label="Switch theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☀' : '☾'}</button>
        </div>

        {side && (<>
          <div className="ide-side" style={{ width: sideW }}>
            {side === 'explorer' && (
              <div className="side-pane">
                <div className="side-title">Explorer
                  {!readOnly && <span className="row" style={{ gap: 2 }}>
                    <button className="tree-act show" title="New File…" aria-label="New File" onClick={() => treeRef.current?.newFile()}>＋</button>
                    <button className="tree-act show" title="New Folder…" aria-label="New Folder" onClick={() => treeRef.current?.newFolder()}>▣</button>
                    <button className="tree-act show" title="Upload text files" onClick={() => { uploadFolder.current = ''; uploadRef.current.click(); }}>⇪</button>
                    <button className="tree-act show" title="Download project as zip" onClick={downloadProject}>⇩</button>
                    <button className="tree-act show" title="Collapse folders" aria-label="Collapse folders" onClick={() => treeRef.current?.collapseAll()}>⊟</button>
                    <input ref={uploadRef} type="file" multiple hidden onChange={upload} /></span>}
                  {readOnly && <button className="tree-act show" title="Download project as zip" onClick={downloadProject}>⇩</button>}
                </div>
                <div style={{ padding: '0 10px 6px' }}><input aria-label="Filter files" placeholder="Filter files" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ padding: '5px 8px' }} /></div>
                <FileTree ref={treeRef} files={files} activeId={activeId} dirty={dirty} readOnly={readOnly} filter={filter} onOpen={openFile} onAction={treeAction}
                  onCreate={treeCreate} onRename={(from, to) => movePath(from, to)}
                  onMove={(from, folder) => movePath(from, (folder ? `${folder}/` : '') + baseOf(from))} onDropFiles={uploadFiles} />
              </div>)}
            {side === 'search' && <SearchPanel files={files} onOpen={openFile} />}
            {side === 'task' && (
              <div className="side-pane" style={{ padding: '0 10px 10px', overflow: 'auto' }}>
                <div className="side-title" style={{ padding: '8px 0' }}>Task details</div>
                <b>{ws.task_code} · {ws.task_title}</b>
                <div style={{ margin: '6px 0' }}><Badge value={ws.task_status} /></div>
                <div className="muted">Requirements</div><div style={{ whiteSpace: 'pre-wrap', marginBottom: 8 }}>{ws.task_requirements || '—'}</div>
                <div className="muted">Expected deliverables</div><div style={{ whiteSpace: 'pre-wrap', marginBottom: 8 }}>{ws.task_deliverables || '—'}</div>
                <Link className="btn small" to={`/tasks/${taskId}`}>Versions, files and task history</Link>
              </div>)}
            {side === 'changes' && (
              <div className="side-pane" style={{ padding: '0 10px 10px', overflow: 'auto' }}>
                <div className="side-title" style={{ padding: '8px 0' }}>File history
                  <button className="tree-act show" title="Refresh file history" aria-label="Refresh file history" onClick={loadEvents}>↻</button></div>
                {events === null && <p className="muted">Loading…</p>}
                {events && events.length === 0 && <p className="muted">No file changes recorded yet.</p>}
                {events && events.map((e) => (
                  <div key={e.id} style={{ marginBottom: 8 }}>
                    <div><b>{e.action}</b> {e.path}</div>
                    <div className="muted">{e.modified_by_name || '—'} · {fmtDateTime(e.at)}
                      {e.new_version ? ` · v${e.previous_version ?? 0} → v${e.new_version}` : ''}{e.submission_version ? ` · in ${e.submission_version}` : ''}</div>
                    {e.summary && <div className="muted">{e.summary}</div>}
                  </div>))}
              </div>)}
          </div>
          <Splitter vertical label="Resize sidebar" onDrag={dragSide} />
        </>)}

        <div className="ide-main">
          <div className="ide-edit">
            <ErrorBox error={error} />
            <div className="ide-tabs" role="tablist">{tabs.map((id) => { const f = files.find((x) => x.id === id); return f && (
              <div key={id} role="tab" aria-selected={id === activeId} className={`t ${id === activeId ? 'on' : ''}`} title={f.path} onClick={() => setActiveId(id)}
                onAuxClick={(e) => { if (e.button === 1) closeTab(id); }}>
                {baseOf(f.path)}{dirty[id] ? ' ●' : ''} <span className="x" role="button" aria-label={`Close ${f.path}`} onClick={(e) => { e.stopPropagation(); closeTab(id); }}>×</span></div>); })}</div>
            {active && <div className="crumbs">{active.path.split('/').join(' › ')}</div>}
            <div style={{ flex: 1, minHeight: 0 }}>
              {active
                ? <Editor path={active.path} language={languageFor(active.path, langs.languages)} value={active.content} onChange={onEdit} onMount={onMount}
                    theme={theme === 'dark' ? 'vs-dark' : 'vs'}
                    options={{ readOnly, minimap: { enabled: true }, fontSize: 13.5, automaticLayout: true, tabSize: 2, formatOnPaste: true, bracketPairColorization: { enabled: true } }} />
                : <div className="empty">
                    <p><b>WORKCODE IDE</b></p>
                    <p>Open a file from the explorer · Ctrl+P go to file · Ctrl+Shift+P commands · Ctrl+` terminal</p>
                    {!readOnly && <p className="row" style={{ justifyContent: 'center' }}>
                      <button className="btn small" onClick={() => newInExplorer('newFile')}>New file</button>
                      <button className="btn small primary" onClick={() => setModal({ type: 'wizard' })}>New project from template</button></p>}
                  </div>}
            </div>
          </div>

          {bottomOpen && (<>
            <Splitter label="Resize bottom panel" onDrag={dragBottom} />
            <div className="ide-bottom" style={{ height: bottomH }}>
              <div className="tabs" style={{ margin: 0, padding: '0 8px' }}>
                <button className={panel === 'terminal' ? 'on' : ''} onClick={() => setPanel('terminal')}>Terminal</button>
                <button className={panel === 'output' ? 'on' : ''} onClick={() => setPanel('output')}>Output</button>
                <button className={panel === 'problems' ? 'on' : ''} onClick={() => setPanel('problems')}>Problems ({problems.length})</button>
                <button className={panel === 'preview' ? 'on' : ''} onClick={() => setPanel('preview')}>Preview</button>
                <button className={panel === 'log' ? 'on' : ''} onClick={() => setPanel('log')}>Activity log</button>
                <button style={{ marginLeft: 'auto' }} title="Hide panel" aria-label="Hide panel" onClick={() => setBottomOpen(false)}>✕</button>
              </div>
              {panel === 'log' && <div className="body">{log.length ? log.join('\n') : 'Saves, runs and submissions are listed here.'}</div>}
              {/* kept mounted so the shell survives switching tabs */}
              <div style={{ flex: 1, minHeight: 0, display: panel === 'terminal' ? 'flex' : 'none' }}>
                <TerminalTabs workspaceId={ws.id} langs={langs.languages} runner={langs.runner} defaultLang={canRun ? activeLang.id : undefined} textRef={termText} inject={inject} onFilesChanged={syncFromTerminal} onPorts={onTermPorts} onServer={onDevServer} onListening={setListening} probePort={showDev && panel === 'preview' && bottomOpen ? devPort : ''} />
              </div>
              {panel === 'output' && (
                <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
                  <div className="body" data-testid="run-output">
                    {!output && (langs.runner.available ? 'Press ▶ Run to run the open file. Output appears here.'
                      : `Running code is not available on this server: ${langs.runner.reason || 'the runner status could not be read.'}`)}
                    {output?.status === 'running' && `Running ${output.file}…`}
                    {output?.status === 'not_started' && <span style={{ color: '#ff8f9b' }}>Not started: {output.message}</span>}
                    {output && !['running', 'not_started'].includes(output.status) && (<>
                      {output.stdout}
                      {output.stderr && <span style={{ color: '#ff8f9b' }}>{output.stderr}</span>}
                      {'\n'}<span className="muted">— {output.status === 'ok' ? 'finished' : output.status === 'timeout' ? `stopped: time limit of ${output.time_limit_seconds}s reached`
                        : output.status === 'killed' ? 'stopped (by you, or out of memory)' : `exited with code ${output.exit_code}`} · {output.duration_ms} ms
                        {output.truncated ? ' · output was cut because it is too long' : ''}</span>
                    </>)}
                  </div>
                  <textarea aria-label="Program input" placeholder="Program input (stdin), optional" value={stdin} onChange={(e) => setStdin(e.target.value)}
                    style={{ width: 230, resize: 'none', borderRadius: 0, border: 0, borderLeft: '1px solid var(--line)', fontFamily: 'ui-monospace,Consolas,monospace', fontSize: 12.5 }} />
                </div>)}
              {panel === 'problems' && (
                <div className="body" style={{ whiteSpace: 'normal' }}>
                  {problems.length === 0 && 'No problems found by the editor.'}
                  {problems.map((p, i) => { const f = files.find((x) => x.path === p.path); return (
                    <div key={i} className="search-hit" onClick={() => f && openFile(f.id, p.line, p.column)}>
                      <span style={{ color: p.level === 'error' ? '#ff8f9b' : '#e3b04b' }}>{p.level}</span> {p.message} <span className="muted">{p.path}:{p.line}</span></div>); })}
                </div>)}
              {panel === 'preview' && termPorts && (
                <div className="row muted preview-bar" role="group" aria-label="Preview source">
                  <button className={`btn small${previewSrc === 'files' ? ' primary' : ''}`} onClick={() => setPreviewSrc('files')}>HTML files</button>
                  <button className={`btn small${previewSrc === 'server' ? ' primary' : ''}`} onClick={() => { setPreviewSrc('server'); if (!devPort) setDevPort(Object.keys(termPorts)[0] || ''); }}>Terminal server</button>
                  {previewSrc === 'server' && (<>
                    <label className="row" style={{ gap: 6 }}>Port
                      <select aria-label="Server port" value={devPort} onChange={(e) => setDevPort(e.target.value)} style={{ width: 90, padding: '2px 6px' }}>
                        {Object.keys(termPorts).map((p) => <option key={p} value={p}>{p}</option>)}
                      </select></label>
                    <button className="btn small" onClick={() => setPreviewKey((k) => k + 1)}>↻ Reload</button>
                    {devUrl && <a className="btn small" href={devUrl} target="_blank" rel="noreferrer">Open in new tab ↗</a>}
                  </>)}
                </div>)}
              {panel === 'preview' && showDev && (
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                  <div className={`server-status ${serverState}`} role="status" data-testid="server-status">
                    {serverState === 'unknown' && <>Checking port {devPort} in the terminal…</>}
                    {serverState === 'up' && <>● Port {devPort} is answering in the terminal. Still a white page? Then the app itself has an error: press <b>Open in new tab ↗</b>, then F12 → Console.</>}
                    {serverState === 'noanswer' && <>▲ Something listens on port {devPort} but it does not answer yet. Wait a moment, then press Reload.</>}
                    {serverState === 'local' && <>▲ The program on port {devPort} listens only on localhost inside the terminal, so the preview cannot reach it. Stop it (Ctrl+C) and start it on all addresses, e.g. <code>npm run dev -- --host 0.0.0.0</code></>}
                    {serverState === 'none' && <>▲ Nothing is listening on port {devPort} in the terminal. Start your server there
                      {otherPorts.length > 0 && <> (listening now: {otherPorts.map((p) => (termPorts[p] ? p : `${p} — not a preview port`)).join(', ')})</>}.</>}
                  </div>
                  <iframe key={`${devUrl}#${previewKey}`} title="Terminal server preview" src={devUrl}
                    sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-downloads" />
                </div>)}
              {panel === 'preview' && !showDev && (preview
                ? <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                      <div className="row muted" style={{ padding: '3px 12px', fontSize: 12, gap: 8 }}>
                        <span>{htmlFile.path} · updates as you type</span>
                        <button className="btn small" onClick={() => setPreviewKey((k) => k + 1)}>↻ Reload</button></div>
                      <iframe ref={frameRef} key={previewKey} title="HTML preview" sandbox="allow-scripts allow-forms allow-modals" srcDoc={preview} />
                    </div>
                    <div className="body" data-testid="preview-console" style={{ flex: 'none', width: '34%', borderLeft: '1px solid var(--line)' }}>
                      <b>Console</b>{'\n'}
                      {consoleLines.length === 0 && <span className="muted">console.log output and JavaScript errors of the page appear here.</span>}
                      {consoleLines.map((l, i) => <div key={i} style={{ color: l.level === 'error' ? '#ff8f9b' : l.level === 'warn' ? '#e3b04b' : undefined }}>{l.text}</div>)}
                    </div>
                  </div>
                : <div className="body">Open an .html file (or add index.html) to preview it. The preview runs in a sandboxed frame in your browser.</div>)}
            </div>
          </>)}
        </div>

        {aiOpen && (<>
          <Splitter vertical label="Resize AI panel" onDrag={dragAi} />
          <div className="ai-wrap" style={{ width: aiW }}>
            <AIPanel ws={ws} files={files} active={active} readOnly={readOnly} editorApi={editorApi} monaco={monacoApi}
              runOutput={aiRunOutput} getTerminal={() => termText.current} onSendToTerminal={sendToTerminal}
              onCreateFile={aiCreateFile} onApplied={aiApplied} beforeApply={() => saveAll(false)} onClose={() => setAiOpen(false)} />
          </div>
        </>)}
      </div>

      <div className="ide-status" role="status">
        <button type="button" onClick={() => showPanel('problems')} title="Problems">⊗ {errorCount} ⚠ {problems.length - errorCount}</button>
        <span>{files.length} files{usage ? ` · ${mb(files.reduce((a, f) => a + (f.content || '').length, 0))} of ${mb(usage.max_bytes)} MB` : ''}</span>
        <span>{langs.runner.available ? 'Runner: ready' : 'Runner: not available'}</span>
        <span style={{ flex: 1 }} />
        {!bottomOpen && <button type="button" onClick={() => setBottomOpen(true)}>Show panel</button>}
        {active && <span>Ln {cursor.line}, Col {cursor.column}</span>}
        {active && <span>{activeLang?.name || 'Plain text'}</span>}
        <span>{readOnly ? 'Read-only' : unsaved ? 'Unsaved changes' : 'Saved'}</span>
      </div>

      {palette === 'files' && <Palette title="Go to file" placeholder="Type a file name" onClose={() => setPalette(null)}
        items={files.map((f) => ({ key: f.id, label: f.path, run: () => openFile(f.id) }))} />}
      {palette === 'commands' && <Palette title="Command palette" placeholder="Type a command" onClose={() => setPalette(null)} items={commands} />}
      {modal?.type === 'wizard' && <ProjectWizard workspaceId={ws.id} onClose={() => setModal(null)} onDone={onTemplate} />}
      {modal?.type === 'new' && <NewFileModal langs={langs.languages} folder={modal.folder} onClose={() => setModal(null)} onSubmit={createFile} />}
      {modal?.type === 'newFolder' && <PromptModal title="New folder" label="Folder path" initial={modal.folder ? `${modal.folder}/` : ''}
        hint="A .gitkeep file is created inside so the empty folder is saved." onClose={() => setModal(null)} onSubmit={(v) => createFile(`${v.replace(/\/+$/, '')}/.gitkeep`)} />}
      {modal?.type === 'rename' && <PromptModal title={`Rename / move ${modal.node.id ? 'file' : 'folder'}`} label="New path" initial={modal.node.path}
        hint="Change the folder part of the path to move it." onClose={() => setModal(null)} onSubmit={(v) => (v === modal.node.path ? setModal(null) : movePath(modal.node.path, v))} />}
      {modal?.type === 'copy' && <PromptModal title={`Duplicate ${modal.node.id ? 'file' : 'folder'}`} label="Path of the copy"
        initial={modal.node.id ? `${parentOf(modal.node.path) ? `${parentOf(modal.node.path)}/` : ''}${baseOf(modal.node.path).replace(/(\.[^.]+)?$/, ' copy$1')}` : `${modal.node.path} copy`}
        onClose={() => setModal(null)} onSubmit={(v) => copyPath(modal.node.path, v)} />}
      {modal?.type === 'delete' && <ConfirmModal danger title="Delete file" confirmLabel="Delete" text={`Delete ${modal.file.path}? Its saved versions stay on the server.`} onClose={() => setModal(null)} onConfirm={() => deleteFile(modal.file)} />}
      {modal?.type === 'deleteFolder' && <ConfirmModal danger title="Delete folder" confirmLabel="Delete folder"
        text={`Delete the folder ${modal.node.path} and the ${files.filter((f) => f.path.startsWith(`${modal.node.path}/`)).length} file(s) inside it? Saved versions stay on the server.`}
        onClose={() => setModal(null)} onConfirm={() => deleteFolder(modal.node.path)} />}
      {modal?.type === 'submit' && (
        <Modal title="Submit for review" onClose={() => setModal(null)}>
          <p>All files are saved and frozen as a new version. The project is locked until the reviewer responds.</p>
          <Field label="Note for the reviewer (optional)"><textarea value={note} onChange={(e) => setNote(e.target.value)} aria-label="Submission note" maxLength={2000} /></Field>
          <div className="modal-foot"><button className="btn" onClick={() => setModal(null)}>Cancel</button>
            <button className="btn primary" onClick={submit}>Submit</button></div>
        </Modal>)}
      {versions && (
        <Modal title={`Saved versions · ${active.path}`} onClose={() => setVersions(null)} wide>
          {versions.length === 0 && <p className="muted">No versions.</p>}
          <table><thead><tr><th>Version</th><th>Saved</th><th>Type</th><th>Size</th><th /></tr></thead><tbody>{versions.map((v) => (
            <tr key={v.id}><td>v{v.version_no}</td><td>{fmtDateTime(v.created_at)}</td><td>{v.kind}</td><td>{v.size} chars</td>
              <td style={{ textAlign: 'right' }}><button className="btn small" disabled={readOnly || v.content === active.content} onClick={() => restore(v)}>
                {v.content === active.content ? 'Current' : 'Restore'}</button></td></tr>))}</tbody></table>
        </Modal>)}
    </div>
  );
}

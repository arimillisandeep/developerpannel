import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { isRisky, isShell, parseBlocks, proposedFiles, streamChat } from '../../services/ai';
import { copyText } from '../../services/copyGuard';
import Markdown from '../../components/Markdown';
import { DiffText } from '../../components/DiffView';
import { ConfirmModal, ErrorBox, Modal, PromptModal } from '../../components/ui';
import { fmtDateTime } from '../../utils/format';

const MONACO_LANG = { js: 'javascript', jsx: 'javascript', mjs: 'javascript', ts: 'typescript', tsx: 'typescript', py: 'python', sh: 'shell', bash: 'shell',
  zsh: 'shell', console: 'shell', yml: 'yaml', 'c#': 'csharp', cs: 'csharp', rb: 'ruby', kt: 'kotlin', rs: 'rust', golang: 'go', md: 'markdown', vue: 'html',
  ps1: 'powershell', dockerfile: 'dockerfile', 'c++': 'cpp' };
const QUICK = [
  { id: 'explain', label: 'Explain selected code', needs: 'selection', ctx: { selection: true, file: true }, prompt: 'Explain the selected code step by step: what it does, and anything risky or wrong in it.' },
  { id: 'fix', label: 'Fix selected code', needs: 'selection', ctx: { selection: true, file: true }, prompt: 'Find and fix the problems in the selected code. Explain the cause briefly, then give the corrected file as one complete path= block.' },
  { id: 'review', label: 'Review current file', needs: 'file', ctx: { file: true }, prompt: 'Review the current open file: bugs, edge cases, security, readability. List findings by importance, then give an improved complete file as a path= block if changes are needed.' },
  { id: 'project', label: 'Analyze project', ctx: { project: true, tree: true }, prompt: 'Analyze this project: what it does, how the files fit together, problems you see, and what is missing. Be specific about file names.' },
  { id: 'terminal', label: 'Fix terminal error', needs: 'error', ctx: { terminal: true, run: true, file: true, tree: true }, prompt: 'Explain the error in the terminal / run output in simple words, find its cause in my code and fix it. Give changed files as complete path= blocks and any command I should run.' },
  { id: 'tests', label: 'Generate tests', needs: 'file', ctx: { file: true, tree: true }, prompt: 'Write test cases for the current open file, in the usual test framework of this language. Put them in a new test file as a complete path= block and tell me the command to run them.' },
];
const CTX_LABEL = { file: 'Current file', selection: 'Selected code', tree: 'Folder structure', project: 'Whole project', terminal: 'Terminal output', run: 'Run / build output' };

function Code({ block, monaco, actions, readOnly, hasEditor }) {
  const [html, setHtml] = useState(null);
  const [copied, setCopied] = useState(false);
  const lang = MONACO_LANG[block.lang] || block.lang || 'plaintext';
  useEffect(() => {
    let live = true;
    setHtml(null);
    if (monaco?.editor?.colorize && block.closed && block.code.length < 60000) {
      monaco.editor.colorize(block.code, lang, { tabSize: 2 }).then((h) => { if (live) setHtml(h); }).catch(() => {});
    }
    return () => { live = false; };
  }, [monaco, block.code, block.closed, lang]);
  const copy = async () => { if (await copyText(block.code)) { setCopied(true); setTimeout(() => setCopied(false), 1500); } };
  const shell = isShell(block.lang);
  return (
    <div className="ai-code">
      <div className="ai-code-head">
        <span className="ai-code-name" title={block.path || block.lang}>{block.path || block.lang || 'code'}</span>
        <button type="button" onClick={copy}>{copied ? 'Copied ✓' : 'Copy code'}</button>
      </div>
      {html ? <pre className="ai-pre" dangerouslySetInnerHTML={{ __html: html }} /> : <pre className="ai-pre">{block.code}</pre>}
      {block.closed && (
        <div className="ai-code-acts">
          {block.path && <button type="button" className="strong" onClick={() => actions.preview([{ path: block.path, content: block.code.endsWith('\n') ? block.code : `${block.code}\n` }])}>Preview changes</button>}
          {shell && <button type="button" className="strong" onClick={() => actions.terminal(block.code)}>Send to terminal</button>}
          {!shell && <>
            <button type="button" disabled={readOnly || !hasEditor} onClick={() => actions.insert('cursor', block.code)}>Insert at cursor</button>
            <button type="button" disabled={readOnly || !hasEditor} onClick={() => actions.insert('replace', block.code)}>Replace selection</button>
            <button type="button" disabled={readOnly || !hasEditor} onClick={() => actions.insert('below', block.code)}>Insert below</button>
            <button type="button" disabled={readOnly} onClick={() => actions.newFile(block)}>Create new file</button>
          </>}
        </div>)}
    </div>
  );
}

/** Diff of every proposed file against the real project; the user ticks what to accept. Nothing is written before "Apply". */
function PatchModal({ wsId, changes, onApplied, onClose }) {
  const [data, setData] = useState(null);
  const [accept, setAccept] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.post('/ai/patch/preview', { workspace_id: wsId, changes }).then((r) => {
      setData(r.data);
      setAccept(Object.fromEntries(r.data.files.map((f) => [f.path, f.status !== 'unchanged'])));
    }).catch((e) => setError(errMsg(e)));
  }, [wsId, changes]);
  const chosen = data ? data.files.filter((f) => accept[f.path] && f.status !== 'unchanged') : [];
  const apply = async () => {
    setBusy(true);
    try {
      const paths = new Set(chosen.map((f) => f.path));
      const { data: res } = await api.post('/ai/patch/apply', { workspace_id: wsId, changes: changes.filter((c) => paths.has(c.path.replace(/^\.?\//, ''))) });
      onApplied(res);
      onClose();
    } catch (e) { setError(errMsg(e)); setBusy(false); }
  };
  return (
    <Modal title="Preview changes" onClose={onClose} wide>
      <ErrorBox error={error} />
      {!data && !error && <p className="muted">Comparing with your project…</p>}
      {data && (<>
        <p className="muted">Nothing is written until you press Apply. Untick a file to reject it. Every applied file gets a saved version you can restore from History.</p>
        {!data.can_apply && <div className="notice">{data.reason}</div>}
        {data.files.map((f) => (
          <details key={f.path} className="diff-file" open={data.files.length <= 3 && f.status !== 'unchanged'}>
            <summary>
              <input type="checkbox" aria-label={`Accept ${f.path}`} style={{ width: 'auto', marginRight: 8 }} checked={!!accept[f.path]} disabled={f.status === 'unchanged' || !data.can_apply}
                onClick={(e) => e.stopPropagation()} onChange={(e) => setAccept({ ...accept, [f.path]: e.target.checked })} />
              <span className={`badge ${f.status === 'new' ? 'green' : f.status === 'modified' ? 'amber' : ''}`}>{f.status === 'new' ? 'new file' : f.status}</span> <b>{f.path}</b>
              <span className="muted"> +{f.lines_added} −{f.lines_removed}</span>
            </summary>
            {f.status === 'unchanged' ? <p className="muted">Same as the file you already have.</p> : <DiffText diff={f.diff} />}
          </details>))}
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Reject all</button>
          <button className="btn primary" disabled={busy || !data.can_apply || chosen.length === 0} onClick={apply}>{busy ? 'Applying…' : `Apply ${chosen.length} file${chosen.length === 1 ? '' : 's'}`}</button>
        </div>
      </>)}
    </Modal>
  );
}

export default function AIPanel({ ws, files, active, readOnly, editorApi, monaco, runOutput, getTerminal, onSendToTerminal, onCreateFile, onApplied, beforeApply, onClose }) {
  const [status, setStatus] = useState(null);
  const [view, setView] = useState('chat');            // chat | history | saved
  const [conv, setConv] = useState(null);              // {id, title}
  const [messages, setMessages] = useState([]);
  const [list, setList] = useState(null);
  const [saved, setSaved] = useState(null);
  const [search, setSearch] = useState('');
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [ctx, setCtx] = useState({ file: true, selection: true, tree: false, project: false, terminal: false, run: false });
  const [extra, setExtra] = useState([]);              // more project files to send
  const [attached, setAttached] = useState([]);        // [{name, content}] from the user's computer
  const [showCtx, setShowCtx] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [patch, setPatch] = useState(null);
  const [ask, setAsk] = useState(null);                // {type:'rename'|'delete'|'clear'|'risky'|'newfile', ...}
  const streamId = useRef(null);
  const abort = useRef(null);
  const bodyRef = useRef(null);
  const fileRef = useRef(null);

  const loadStatus = useCallback(() => api.get('/ai/status').then((r) => {
    setStatus(r.data);
    setModel((m) => (r.data.models.some((x) => x.id === m) ? m : (r.data.models.find((x) => x.default) || r.data.models[0])?.id || ''));
  }).catch((e) => setError(errMsg(e))), []);
  useEffect(() => { loadStatus(); }, [loadStatus]);
  useEffect(() => { const el = bodyRef.current; if (el) el.scrollTop = el.scrollHeight; }, [messages, view]);
  useEffect(() => () => abort.current?.abort(), []);
  const flash = (t) => { setNote(t); setTimeout(() => setNote(''), 2500); };

  const loadList = useCallback((q) => api.get('/ai/conversations', { params: q ? { q } : {} }).then((r) => setList(r.data)).catch((e) => setError(errMsg(e))), []);
  useEffect(() => { if (view === 'history') { const t = setTimeout(() => loadList(search.trim()), search ? 250 : 0); return () => clearTimeout(t); } return undefined; }, [view, search, loadList]);
  useEffect(() => { if (view === 'saved') api.get('/ai/saved').then((r) => setSaved(r.data)).catch((e) => setError(errMsg(e))); }, [view]);

  const openConv = async (id) => {
    try { const { data } = await api.get(`/ai/conversations/${id}`); setConv({ id: data.id, title: data.title }); setMessages(data.messages); setView('chat'); setError(''); }
    catch (e) { setError(errMsg(e)); }
  };
  const newChat = () => { if (busy) return; setConv(null); setMessages([]); setView('chat'); setError(''); };

  const selection = () => editorApi.getSelection() || '';
  const terminalText = () => (getTerminal?.() || '').trim();
  const buildContext = (flags) => {
    const sel = flags.selection ? selection() : '';
    return {
      active_path: (flags.file || sel) && active ? active.path : null,
      active_content: flags.file && active ? active.content : null,
      selection: sel || null,
      files: extra.filter((p) => files.some((f) => f.path === p)),
      tree: !!flags.tree, project: !!flags.project,
      terminal: flags.terminal ? terminalText() || null : null,
      run_output: flags.run ? runOutput || null : null,
      attachments: attached,
    };
  };

  const run = async (path, body, optimistic) => {
    setBusy(true); setError('');
    const tempId = `t${Date.now()}`;
    setMessages((m) => [...m, ...optimistic, { id: tempId, role: 'assistant', content: '', status: 'streaming' }]);
    const patchLast = (fn) => setMessages((m) => m.map((x) => (x.id === tempId || x.id === streamId.current ? fn(x) : x)));
    abort.current = new AbortController();
    try {
      await streamChat(path, body, (ev) => {
        if (ev.type === 'start') {
          streamId.current = ev.message_id;
          setConv((c) => (c ? { ...c, title: ev.title } : c));
          setMessages((m) => m.map((x) => (x.id === tempId ? { ...x, id: ev.message_id, model: ev.model }
            : typeof x.id === 'string' && x.role === 'user' ? { ...x, id: ev.user_message_id, context: ev.context } : x)));
        } else if (ev.type === 'delta') patchLast((x) => ({ ...x, content: x.content + ev.text }));
        else if (ev.type === 'done') patchLast(() => ev.message);
        else if (ev.type === 'error') { patchLast((x) => ({ ...(ev.message_obj || x), status: 'error', error: ev.message })); }
      }, abort.current.signal);
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== tempId));
      setError(e.message || 'The request failed.');
    } finally {
      setMessages((m) => m.map((x) => (x.status === 'streaming' ? { ...x, status: 'stopped' } : x)));
      streamId.current = null; abort.current = null; setBusy(false); loadStatus();
    }
  };

  const send = async (text, flags = ctx) => {
    const content = (text ?? input).trim();
    if (!content || busy) return;
    let c = conv;
    try {
      if (!c) { const { data } = await api.post('/ai/conversations', ws ? { workspace_id: ws.id } : {}); c = { id: data.id, title: data.title }; setConv(c); }
    } catch (e) { setError(errMsg(e)); return; }
    if (text == null) setInput('');
    const context = buildContext(flags);
    setAttached([]);
    await run(`/ai/conversations/${c.id}/messages`, { content, model: model || null, workspace_id: ws?.id ?? null, context },
      [{ id: `u${Date.now()}`, role: 'user', content }]);
  };
  const regenerate = async () => {
    if (!conv || busy) return;
    setMessages((m) => { const i = m.map((x) => x.role).lastIndexOf('user'); return i < 0 ? m : m.slice(0, i + 1); });
    await run(`/ai/conversations/${conv.id}/regenerate`, { model: model || null }, []);
  };
  const stop = () => {
    if (streamId.current) api.post(`/ai/messages/${streamId.current}/stop`).catch(() => abort.current?.abort());
    else abort.current?.abort();
  };
  const quick = (q) => {
    if (q.needs === 'selection' && !selection().trim()) { setError('Select some code in the editor first.'); return; }
    if (q.needs === 'file' && !active) { setError('Open a file in the editor first.'); return; }
    if (q.needs === 'error' && !terminalText() && !runOutput) { setError('There is no terminal or run output yet. Run the program first, then ask again.'); return; }
    send(q.prompt, q.ctx);
  };

  const actions = useMemo(() => ({
    insert: (mode, code) => { const r = editorApi.insert(mode, code); if (r === true) flash(mode === 'replace' ? 'Selection replaced' : 'Code inserted'); else setError(r); },
    newFile: (block) => setAsk({ type: 'newfile', code: block.code, initial: block.path || '' }),
    preview: async (changes) => { if (!ws) { setError('Open a task workspace to apply changes.'); return; } await beforeApply?.(); setPatch(changes); },
    terminal: (code) => {
      const cmds = code.split('\n').map((l) => l.replace(/^\s*[$>]\s?/, '').trim()).filter((l) => l && !l.startsWith('#'));
      if (!cmds.length) return;
      if (cmds.some(isRisky)) setAsk({ type: 'risky', cmds }); else { onSendToTerminal(cmds); flash('Command placed in the terminal. Press Enter there to run it.'); }
    },
  }), [editorApi, ws, beforeApply, onSendToTerminal]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleSaved = async (m) => {
    try { const { data } = await api.patch(`/ai/messages/${m.id}`, { saved: !m.saved }); setMessages((all) => all.map((x) => (x.id === m.id ? { ...x, saved: data.saved } : x))); }
    catch (e) { setError(errMsg(e)); }
  };
  const attach = (e) => {
    const picked = [...e.target.files]; e.target.value = '';
    picked.slice(0, 5 - attached.length).forEach((f) => {
      if (f.size > 150000) { setError(`${f.name} is too large to attach (limit 150 KB of text).`); return; }
      const r = new FileReader();
      r.onload = () => { const content = String(r.result); if (content.includes('\u0000')) setError(`${f.name} is not a text file.`); else setAttached((a) => [...a, { name: f.name, content }]); };
      r.readAsText(f);
    });
  };
  const confirmAsk = async (value) => {
    const a = ask; setAsk(null);
    try {
      if (a.type === 'rename') { await api.patch(`/ai/conversations/${a.id}`, { title: value }); if (conv?.id === a.id) setConv({ ...conv, title: value }); loadList(search.trim()); }
      else if (a.type === 'delete') { await api.delete(`/ai/conversations/${a.id}`); if (conv?.id === a.id) { setConv(null); setMessages([]); } loadList(search.trim()); }
      else if (a.type === 'clear') { await api.post(`/ai/conversations/${conv.id}/clear`); setMessages([]); }
      else if (a.type === 'risky') { onSendToTerminal(a.cmds); flash('Command placed in the terminal. Check it, then press Enter to run it.'); }
      else if (a.type === 'newfile') { const r = await onCreateFile(value, a.code); if (r === true) flash(`Created ${value}`); else setError(r); }
    } catch (e) { setError(errMsg(e)); }
  };

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
  const ctxOn = Object.keys(CTX_LABEL).filter((k) => ctx[k]).length + extra.length + attached.length;
  const left = status && status.daily_limit ? Math.max(0, status.daily_limit - status.used_today) : null;

  return (
    <aside className="ai-panel" aria-label="AI Assistant">
      <div className="ai-head">
        <b>✦ AI Assistant</b>
        <select aria-label="AI model" value={model} onChange={(e) => setModel(e.target.value)} disabled={!status?.models.length || busy} title="Model">
          {!status?.models.length && <option value="">No model</option>}
          {status?.models.map((m) => <option key={m.id} value={m.id}>{m.model}{status.models.some((x) => x.model === m.model && x.id !== m.id) ? ` (${m.provider})` : ''}</option>)}
        </select>
        <span style={{ flex: 1 }} />
        <button type="button" title="New chat" aria-label="New chat" onClick={newChat} disabled={busy}>＋</button>
        <button type="button" title="Chat history" aria-label="Chat history" className={view === 'history' ? 'on' : ''} onClick={() => setView(view === 'history' ? 'chat' : 'history')}>🕘</button>
        <button type="button" title="Saved answers" aria-label="Saved answers" className={view === 'saved' ? 'on' : ''} onClick={() => setView(view === 'saved' ? 'chat' : 'saved')}>★</button>
        <button type="button" title="Close AI panel" aria-label="Close AI panel" onClick={onClose}>✕</button>
      </div>

      {error && <div className="ai-error" role="alert">{error}<button type="button" aria-label="Dismiss" onClick={() => setError('')}>✕</button></div>}
      {note && <div className="ai-note" role="status">{note}</div>}

      {view === 'history' && (
        <div className="ai-body">
          <input aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={(e) => setSearch(e.target.value)} />
          {list && list.length === 0 && <p className="muted">{search ? 'No conversation matches.' : 'No conversations yet.'}</p>}
          {list && list.map((c) => (
            <div key={c.id} className={`ai-conv ${conv?.id === c.id ? 'on' : ''}`}>
              <button type="button" className="ai-conv-open" onClick={() => openConv(c.id)}><b>{c.title}</b>
                <span className="muted">{c.task_code ? `${c.task_code} · ` : ''}{fmtDateTime(c.updated_at)}</span></button>
              <button type="button" title="Rename" aria-label={`Rename ${c.title}`} onClick={() => setAsk({ type: 'rename', id: c.id, initial: c.title })}>✎</button>
              <button type="button" title="Delete" aria-label={`Delete ${c.title}`} onClick={() => setAsk({ type: 'delete', id: c.id, title: c.title })}>🗑</button>
            </div>))}
        </div>)}

      {view === 'saved' && (
        <div className="ai-body">
          {saved && saved.length === 0 && <p className="muted">Nothing saved yet. Press ☆ under an answer to keep it here.</p>}
          {saved && saved.map((m) => (
            <div key={m.id} className="ai-msg assistant">
              <div className="muted" style={{ marginBottom: 4 }}>{m.conversation} · {fmtDateTime(m.created_at)} <button type="button" className="ai-link" onClick={() => openConv(m.conversation_id)}>Open chat</button></div>
              {parseBlocks(m.content).map((b, i) => (b.type === 'text' ? <Markdown key={i} text={b.text} />
                : <Code key={i} block={b} monaco={monaco} actions={actions} readOnly={readOnly} hasEditor={!!active} />))}
            </div>))}
        </div>)}

      {view === 'chat' && (<>
        <div className="ai-body" ref={bodyRef}>
          {status && !status.can_use && <div className="notice">{status.reason}</div>}
          {messages.length === 0 && (
            <div className="ai-empty">
              <p><b>Ask about your code</b></p>
              <p className="muted">The assistant sees what you tick under “Context” — by default the open file and your selection. Code it writes can go straight into the editor.</p>
              <div className="ai-quick">{QUICK.map((q) => <button type="button" key={q.id} disabled={busy || !status?.can_use} onClick={() => quick(q)}>{q.label}</button>)}</div>
            </div>)}
          {messages.map((m) => (
            <div key={m.id} className={`ai-msg ${m.role}`}>
              {m.role === 'user' ? (<>
                <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
                {m.context?.length > 0 && <div className="ai-ctx-sent" title="What was sent with this question">📎 {m.context.filter((c) => !c.skipped).map((c) => (c.path || CTX_LABEL[c.kind] || c.kind) + (c.truncated ? ' (cut)' : '')).join(' · ')}</div>}
              </>) : (<>
                {parseBlocks(m.content).map((b, i) => (b.type === 'text' ? <Markdown key={i} text={b.text} />
                  : <Code key={i} block={b} monaco={monaco} actions={actions} readOnly={readOnly} hasEditor={!!active} />))}
                {m.status === 'streaming' && <div className="ai-typing" role="status" aria-label="AI is writing"><span /><span /><span /></div>}
                {m.status === 'stopped' && <div className="muted">Stopped.</div>}
                {m.status === 'error' && <div className="ai-fail">{m.error || 'The answer failed.'}</div>}
                {m.status !== 'streaming' && (
                  <div className="ai-msg-acts">
                    {m.content && <button type="button" onClick={async () => { if (await copyText(m.content)) flash('Response copied'); }}>Copy response</button>}
                    {m.content && typeof m.id === 'number' && <button type="button" aria-pressed={!!m.saved} onClick={() => toggleSaved(m)}>{m.saved ? '★ Saved' : '☆ Save'}</button>}
                    {m === lastAssistant && <button type="button" disabled={busy || !status?.can_use} onClick={regenerate}>↻ Regenerate</button>}
                    {proposedFiles(m.content).length > 1 && <button type="button" className="strong" onClick={() => actions.preview(proposedFiles(m.content))}>Preview all {proposedFiles(m.content).length} files</button>}
                  </div>)}
              </>)}
            </div>))}
        </div>

        {messages.length > 0 && <div className="ai-quick slim">{QUICK.map((q) => <button type="button" key={q.id} disabled={busy || !status?.can_use} onClick={() => quick(q)}>{q.label}</button>)}</div>}

        <div className="ai-foot">
          {showCtx && (
            <div className="ai-ctx" role="group" aria-label="Context">
              {Object.entries(CTX_LABEL).map(([k, l]) => (
                <label key={k}><input type="checkbox" checked={!!ctx[k]} onChange={(e) => setCtx({ ...ctx, [k]: e.target.checked })} />{l}{k === 'file' && active ? `: ${active.path}` : ''}</label>))}
              <label style={{ flexBasis: '100%' }}>More files
                <select multiple aria-label="More files" value={extra} onChange={(e) => setExtra([...e.target.selectedOptions].map((o) => o.value))} size={Math.min(5, Math.max(2, files.length))}>
                  {files.filter((f) => f.path !== active?.path).map((f) => <option key={f.id} value={f.path}>{f.path}</option>)}</select></label>
              <small className="muted">Only what is ticked here is sent to the AI service. Ctrl+click to choose several files.</small>
            </div>)}
          {attached.length > 0 && <div className="ai-chips">{attached.map((a) => <span key={a.name}>{a.name}<button type="button" aria-label={`Remove ${a.name}`} onClick={() => setAttached(attached.filter((x) => x !== a))}>✕</button></span>)}</div>}
          <textarea aria-label="Message to AI" placeholder={status?.can_use === false ? 'AI is not available' : 'Ask anything about your code… (Enter to send, Shift+Enter for a new line)'}
            value={input} disabled={status?.can_use === false} onChange={(e) => setInput(e.target.value)} rows={3}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} />
          <div className="ai-foot-row">
            <input ref={fileRef} type="file" multiple hidden aria-label="Attach text files" onChange={attach} />
            <button type="button" title="Attach a text file from your computer" aria-label="Attach file" onClick={() => fileRef.current.click()}>📎</button>
            <button type="button" aria-expanded={showCtx} onClick={() => setShowCtx(!showCtx)}>Context ({ctxOn})</button>
            {messages.length > 0 && <button type="button" disabled={busy} onClick={() => setAsk({ type: 'clear' })}>Clear</button>}
            <span style={{ flex: 1 }} />
            {left != null && <span className="muted" title="AI messages left today">{left} left</span>}
            {busy ? <button type="button" className="stop" onClick={stop}>■ Stop</button>
              : <button type="button" className="send" disabled={!input.trim() || status?.can_use === false} onClick={() => send()}>Send ➤</button>}
          </div>
        </div>
      </>)}

      {patch && <PatchModal wsId={ws.id} changes={patch} onClose={() => setPatch(null)}
        onApplied={(res) => { onApplied(res); flash(res.applied.length ? `Applied ${res.applied.length} file(s) and saved` : 'Nothing to change'); }} />}
      {ask?.type === 'rename' && <PromptModal title="Rename conversation" label="Title" initial={ask.initial} onClose={() => setAsk(null)} onSubmit={confirmAsk} />}
      {ask?.type === 'newfile' && <PromptModal title="Create new file" label="File path" initial={ask.initial} hint="Example: src/utils/date.js" onClose={() => setAsk(null)} onSubmit={confirmAsk} />}
      {ask?.type === 'delete' && <ConfirmModal danger title="Delete conversation" confirmLabel="Delete" text={`Delete “${ask.title}”? Its messages are removed for good.`} onClose={() => setAsk(null)} onConfirm={() => confirmAsk()} />}
      {ask?.type === 'clear' && <ConfirmModal danger title="Clear conversation" confirmLabel="Clear" text="Remove all messages of this chat? This cannot be undone." onClose={() => setAsk(null)} onConfirm={() => confirmAsk()} />}
      {ask?.type === 'risky' && <ConfirmModal danger title="This command can delete or overwrite data" confirmLabel="Put it in the terminal anyway" onClose={() => setAsk(null)} onConfirm={() => confirmAsk()}
        text={`${ask.cmds.join('  ⏎  ')} — it is only placed in the terminal input. It runs when you press Enter there.`} />}
    </aside>
  );
}

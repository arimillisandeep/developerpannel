import { useCallback, useEffect, useRef, useState } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { wsUrl } from '../../services/api';

/** Real interactive terminal (same engine as the VS Code terminal: xterm.js).
 *  Keys go straight to a shell inside an isolated Docker container on the server, so line editing,
 *  Tab completion, Ctrl+C, arrow keys, colours and full-screen programs work.
 *  The shell works in the project folder: files it creates, changes or deletes appear in the editor
 *  (onFilesChanged), and files saved in the editor appear in the shell within about two seconds. */
const THEME = { background: '#0b1020', foreground: '#d6deeb', cursor: '#6fd08c', selectionBackground: '#33467c',
  black: '#1b2233', brightBlack: '#5c6a85' };
const plain = (s) => s.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(\x07|\x1b\\)|\x1b[=>]|\r/g, '');   // eslint-disable-line no-control-regex

const SERVER_URL = /https?:\/\/(?:localhost|\[::1?\]|\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})/g;

/** One terminal. Several can be open for a workspace (see TerminalTabs): on the server they are shells in the same
 *  container, so they share the files, the installed packages and localhost.
 *  lockLang: environment of the terminals already open (a container has one image); autoStart: connect when mounted;
 *  probePort: while set, the server is asked every few seconds what listens in the container (onListening). */
export default function Terminal({ workspaceId, langs, runner, defaultLang, textRef, inject, onFilesChanged, onPorts, onServer,
  lockLang = '', autoStart = false, active = true, probePort = '', onListening, onState }) {
  const runnable = langs.filter((l) => l.kind === 'run');
  const [lang, setLang] = useState('');
  const [state, setState] = useState('closed');   // closed | connecting | open
  const [ready, setReady] = useState(false);      // the shell has answered: 'connected' would be a lie before that
  const [pending, setPending] = useState([]);     // commands suggested by the AI assistant, waiting for the user
  const sock = useRef(null);
  const stateRef = useRef('closed');              // the current state, readable from callbacks
  useEffect(() => { stateRef.current = state; }, [state]);
  const ended = useRef(false);                    // the server already said how the shell ended
  const attempts = useRef(0);                     // automatic reconnects since the user last pressed New terminal
  const term = useRef(null);
  const fit = useRef(null);
  const holder = useRef(null);
  const text = useRef('');
  const filesChanged = useRef(onFilesChanged);
  filesChanged.current = onFilesChanged;
  const ports = useRef(null);                     // {container port: port on this computer}, sent by the server
  const hinted = useRef(false);
  const portCbs = useRef({});
  portCbs.current = { onPorts, onServer, onListening, onState };
  const chosen = lockLang || lang || defaultLang || 'python';

  const write = useCallback((s) => {
    term.current?.write(s);
    text.current = (text.current + plain(s)).slice(-60000);
    if (textRef) textRef.current = text.current;   // lets the AI assistant read the recent output when the user asks
  }, [textRef]);
  /** A program in the shell printed its address (http://localhost:5173/): offer it in the Preview tab. */
  const lookForServer = useCallback((chunk) => {
    if (!ports.current) return;
    const tail = text.current.slice(-(plain(chunk).length + 200));     // an address can be split over two chunks
    let last = null;
    for (const m of tail.matchAll(SERVER_URL)) if (ports.current[m[1]]) last = m[1];
    if (last) portCbs.current.onServer?.(last);
    if (!hinted.current && /use --host to expose/.test(tail)) {
      hinted.current = true;
      term.current?.write('\r\n\x1b[33m[workspace] To see this app in the Preview tab, stop it (Ctrl+C) and start it with:  npm run dev -- --host 0.0.0.0\x1b[0m\r\n');
    }
  }, []);
  const send = (message) => { if (sock.current?.readyState === 1 || sock.current?.ready) sock.current.send(JSON.stringify(message)); };
  const refit = useCallback(() => { try { fit.current?.fit(); } catch { /* panel hidden */ } }, []);

  useEffect(() => {
    const t = new XTerm({ cursorBlink: true, convertEol: false, fontSize: 13, scrollback: 5000, theme: THEME,
      fontFamily: 'ui-monospace, "Cascadia Code", Consolas, "Courier New", monospace' });
    const f = new FitAddon();
    t.loadAddon(f);
    t.open(holder.current);
    term.current = t; fit.current = f;
    refit();
    if (!autoStart) t.write('No shell yet. Press \x1b[1mNew terminal\x1b[0m to start one in an isolated container.\r\n');
    const onData = t.onData((data) => send({ type: 'input', data }));
    const onResize = t.onResize(({ cols, rows }) => send({ type: 'resize', cols, rows }));
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(refit);
    ro?.observe(holder.current);
    window.addEventListener('resize', refit);
    return () => { onData.dispose(); onResize.dispose(); ro?.disconnect(); window.removeEventListener('resize', refit);
      sock.current?.close(); sock.current = null; t.dispose(); };
  }, [refit]);

  // a suggested command is only typed into the shell; it runs when the user presses Enter
  useEffect(() => { if (inject?.cmds?.length) setPending(inject.cmds); }, [inject]);
  const insertSuggested = () => {
    if (state !== 'open' || !pending.length) return;
    send({ type: 'input', data: pending[0] });
    setPending((p) => p.slice(1));
    term.current?.focus();
  };

  const open = (manual = false) => {
    if (stateRef.current !== 'closed') return;
    if (manual) attempts.current = 0;              // a click on New terminal starts counting again
    setState('connecting');
    const t = term.current;
    t.reset(); text.current = '';
    ended.current = false; setReady(false);
    refit();
    const url = wsUrl('/ws/terminal', { workspace_id: workspaceId, language: chosen,
      cols: t.cols || 80, rows: t.rows || 24 });
    const ws = new WebSocket(url);
    sock.current = ws;
    // Every handler first checks that this socket is still the current one. React calls mount effects twice in
    // development (StrictMode), so a socket from the first mount closes *after* the second mount opened its own;
    // without this guard that late onclose emptied sock.current and every key typed afterwards was thrown away -
    // the terminal looked connected and did nothing.
    const current = () => sock.current === ws;
    let gotAnything = false;
    ws.onopen = () => { if (!current()) return; ws.ready = true; setState('open'); t.focus(); };
    ws.onmessage = (e) => {
      if (!current()) return;
      gotAnything = true;
      const m = JSON.parse(e.data);
      if (m.type === 'output') { setReady(true); write(m.data); lookForServer(m.data); }
      else if (m.type === 'listening') portCbs.current.onListening?.(m);
      else if (m.type === 'ports') { ports.current = m.ports; portCbs.current.onPorts?.(m.ports); }
      else if (m.type === 'files') filesChanged.current?.();
      else if (m.type === 'note') write(`\r\n\x1b[33m[workspace] ${m.message}\x1b[0m\r\n`);
      else if (m.type === 'error') write(`\r\n\x1b[31m[not available] ${m.message}\x1b[0m\r\n`);
      else if (m.type === 'exit') { ended.current = true; write(`\r\n\x1b[90m[shell ended${m.code == null ? '' : ` with code ${m.code}`}]\x1b[0m\r\n`); }
    };
    ws.onclose = (e) => {
      if (!current()) return;                     // a socket of an earlier mount: it says nothing about this one
      const code = e && e.code, why = (e && e.reason ? String(e.reason).trim() : '');
      const said = code ? ` (code ${code}${why ? `: ${why}` : ''})` : '';
      if (!gotAnything && attempts.current < 2) {      // a dropped upgrade (proxy, network): try again quietly
        attempts.current += 1;
        sock.current = null;
        write(`\r\n\x1b[90m[connection lost before the shell answered${said}, retrying…]\x1b[0m\r\n`);
        stateRef.current = 'closed';            // the state setter alone is not visible to this closure yet
        setState('closed');
        setTimeout(() => { t.reset(); text.current = ''; open(); }, 700);
        return;
      }
      if (!gotAnything) write(`\r\n\x1b[90m[the terminal service did not answer${said}. Press New terminal to try again]\x1b[0m\r\n`);
      else if (!ended.current) write(`\r\n\x1b[90m[connection closed${said}]\x1b[0m\r\n`);
      sock.current = null; setReady(false); setState('closed');
      ports.current = null; hinted.current = false; portCbs.current.onPorts?.(null);
      if (gotAnything) setTimeout(() => filesChanged.current?.(), 1500);   // the server saves the shell's last changes while closing
    };
    ws.onerror = () => { if (current()) write('\r\n\x1b[31m[could not connect to the terminal service]\x1b[0m\r\n'); };
  };
  const close = () => sock.current?.close();
  useEffect(() => { if (autoStart) open(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  // A tab that becomes the visible one gets the keyboard. Without this the click stays on the tab button, keys go
  // nowhere and the terminal looks dead even though the shell behind it is running.
  useEffect(() => { if (active) term.current?.focus(); }, [active]);
  useEffect(() => { portCbs.current.onState?.(state, chosen); }, [state, chosen]);
  useEffect(() => {
    if (state !== 'open' || !probePort) return undefined;
    const ask = () => send({ type: 'probe', port: probePort });
    ask();
    const timer = setInterval(ask, 3000);
    return () => clearInterval(timer);
  }, [state, probePort]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="row" style={{ padding: '6px 14px', gap: 8, borderBottom: '1px solid var(--line)' }}>
        <select aria-label="Terminal environment" value={chosen} disabled={state !== 'closed' || Boolean(lockLang)} onChange={(e) => setLang(e.target.value)} style={{ width: 200, padding: '4px 8px' }}>
          {runnable.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        {state === 'closed'
          ? <button className="btn small primary" onClick={() => open(true)}>＋ New terminal</button>
          : <button className="btn small danger" onClick={close}>Close terminal</button>}
        <button className="btn small" onClick={() => { term.current?.clear(); term.current?.focus(); }}>Clear</button>
        <span className="muted" style={{ fontSize: 12 }}>
          {state === 'open' ? (ready ? 'connected' : 'connected, waiting for the shell…')
            : state === 'connecting' ? 'starting…' : runner.available ? 'not started' : `not available: ${runner.reason}`}
        </span>
      </div>
      {pending.length > 0 && (
        <div className="row term-suggest" role="status">
          <span className="muted">Suggested command:</span>
          <code aria-label="Suggested command">{pending[0]}</code>
          <button type="button" className="btn small primary" disabled={state !== 'open'} onClick={insertSuggested}
            title={state === 'open' ? 'Types the command into the terminal. It runs when you press Enter.' : 'Start a terminal first'}>Put in terminal</button>
          {pending.length > 1 && <span className="muted">{pending.length - 1} more suggested</span>}
          <button type="button" className="btn small" onClick={() => setPending([])}>Skip</button>
        </div>
      )}
      <div className="term-holder" ref={holder} data-testid="terminal" aria-label="Terminal" onClick={() => term.current?.focus()} />
    </div>
  );
}

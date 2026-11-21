import { useCallback, useRef, useState } from 'react';
import Terminal from './Terminal';

const MAX = 4;   // same as TERMINAL_MAX_PER_USER on the server

/** Several terminals side by side as tabs, like the terminal list of VS Code.
 *  All of them work in the same container: start a server in one and run commands in another. */
export default function TerminalTabs({ onPorts, onServer, onListening, probePort, textRef, inject, ...rest }) {
  const [tabs, setTabs] = useState([{ id: 1, auto: false }]);
  const [active, setActive] = useState(1);
  const [info, setInfo] = useState({});            // tab id -> { state, lang }
  const nextId = useRef(2);
  const portsOf = useRef({});

  const live = tabs.filter((t) => info[t.id] && info[t.id].state !== 'closed');
  const sessionLang = live.length ? info[live[0].id].lang : '';
  const prober = tabs.find((t) => info[t.id]?.state === 'open')?.id;

  const add = () => {
    const id = nextId.current++;
    setTabs((list) => [...list, { id, auto: true }]);
    setActive(id);
  };
  const remove = (id) => {
    const rest2 = tabs.filter((t) => t.id !== id);
    setTabs(rest2);
    setInfo((old) => { const copy = { ...old }; delete copy[id]; return copy; });
    if (active === id) setActive(rest2[rest2.length - 1].id);
  };
  const setPorts = useCallback((id, map) => {
    if (map) portsOf.current[id] = map; else delete portsOf.current[id];
    onPorts?.(Object.values(portsOf.current)[0] || null);      // the ports stay while any terminal is open
  }, [onPorts]);
  const setState = useCallback((id, state, lang) => setInfo((old) => (
    old[id]?.state === state && old[id]?.lang === lang ? old : { ...old, [id]: { state, lang } })), []);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
      <div className="term-tabs" role="tablist" aria-label="Terminals">
        {tabs.map((t) => (
          <span key={t.id} className={`term-tab${t.id === active ? ' on' : ''}`}>
            <button type="button" role="tab" aria-selected={t.id === active} onClick={() => setActive(t.id)}>
              <span className={`dot${info[t.id]?.state === 'open' ? ' live' : ''}`} />Terminal {t.id}
            </button>
            {tabs.length > 1 && <button type="button" className="x" aria-label={`Remove terminal ${t.id}`} title="Close this terminal and remove the tab" onClick={() => remove(t.id)}>×</button>}
          </span>))}
        <button type="button" className="term-add" aria-label="Add terminal" disabled={tabs.length >= MAX}
          title={tabs.length >= MAX ? `At most ${MAX} terminals` : 'Open another terminal next to this one (same files, same container)'} onClick={add}>＋</button>
      </div>
      {tabs.map((t) => (
        <div key={t.id} style={{ flex: 1, minHeight: 0, display: t.id === active ? 'flex' : 'none' }}>
          <Terminal {...rest} autoStart={t.auto} active={t.id === active}
            lockLang={live.some((x) => x.id !== t.id) ? sessionLang : ''}
            textRef={t.id === active ? textRef : undefined} inject={t.id === active ? inject : undefined}
            probePort={t.id === prober ? probePort : ''} onListening={onListening} onServer={onServer}
            onPorts={(map) => setPorts(t.id, map)} onState={(state, lang) => setState(t.id, state, lang)} />
        </div>))}
    </div>
  );
}

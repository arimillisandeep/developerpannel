import { useCallback, useEffect, useRef, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, Field, Modal, PageHead } from '../../components/ui';
import { useAuth } from '../../context/AuthContext';
import { useNotifications } from '../../context/NotificationContext';
import { ROLE_LABEL, fmtDateTime } from '../../utils/format';

function GroupForm({ kind, contacts, onDone, onClose }) {
  const [title, setTitle] = useState('');
  const [picked, setPicked] = useState([]);
  const [error, setError] = useState('');
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const submit = async (e) => {
    e.preventDefault();
    try { onDone((await api.post('/chat/conversations', { kind, title, user_ids: picked })).data); } catch (err) { setError(errMsg(err)); }
  };
  return (
    <Modal title={kind === 'group' ? 'New group chat' : 'New announcement channel'} onClose={onClose}>
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Title"><input required value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        {kind === 'group'
          ? <Field label={`Members (${picked.length} selected, at least 2)`}><div className="tile" style={{ maxHeight: 200, overflow: 'auto' }}>{contacts.map((p) => (
              <label key={p.id} className="row" style={{ padding: '3px 0' }}><input type="checkbox" style={{ width: 'auto' }} checked={picked.includes(p.id)} onChange={() => toggle(p.id)} />
                {p.full_name} <span className="muted">({ROLE_LABEL[p.role]})</span></label>))}</div></Field>
          : <p className="muted">Everyone who is active now is added. Only admins can post.</p>}
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary">Create</button></div>
      </form>
    </Modal>
  );
}

export default function Chat() {
  const { user } = useAuth();
  const { chatEvent } = useNotifications();
  const [convs, setConvs] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [active, setActive] = useState(null);
  const [data, setData] = useState({ messages: [], read_by_all_up_to: 0 });
  const [text, setText] = useState('');
  const [modal, setModal] = useState(null);
  const [error, setError] = useState('');
  const endRef = useRef(null);
  const current = convs.find((c) => c.id === active);

  const loadConvs = useCallback(() => api.get('/chat/conversations').then((r) => setConvs(r.data)).catch((e) => setError(errMsg(e))), []);
  const loadMessages = useCallback((id) => api.get(`/chat/conversations/${id}/messages`).then((r) => setData(r.data)).catch((e) => setError(errMsg(e))), []);
  useEffect(() => { loadConvs(); api.get('/chat/contacts').then((r) => setContacts(r.data)).catch(() => {}); }, [loadConvs]);
  useEffect(() => { if (active) loadMessages(active).then(loadConvs); }, [active, loadMessages, loadConvs]);
  useEffect(() => {  // live message arrived
    if (!chatEvent) return;
    if (chatEvent.conversation_id === active) loadMessages(active).then(loadConvs); else loadConvs();
  }, [chatEvent]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // read receipts and missed events
    if (!active) return undefined;
    const t = setInterval(() => loadMessages(active), 20000);
    return () => clearInterval(t);
  }, [active, loadMessages]);
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: 'end' }); }, [data.messages.length, active]);

  const openDirect = async (id) => {
    if (!id) return;
    try { const { data: c } = await api.post('/chat/conversations', { kind: 'direct', user_ids: [Number(id)] }); await loadConvs(); setActive(c.id); }
    catch (e) { setError(errMsg(e)); }
  };
  const send = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    try { await api.post(`/chat/conversations/${active}/messages`, { body: text }); setText(''); await loadMessages(active); loadConvs(); }
    catch (err) { setError(errMsg(err)); }
  };
  const canGroup = ['admin', 'developer', 'onroll'].includes(user.role);

  return (
    <>
      <PageHead title="Chat" sub="Internal messages. Only the members of a conversation can read it.">
        {canGroup && <button className="btn" onClick={() => setModal('group')}>New group</button>}
        {user.role === 'admin' && <button className="btn" onClick={() => setModal('announcement')}>New announcement channel</button>}
      </PageHead>
      <ErrorBox error={error} />
      <div className="grid" style={{ gridTemplateColumns: '300px 1fr' }}>
        <div className="card" style={{ padding: 12, marginBottom: 0 }}>
          <select value="" onChange={(e) => openDirect(e.target.value)} aria-label="Start a chat" style={{ marginBottom: 10 }}>
            <option value="">Message someone…</option>
            {contacts.map((c) => <option key={c.id} value={c.id}>{c.full_name} ({ROLE_LABEL[c.role]})</option>)}
          </select>
          {convs.length === 0 && <div className="empty">No conversations yet.</div>}
          {convs.map((c) => (
            <div key={c.id} className="tile" onClick={() => setActive(c.id)}
              style={{ cursor: 'pointer', marginBottom: 6, borderColor: c.id === active ? '#27407a' : undefined, background: c.id === active ? '#13203d' : undefined }}>
              <div className="row spread"><b>{c.kind === 'announcement' ? '📢 ' : c.kind === 'group' ? '# ' : ''}{c.title}</b>
                {c.unread > 0 && <span className="badge blue">{c.unread}</span>}</div>
              <div className="muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>{c.last_message || 'No messages yet'}</div>
            </div>))}
        </div>
        <div className="card" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 250px)', minHeight: 360, marginBottom: 0 }}>
          {!current ? <div className="empty" style={{ margin: 'auto' }}>Choose a conversation, or message someone.</div> : (<>
            <div style={{ borderBottom: '1px solid var(--line)', paddingBottom: 10, marginBottom: 10 }}><b>{current.title}</b>
              <div className="muted" style={{ fontSize: 13 }}>{current.members.map((m) => m.full_name).join(', ')}</div></div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              {data.messages.length === 0 && <div className="empty">No messages yet.</div>}
              {data.messages.map((m) => {
                const mine = m.sender_id === user.id;
                return (
                  <div key={m.id} style={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start', marginBottom: 8 }}>
                    <div style={{ maxWidth: '70%', background: mine ? '#23408a' : 'var(--tile)', border: '1px solid var(--line)', borderRadius: 12, padding: '8px 12px' }}>
                      {!mine && <div style={{ fontSize: 12, fontWeight: 700, color: '#8eabff' }}>{m.sender}</div>}
                      <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{m.body}</div>
                      <div className="muted" style={{ fontSize: 11, textAlign: 'right' }}>{fmtDateTime(m.created_at)}{mine && (m.id <= data.read_by_all_up_to ? ' · read' : ' · sent')}</div>
                    </div>
                  </div>);
              })}
              <div ref={endRef} />
            </div>
            {current.can_post
              ? <form className="row" onSubmit={send} style={{ marginTop: 10, flexWrap: 'nowrap' }}>
                  <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Write a message" aria-label="Message" maxLength={5000} />
                  <button className="btn primary" disabled={!text.trim()}>Send</button></form>
              : <div className="muted" style={{ marginTop: 10 }}>Only admins can post in this channel.</div>}
          </>)}
        </div>
      </div>
      {modal && <GroupForm kind={modal} contacts={contacts} onClose={() => setModal(null)} onDone={async (c) => { setModal(null); await loadConvs(); setActive(c.id); }} />}
    </>
  );
}

import { useCallback, useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { Badge, ConfirmModal, ErrorBox, Field, Modal, PageHead } from '../../components/ui';
import { ROLE_LABEL, fmtDateTime } from '../../utils/format';

const PRESETS = [
  ['OpenAI', 'https://api.openai.com/v1'],
  ['OpenRouter', 'https://openrouter.ai/api/v1'],
  ['Groq', 'https://api.groq.com/openai/v1'],
  ['Google Gemini (OpenAI-compatible)', 'https://generativelanguage.googleapis.com/v1beta/openai'],
  ['Ollama on this server (no key)', 'http://localhost:11434/v1'],
];
const ROLES = ['admin', 'onroll', 'offroll', 'intern'];

function ProviderForm({ provider, onDone, onClose }) {
  const [f, setF] = useState(provider ? { name: provider.name, base_url: provider.base_url, api_key: '', models: provider.models.join('\n'), default_model: provider.default_model || '', is_enabled: provider.is_enabled }
    : { name: 'OpenAI', base_url: PRESETS[0][1], api_key: '', models: '', default_model: '', is_enabled: true });
  const [error, setError] = useState('');
  const [found, setFound] = useState(null);
  const [testing, setTesting] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const models = f.models.split('\n').map((m) => m.trim()).filter(Boolean);
  const body = () => {
    const b = { name: f.name, base_url: f.base_url, models, default_model: models.includes(f.default_model) ? f.default_model : models[0] || null, is_enabled: f.is_enabled };
    if (f.api_key.trim()) b.api_key = f.api_key.trim();     // empty = keep the stored key
    return b;
  };
  const save = async () => (provider ? api.patch(`/ai/providers/${provider.id}`, body()) : api.post('/ai/providers', body()));
  const submit = async (e) => {
    e.preventDefault();
    try { await save(); onDone(); } catch (err) { setError(errMsg(err)); }
  };
  const test = async () => {      // saves first (the key is only ever checked on the server), then asks the provider for its models
    setTesting(true); setError(''); setFound(null);
    try {
      const { data: saved } = await save();
      setF((x) => ({ ...x, api_key: '' }));            // the key is on the server now; do not keep it in the page
      const { data } = await api.post(`/ai/providers/${saved.id}/test`);
      setFound(data);
      onDone(saved, true);
    } catch (err) { setError(errMsg(err)); } finally { setTesting(false); }
  };
  const addModel = (m) => setF((x) => ({ ...x, models: [...new Set([...x.models.split('\n').map((s) => s.trim()).filter(Boolean), m])].join('\n') }));
  return (
    <Modal title={provider ? `Edit ${provider.name}` : 'Add AI provider'} onClose={onClose} wide>
      <form onSubmit={submit}>
        <ErrorBox error={error} />
        <div className="grid g2">
          <Field label="Name"><input required minLength={2} value={f.name} onChange={set('name')} aria-label="Provider name" /></Field>
          <Field label="Service"><select aria-label="Service preset" value={PRESETS.some((p) => p[1] === f.base_url) ? f.base_url : ''}
            onChange={(e) => { const p = PRESETS.find((x) => x[1] === e.target.value); if (p) setF({ ...f, base_url: p[1], name: provider ? f.name : p[0].split(' (')[0] }); }}>
            <option value="">Other OpenAI-compatible API</option>{PRESETS.map((p) => <option key={p[1]} value={p[1]}>{p[0]}</option>)}</select></Field>
        </div>
        <Field label="API address (base URL)"><input required value={f.base_url} onChange={set('base_url')} aria-label="API address" /></Field>
        <Field label={provider?.key_set ? 'API key (a key is stored; leave empty to keep it)' : 'API key'}>
          <input type="password" autoComplete="new-password" value={f.api_key} onChange={set('api_key')} aria-label="API key" placeholder={provider?.key_set ? '•••••••• stored' : 'sk-…'} />
          <small className="muted">The key is encrypted on the server. It is never sent back to any browser and never written to logs.</small></Field>
        <Field label="Models offered to users (one per line)"><textarea rows={4} value={f.models} onChange={set('models')} aria-label="Models" placeholder="Press “Save and test” to load the list from the provider" /></Field>
        {models.length > 1 && <Field label="Default model"><select value={models.includes(f.default_model) ? f.default_model : models[0]} onChange={set('default_model')} aria-label="Default model">
          {models.map((m) => <option key={m}>{m}</option>)}</select></Field>}
        {found && (
          <div className={found.ok ? 'notice' : 'error'} role="status" style={{ marginBottom: 12 }}>{found.message}
            {found.ok && found.models.length > 0 && <div className="checks" style={{ marginTop: 8, maxHeight: 150 }}>{found.models.map((m) => (
              <label key={m}><input type="checkbox" checked={models.includes(m)} onChange={(e) => (e.target.checked ? addModel(m) : setF({ ...f, models: models.filter((x) => x !== m).join('\n') }))} />{m}</label>))}</div>}
          </div>)}
        <label className="row" style={{ gap: 6, fontWeight: 400 }}><input type="checkbox" style={{ width: 'auto' }} checked={f.is_enabled} onChange={set('is_enabled')} />Enabled</label>
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Close</button>
          <button type="button" className="btn" disabled={testing} onClick={test}>{testing ? 'Testing…' : 'Save and test connection'}</button>
          <button className="btn primary">Save</button></div>
      </form>
    </Modal>
  );
}

export default function AISettings() {
  const [providers, setProviders] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [usage, setUsage] = useState(null);
  const [days, setDays] = useState(30);
  const [form, setForm] = useState(null);       // null | {} | provider
  const [remove, setRemove] = useState(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const load = useCallback(() => {
    api.get('/ai/providers').then((r) => setProviders(r.data)).catch((e) => setError(errMsg(e)));
    api.get('/ai/settings').then((r) => setCfg(r.data)).catch((e) => setError(errMsg(e)));
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get('/ai/usage', { params: { days } }).then((r) => setUsage(r.data)).catch((e) => setError(errMsg(e))); }, [days]);
  const saveCfg = async () => {
    try { setCfg((await api.put('/ai/settings', cfg)).data); setSaved(true); setTimeout(() => setSaved(false), 2000); setError(''); }
    catch (e) { setError(errMsg(e)); }
  };
  const ready = providers?.some((p) => p.is_enabled && p.models.length > 0);
  return (
    <>
      <PageHead title="AI assistant" sub="Connect an AI service, decide who may use it and how much, and see usage numbers.">
        <button className="btn primary" onClick={() => setForm({})}>Add AI provider</button>
      </PageHead>
      <ErrorBox error={error} />
      {providers && !ready && <div className="notice">The assistant does not answer yet: add a provider with an API key and at least one model. Until then users see “not set up”.</div>}
      <div className="card"><h2>Providers</h2>
        <div className="table-wrap">
          {providers && providers.length === 0 && <div className="empty">No provider yet.</div>}
          {providers && providers.length > 0 && (
            <table><thead><tr><th>Name</th><th>Address</th><th>Key</th><th>Models</th><th>Status</th><th /></tr></thead>
              <tbody>{providers.map((p) => (
                <tr key={p.id}><td><b>{p.name}</b></td><td className="muted">{p.base_url}</td><td>{p.key_set ? 'stored (hidden)' : <span className="muted">none</span>}</td>
                  <td>{p.models.length ? p.models.map((m) => <div key={m}>{m}{m === p.default_model ? ' · default' : ''}</div>) : <span className="muted">none chosen</span>}</td>
                  <td><Badge value={p.is_enabled ? 'active' : 'inactive'}>{p.is_enabled ? 'enabled' : 'disabled'}</Badge></td>
                  <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}><button className="btn small" onClick={() => setForm(p)}>Edit / test</button>{' '}
                    <button className="btn small danger" onClick={() => setRemove(p)}>Delete</button></td></tr>))}</tbody></table>)}
        </div>
      </div>

      {cfg && (
        <div className="card"><h2>Access and limits</h2>
          <label className="row" style={{ gap: 6, fontWeight: 400, marginBottom: 10 }}><input type="checkbox" style={{ width: 'auto' }} checked={cfg.enabled}
            onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} />AI assistant switched on for the company</label>
          <div className="table-wrap"><table><thead><tr><th>Role</th><th>May use AI</th><th>Messages per day (0 = no limit)</th></tr></thead>
            <tbody>{ROLES.map((r) => (
              <tr key={r}><td>{ROLE_LABEL[r]}</td>
                <td><input type="checkbox" style={{ width: 'auto' }} aria-label={`${ROLE_LABEL[r]} may use AI`} checked={cfg.role_enabled[r]}
                  onChange={(e) => setCfg({ ...cfg, role_enabled: { ...cfg.role_enabled, [r]: e.target.checked } })} /></td>
                <td><input type="number" min="0" max="100000" style={{ width: 120 }} aria-label={`${ROLE_LABEL[r]} daily limit`} value={cfg.daily_limits[r]}
                  onChange={(e) => setCfg({ ...cfg, daily_limits: { ...cfg.daily_limits, [r]: Number(e.target.value) || 0 } })} /></td></tr>))}</tbody></table></div>
          <div className="grid g2" style={{ marginTop: 12 }}>
            <Field label="Most project text sent with one question (characters)"><input type="number" min="2000" max="400000" value={cfg.max_context_chars}
              onChange={(e) => setCfg({ ...cfg, max_context_chars: Number(e.target.value) })} /></Field>
            <Field label="Longest answer (tokens)"><input type="number" min="200" max="32000" value={cfg.max_output_tokens}
              onChange={(e) => setCfg({ ...cfg, max_output_tokens: Number(e.target.value) })} /></Field>
          </div>
          <Field label="Company instructions for the assistant (optional)"><textarea value={cfg.extra_instructions} maxLength={4000}
            onChange={(e) => setCfg({ ...cfg, extra_instructions: e.target.value })} placeholder="Example: We use React 18 with plain CSS. Follow our naming rules…" /></Field>
          <button className="btn primary" onClick={saveCfg}>{saved ? 'Saved ✓' : 'Save settings'}</button>
        </div>)}

      <div className="card">
        <div className="row spread"><h2 style={{ margin: 0 }}>Usage</h2>
          <select style={{ width: 'auto' }} aria-label="Usage period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select></div>
        <p className="muted">Numbers only. Conversations are private; nobody, including administrators, can read another person’s chats here. Token counts are the provider’s figures when it reports them, otherwise an estimate.</p>
        {usage && (<>
          <p><b>{usage.totals.messages}</b> questions · <b>{usage.totals.users}</b> people · <b>{(usage.totals.prompt_tokens + usage.totals.completion_tokens).toLocaleString()}</b> tokens
            {usage.by_model.length > 0 && <span className="muted"> · {usage.by_model.map((m) => `${m.model}: ${m.answers}`).join(', ')}</span>}</p>
          <div className="table-wrap">
            {usage.rows.length === 0 ? <div className="empty">Nobody has used the assistant in this period.</div> : (
              <table><thead><tr><th>Person</th><th>Role</th><th>Questions</th><th>Today</th><th>Tokens in</th><th>Tokens out</th><th>Failed</th><th>Last used</th></tr></thead>
                <tbody>{usage.rows.map((r) => (
                  <tr key={r.user_id}><td>{r.full_name}</td><td>{ROLE_LABEL[r.role] || r.role}</td><td>{r.messages}</td><td>{r.today}</td>
                    <td>{r.prompt_tokens.toLocaleString()}</td><td>{r.completion_tokens.toLocaleString()}</td><td>{r.errors}</td><td>{fmtDateTime(r.last_used_at)}</td></tr>))}</tbody></table>)}
          </div>
        </>)}
      </div>

      {form && <ProviderForm provider={form.id ? form : null} onClose={() => { setForm(null); load(); }}
        onDone={(savedProvider, stay) => { load(); if (stay) setForm(savedProvider); else setForm(null); }} />}
      {remove && <ConfirmModal danger title="Delete provider" confirmLabel="Delete" text={`Delete ${remove.name}? Its stored key is erased. Users can no longer choose its models.`}
        onClose={() => setRemove(null)} onConfirm={async () => { try { await api.delete(`/ai/providers/${remove.id}`); } catch (e) { setError(errMsg(e)); } setRemove(null); load(); }} />}
    </>
  );
}

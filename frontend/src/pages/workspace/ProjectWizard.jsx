import { useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, Modal } from '../../components/ui';

/** "New project": adds a template's files to this workspace. */
export default function ProjectWizard({ workspaceId, onDone, onClose }) {
  const [list, setList] = useState(null);
  const [picked, setPicked] = useState(null);
  const [clash, setClash] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { api.get('/templates').then((r) => setList(r.data)).catch((e) => setError(errMsg(e))); }, []);
  const t = list?.find((x) => x.id === picked);
  const apply = async (overwrite) => {
    setBusy(true); setError('');
    try { onDone((await api.post(`/workspaces/${workspaceId}/template`, { template_id: picked, overwrite })).data, t); }
    catch (e) {
      const d = e?.response?.data?.detail;
      if (e?.response?.status === 409 && d?.files) setClash(d.files); else setError(errMsg(e));
    }
    setBusy(false);
  };
  const groups = [...new Set((list || []).map((x) => x.group))];
  return (
    <Modal title="New project from a template" onClose={onClose} wide>
      <ErrorBox error={error} />
      {!list && !error && <div className="empty">Loading templates…</div>}
      {list && (
        <div className="grid" style={{ gridTemplateColumns: '260px 1fr', gap: 16 }}>
          <div style={{ maxHeight: 380, overflow: 'auto' }}>
            {groups.map((g) => (
              <div key={g}><h3 style={{ marginTop: 8 }}>{g}</h3>
                {list.filter((x) => x.group === g).map((x) => (
                  <button key={x.id} type="button" className={`tpl ${picked === x.id ? 'on' : ''}`} aria-pressed={picked === x.id}
                    onClick={() => { setPicked(x.id); setClash(null); }}>{x.name}</button>))}
              </div>))}
          </div>
          <div>
            {!t && <p className="muted">Choose a template. Its files are added to this workspace; your existing files stay.</p>}
            {t && (<>
              <h2>{t.name}</h2>
              <p><b>Needs:</b> {t.needs}</p>
              <p className={t.verified ? 'muted' : ''}>{t.verified
                ? 'This template was installed, built and run during development.'
                : '⚠ Not test-run: the toolchain for this template was not available where WORKCODE was built. The files follow the standard layout.'}</p>
              <div className="tile" style={{ maxHeight: 170, overflow: 'auto', fontFamily: 'ui-monospace,Consolas,monospace', fontSize: 12.5 }}>
                {t.files.map((f) => <div key={f}>{f}</div>)}</div>
              {clash && <div className="notice" style={{ marginTop: 10 }}>These files already exist: {clash.join(', ')}. Replacing keeps the old content in each file’s History.</div>}
            </>)}
          </div>
        </div>)}
      <div className="modal-foot">
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        {clash
          ? <button type="button" className="btn danger" disabled={busy} onClick={() => apply(true)}>Replace existing files</button>
          : <button type="button" className="btn primary" disabled={!t || busy} onClick={() => apply(false)}>{busy ? 'Creating…' : 'Create project files'}</button>}
      </div>
    </Modal>
  );
}

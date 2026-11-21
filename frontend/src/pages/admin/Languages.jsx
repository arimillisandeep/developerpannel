import { useCallback, useEffect, useState } from 'react';
import api, { errMsg } from '../../services/api';
import { ErrorBox, PageHead } from '../../components/ui';

const TONE = { ready: 'green', pulling: 'blue', missing: 'amber', unknown: '' };

export default function Languages() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(() => api.get('/languages').then((r) => setData(r.data)).catch((e) => setError(errMsg(e))), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {  // refresh while something is downloading
    if (!data?.languages.some((l) => l.image_state === 'pulling')) return undefined;
    const t = setTimeout(load, 5000);
    return () => clearTimeout(t);
  }, [data, load]);
  const pull = async (l) => { try { await api.post(`/languages/${l.id}/pull`); setError(''); load(); } catch (e) { setError(errMsg(e)); } };
  if (!data) return <ErrorBox error={error} />;
  const kinds = { run: 'Runs in Docker', preview: 'Browser preview', edit: 'Edit only' };
  const count = (k) => data.languages.filter((l) => l.kind === k).length;
  return (
    <>
      <PageHead title="Languages" sub={`${data.languages.length} languages: ${count('run')} run in isolated Docker containers, ${count('preview')} use the browser preview, ${count('edit')} are edit-only.`} />
      <ErrorBox error={error} />
      <div className="notice">
        {data.runner.available
          ? 'Docker is running. A language can be run after its image is installed (one download per language, some are several hundred MB).'
          : `Code cannot be run on this server: ${data.runner.reason}`}
      </div>
      <div className="card table-wrap">
        <table><thead><tr><th>Language</th><th>File types</th><th>Mode</th><th>Docker image</th><th>Image</th><th /></tr></thead>
          <tbody>{data.languages.map((l) => (
            <tr key={l.id}><td><b>{l.name}</b>{l.note && <div className="muted" style={{ maxWidth: 380 }}>{l.note}</div>}</td>
              <td>{l.extensions.map((e) => `.${e}`).join(' ') || '—'}</td><td>{kinds[l.kind]}</td><td>{l.image || '—'}</td>
              <td>{l.kind === 'run' && <span className={`badge ${TONE[l.image_state] ?? 'red'}`}>{l.image_state}</span>}</td>
              <td style={{ textAlign: 'right' }}>{l.kind === 'run' && data.runner.available && l.image_state !== 'ready' && l.image_state !== 'pulling' &&
                <button className="btn small primary" onClick={() => pull(l)}>Install</button>}</td></tr>))}
          </tbody></table>
      </div>
    </>
  );
}

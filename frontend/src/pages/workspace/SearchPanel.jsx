import { useMemo, useState } from 'react';

/** Find text in every file of the project (searches the editor's current content, including unsaved edits). */
export function searchFiles(files, query, matchCase = false, limit = 500) {
  if (!query) return [];
  const needle = matchCase ? query : query.toLowerCase();
  const out = [];
  for (const f of files) {
    const lines = (f.content || '').split('\n');
    for (let i = 0; i < lines.length && out.length < limit; i += 1) {
      const col = (matchCase ? lines[i] : lines[i].toLowerCase()).indexOf(needle);
      if (col >= 0) out.push({ fileId: f.id, path: f.path, line: i + 1, column: col + 1, text: lines[i].trim().slice(0, 160) });
    }
  }
  return out;
}

export default function SearchPanel({ files, onOpen }) {
  const [q, setQ] = useState('');
  const [matchCase, setMatchCase] = useState(false);
  const results = useMemo(() => searchFiles(files, q.length >= 2 ? q : '', matchCase), [files, q, matchCase]);
  const groups = useMemo(() => {
    const m = new Map();
    results.forEach((r) => { if (!m.has(r.path)) m.set(r.path, []); m.get(r.path).push(r); });
    return [...m.entries()];
  }, [results]);
  return (
    <div className="side-pane">
      <div className="side-title">Search</div>
      <div style={{ padding: '0 10px 8px' }}>
        <input aria-label="Search in files" autoFocus placeholder="Search in all files" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="row muted" style={{ marginTop: 6, fontSize: 12 }}>
          <input type="checkbox" style={{ width: 'auto' }} checked={matchCase} onChange={(e) => setMatchCase(e.target.checked)} /> Match case</label>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          {q.length < 2 ? 'Type at least 2 characters.' : `${results.length}${results.length >= 500 ? '+' : ''} result(s) in ${groups.length} file(s)`}</div>
      </div>
      <div style={{ overflow: 'auto', flex: 1 }}>
        {groups.map(([path, rows]) => (
          <div key={path}>
            <div className="search-file">{path} <span className="muted">({rows.length})</span></div>
            {rows.map((r) => (
              <div key={`${r.line}:${r.column}`} className="search-hit" onClick={() => onOpen(r.fileId, r.line, r.column)}>
                <span className="muted">{r.line}</span> {r.text}</div>))}
          </div>))}
      </div>
    </div>
  );
}

/** Shows the result of GET /tasks/:id/compare: changed files with their real line differences. */
const TONE = { added: 'green', modified: 'amber', deleted: 'red' };

export function DiffText({ diff }) {
  return (
    <pre className="diff" aria-label="Code differences">{diff.split('\n').map((line, i) => {
      const kind = line.startsWith('+++') || line.startsWith('---') ? 'head' : line.startsWith('@@') ? 'hunk'
        : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : '';
      return <span key={i} className={kind}>{line || ' '}</span>;
    })}</pre>
  );
}

export default function DiffView({ data }) {
  if (!data) return null;
  const { summary } = data;
  return (
    <div>
      <p className="muted">Version {data.from.version} → {data.to.version}: {summary.added} added · {summary.modified} modified · {summary.deleted} deleted · {data.unchanged} unchanged</p>
      {data.files.length === 0 && <div className="empty">These two versions have the same files.</div>}
      {data.files.map((f) => (
        <details key={f.path} open={data.files.length <= 4} className="diff-file">
          <summary><span className={`badge ${TONE[f.status]}`}>{f.status}</span> <b>{f.path}</b> <span className="muted">+{f.lines_added} −{f.lines_removed}</span></summary>
          <DiffText diff={f.diff} />
        </details>))}
    </div>
  );
}

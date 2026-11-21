/** Small, safe Markdown renderer for chat text (no raw HTML is ever inserted): headings, lists, quotes,
 *  tables, bold, italic, inline code and links. Code blocks are rendered by the caller. */
function inline(text, key = 'i') {
  const out = [];
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\((https?:\/\/[^\s)]+)\))/g;
  let last = 0; let m; let n = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${key}-${n++}`;
    if (m[1]) out.push(<code key={k}>{m[1].slice(1, -1)}</code>);
    else if (m[2]) out.push(<b key={k}>{inline(m[2].slice(2, -2), k)}</b>);
    else if (m[3]) out.push(<i key={k}>{m[3].slice(1, -1)}</i>);
    else out.push(<a key={k} href={m[5]} target="_blank" rel="noreferrer noopener">{m[4].slice(1, m[4].indexOf(']'))}</a>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text }) {
  const lines = (text || '').split('\n');
  const out = [];
  let i = 0; let k = 0;
  const cells = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { const T = `h${Math.min(6, h[1].length + 2)}`; out.push(<T key={k++}>{inline(h[2])}</T>); i += 1; continue; }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, '')); i += 1; }
      const L = ordered ? 'ol' : 'ul';
      out.push(<L key={k++}>{items.map((t, j) => <li key={j}>{inline(t)}</li>)}</L>);
      continue;
    }
    if (line.startsWith('>')) {
      const q = [];
      while (i < lines.length && lines[i].startsWith('>')) { q.push(lines[i].replace(/^>\s?/, '')); i += 1; }
      out.push(<blockquote key={k++}>{inline(q.join(' '))}</blockquote>);
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])) {
      const head = cells(line); i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { rows.push(cells(lines[i])); i += 1; }
      out.push(<div className="table-wrap" key={k++}><table><thead><tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
        <tbody>{rows.map((r, j) => <tr key={j}>{r.map((c, x) => <td key={x}>{inline(c)}</td>)}</tr>)}</tbody></table></div>);
      continue;
    }
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) { out.push(<hr key={k++} />); i += 1; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|>|\s*([-*+]|\d+[.)])\s+)/.test(lines[i])) { para.push(lines[i]); i += 1; }
    out.push(<p key={k++}>{para.flatMap((t, j) => (j ? [<br key={`b${j}`} />, ...inline(t, `p${j}`)] : inline(t, `p${j}`)))}</p>);
  }
  return <div className="md">{out}</div>;
}

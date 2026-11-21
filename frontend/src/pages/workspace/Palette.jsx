import { useEffect, useMemo, useRef, useState } from 'react';

/** Quick-open / command palette: type to filter, ↑ ↓ to move, Enter to choose, Esc to close. */
export default function Palette({ title, placeholder, items, onClose }) {
  const [q, setQ] = useState('');
  const [index, setIndex] = useState(0);
  const input = useRef(null);
  useEffect(() => { input.current?.focus(); }, []);
  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return items.filter((i) => words.every((w) => i.label.toLowerCase().includes(w))).slice(0, 60);
  }, [q, items]);
  const choose = (item) => { if (!item || item.disabled) return; onClose(); item.run(); };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setIndex((i) => Math.min(shown.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); choose(shown[index]); }
  };
  return (
    <div className="palette-back" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <input ref={input} aria-label={title} placeholder={placeholder} value={q} onChange={(e) => { setQ(e.target.value); setIndex(0); }} onKeyDown={onKey} />
        <div className="palette-list" role="listbox">
          {shown.length === 0 && <div className="muted" style={{ padding: 10 }}>Nothing matches.</div>}
          {shown.map((item, i) => (
            <div key={item.key ?? item.label} role="option" aria-selected={i === index} aria-disabled={item.disabled || undefined}
              className={`palette-item ${i === index ? 'on' : ''} ${item.disabled ? 'off' : ''}`} onMouseEnter={() => setIndex(i)} onClick={() => choose(item)}>
              <span>{item.label}</span>{item.hint && <span className="muted">{item.hint}</span>}
            </div>))}
        </div>
      </div>
    </div>
  );
}

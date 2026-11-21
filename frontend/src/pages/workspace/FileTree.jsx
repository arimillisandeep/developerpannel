import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/** Turn flat paths into a nested tree: folders first, then files, both A-Z. */
export function buildTree(files) {
  const root = { name: '', path: '', dirs: {}, files: [] };
  files.forEach((f) => {
    const parts = f.path.split('/');
    let node = root;
    parts.slice(0, -1).forEach((part, i) => {
      node.dirs[part] = node.dirs[part] || { name: part, path: parts.slice(0, i + 1).join('/'), dirs: {}, files: [] };
      node = node.dirs[part];
    });
    node.files.push({ ...f, name: parts[parts.length - 1] });
  });
  return root;
}

const ICON = { js: 'JS', jsx: 'JS', ts: 'TS', tsx: 'TS', py: 'PY', java: 'JV', html: '<>', css: '#', scss: '#', json: '{}', md: 'M', sql: 'DB',
  c: 'C', cpp: 'C+', cs: 'C#', php: 'PH', go: 'GO', rs: 'RS', dart: 'DT', yml: 'Y', yaml: 'Y', xml: '<>', vue: 'V' };
const icon = (name) => ICON[name.split('.').pop().toLowerCase()] || '·';
const parentOf = (p) => (p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '');
const join = (folder, name) => (folder ? `${folder}/${name}` : name);
const KEEP = '.gitkeep';                       // placeholder that makes an empty folder exist; never shown
const PART = /^[A-Za-z0-9_\-. @+()[\]]+$/;     // same rule as the server

/** The text box that appears inside the tree for New File, New Folder and Rename (as in VS Code):
 *  Enter or clicking elsewhere confirms, Esc cancels, a problem with the name is shown right under it. */
function NameInput({ initial = '', label, depth, ico, check, onSubmit, onCancel }) {
  const [value, setValue] = useState(initial);
  const ref = useRef(null);
  const done = useRef(false);
  useEffect(() => {
    const el = ref.current;
    el.focus();
    const dot = initial.lastIndexOf('.');
    el.setSelectionRange(0, dot > 0 ? dot : initial.length);      // rename: the name without the extension is selected
  }, [initial]);
  const problem = value.trim() && value.trim() !== initial ? check(value.trim()) : null;
  const finish = (commit) => {
    if (done.current) return;
    const name = value.trim().replace(/^\/+|\/+$/g, '');
    if (!commit || !name || name === initial || check(name)) { done.current = true; onCancel(); return; }
    done.current = true; onSubmit(name);
  };
  return (
    <div className="tree-edit" style={{ paddingLeft: 8 + depth * 14 }} onClick={(e) => e.stopPropagation()}>
      <span className="tree-ico small">{ico}</span>
      <div className="tree-edit-box">
        <input ref={ref} aria-label={label} aria-invalid={!!problem} value={value} spellCheck={false} autoComplete="off"
          onChange={(e) => setValue(e.target.value)} onBlur={() => finish(true)}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === 'Enter') { e.preventDefault(); if (!problem) finish(true); } else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
          }} />
        {problem && <div className="tree-err" role="alert">{problem}</div>}
      </div>
    </div>);
}

const FileTree = forwardRef(function FileTree(
  { files, activeId, dirty, readOnly, filter, onOpen, onAction, onMove, onDropFiles, onCreate, onRename }, apiRef) {
  const [closed, setClosed] = useState({});
  const [over, setOver] = useState(null);
  const [selected, setSelected] = useState(null);     // path of the highlighted file or folder
  const [edit, setEdit] = useState(null);             // { mode: 'file' | 'folder', parent } or { mode: 'rename', node }
  const [menu, setMenu] = useState(null);             // right-click menu: { x, y, node, kind }
  const shown = useMemo(() => (filter ? files.filter((f) => f.path.toLowerCase().includes(filter.toLowerCase())) : files), [files, filter]);
  const tree = useMemo(() => buildTree(shown), [shown]);
  const folders = useMemo(() => { const s = new Set(); files.forEach((f) => { let p = parentOf(f.path); while (p) { s.add(p); p = parentOf(p); } }); return s; }, [files]);
  const taken = (path) => folders.has(path) || files.some((f) => f.path === path);

  useEffect(() => { const f = files.find((x) => x.id === activeId); if (f) setSelected(f.path); }, [activeId]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!menu) return undefined;
    const close = () => setMenu(null);
    const key = (e) => { if (e.key === 'Escape') close(); };
    window.addEventListener('mousedown', close); window.addEventListener('keydown', key); window.addEventListener('blur', close);
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', key); window.removeEventListener('blur', close); };
  }, [menu]);

  /** New things go into the selected folder, or next to the selected file (as in VS Code). */
  const targetFolder = (path = selected) => {
    let p = path == null ? '' : folders.has(path) ? path : parentOf(path);
    while (p && !folders.has(p)) p = parentOf(p);        // e.g. the selection was just created and is not listed yet
    return p;
  };
  const expand = (folder) => setClosed((c) => { const n = { ...c }; let p = folder; while (p) { delete n[p]; p = parentOf(p); } return n; });
  const startNew = (mode, folder = targetFolder()) => { if (readOnly) return; expand(folder); setEdit({ mode, parent: folder }); };
  const startRename = (node) => { if (!readOnly && node) setEdit({ mode: 'rename', node }); };
  useImperativeHandle(apiRef, () => ({ newFile: (folder) => startNew('file', folder), newFolder: (folder) => startNew('folder', folder),
    collapseAll: () => setClosed(Object.fromEntries([...folders].map((p) => [p, true]))) }));

  const checkName = (folder, self) => (name) => {
    const parts = name.replace(/^\/+|\/+$/g, '').split('/');
    if (parts.some((p) => !p || p === '.' || p === '..')) return 'A file or folder name must be provided.';
    if (parts.some((p) => !PART.test(p))) return `The name ${name} is not valid. Use letters, numbers, spaces and - _ . @ + ( ) [ ].`;
    const path = join(folder, parts.join('/'));
    if (path.length > 300) return 'The path is too long.';
    if (path !== self && taken(path)) return `A file or folder ${name} already exists at this location. Choose a different name.`;
    return null;
  };
  const submitNew = (name) => {
    const { mode, parent } = edit;
    const path = join(parent, name);
    setEdit(null); setSelected(path);
    onCreate(mode, path);
  };
  const submitRename = (name) => {
    const { node } = edit;
    setEdit(null);
    const to = join(parentOf(node.path), name);
    setSelected(to);
    onRename(node.path, to);
  };

  const nodeAt = (path) => {
    if (path == null) return null;
    const f = files.find((x) => x.path === path);
    return f ? { node: { ...f, name: path.split('/').pop() }, kind: 'file' } : folders.has(path) ? { node: { path, name: path.split('/').pop() }, kind: 'folder' } : null;
  };
  const onKeyDown = (e) => {
    if (readOnly || edit) return;
    const hit = nodeAt(selected);
    if (e.key === 'F2' && hit) { e.preventDefault(); startRename(hit.node); }
    else if (e.key === 'Delete' && hit) { e.preventDefault(); onAction(hit.kind === 'file' ? 'delete' : 'deleteFolder', hit.node); }
  };
  const openMenu = (e, node, kind) => {
    e.preventDefault(); e.stopPropagation();
    if (node) setSelected(node.path);
    setMenu({ x: Math.min(e.clientX, window.innerWidth - 230), y: Math.min(e.clientY, window.innerHeight - 250), node, kind });
  };
  const menuItems = () => {
    const { node, kind } = menu;
    const folder = kind === 'folder' ? node.path : kind === 'file' ? parentOf(node.path) : '';
    const items = [
      ['New File…', () => startNew('file', folder)],
      ['New Folder…', () => startNew('folder', folder)],
      ['New File from Template…', () => onAction('new', { path: folder })],
    ];
    if (node) items.push(null, ['Rename…', () => startRename(node), 'F2'], ['Duplicate…', () => onAction('copy', node)],
      ['Delete', () => onAction(kind === 'file' ? 'delete' : 'deleteFolder', node), 'Del']);
    return items;
  };

  const dropProps = (folder) => (readOnly ? {} : {
    onDragOver: (e) => { e.preventDefault(); e.stopPropagation(); setOver(folder); },
    onDragLeave: () => setOver((o) => (o === folder ? null : o)),
    onDrop: (e) => {
      e.preventDefault(); e.stopPropagation(); setOver(null);
      const from = e.dataTransfer.getData('text/wc-path');
      if (from) { if (parentOf(from) !== folder && from !== folder) onMove(from, folder); }
      else if (e.dataTransfer.files?.length) onDropFiles(e.dataTransfer.files, folder);
    },
  });
  const drag = (path) => (readOnly ? {} : { draggable: true, onDragStart: (e) => { e.dataTransfer.setData('text/wc-path', path); e.dataTransfer.effectAllowed = 'move'; } });
  const renaming = (path) => edit?.mode === 'rename' && edit.node.path === path;

  const renderDir = (node, depth) => (
    <div key={node.path || '/'}>
      {edit?.mode === 'folder' && edit.parent === node.path && (
        <NameInput label="New folder name" depth={depth} ico="▸" check={checkName(node.path)} onSubmit={submitNew} onCancel={() => setEdit(null)} />)}
      {Object.values(node.dirs).sort((a, b) => a.name.localeCompare(b.name)).map((d) => (
        <div key={d.path}>
          {renaming(d.path)
            ? <NameInput label="Rename folder" initial={d.name} depth={depth} ico="▾" check={checkName(parentOf(d.path), d.path)} onSubmit={submitRename} onCancel={() => setEdit(null)} />
            : <div className={`tree-row ${over === d.path ? 'over' : ''} ${selected === d.path ? 'sel' : ''}`} style={{ paddingLeft: 8 + depth * 14 }} role="treeitem"
                aria-expanded={!closed[d.path]} aria-selected={selected === d.path} title={d.path}
                onClick={() => { setSelected(d.path); setClosed((c) => ({ ...c, [d.path]: !c[d.path] })); }}
                onContextMenu={(e) => openMenu(e, d, 'folder')} {...drag(d.path)} {...dropProps(d.path)}>
                <span className="tree-ico">{closed[d.path] ? '▸' : '▾'}</span><span className="tree-name">{d.name}</span>
              </div>}
          {!closed[d.path] && renderDir(d, depth + 1)}
        </div>))}
      {edit?.mode === 'file' && edit.parent === node.path && (
        <NameInput label="New file name" depth={depth} ico="·" check={checkName(node.path)} onSubmit={submitNew} onCancel={() => setEdit(null)} />)}
      {node.files.filter((f) => f.name !== KEEP).sort((a, b) => a.name.localeCompare(b.name)).map((f) => (renaming(f.path)
        ? <NameInput key={f.id} label="Rename file" initial={f.name} depth={depth} ico={icon(f.name)} check={checkName(parentOf(f.path), f.path)} onSubmit={submitRename} onCancel={() => setEdit(null)} />
        : <div key={f.id} className={`tree-row ${f.id === activeId ? 'on' : ''} ${selected === f.path ? 'sel' : ''}`} style={{ paddingLeft: 8 + depth * 14 }} role="treeitem"
            aria-selected={selected === f.path} title={f.path} onClick={() => { setSelected(f.path); onOpen(f.id); }}
            onContextMenu={(e) => openMenu(e, f, 'file')} {...drag(f.path)}>
            <span className="tree-ico small">{icon(f.name)}</span><span className="tree-name">{f.name}{dirty[f.id] ? ' ●' : ''}</span>
          </div>))}
    </div>);

  return (
    <div className={`tree ${over === '' ? 'over' : ''}`} role="tree" aria-label="Project files" tabIndex={0} onKeyDown={onKeyDown}
      onClick={(e) => { if (e.target === e.currentTarget) setSelected(null); }}
      onContextMenu={(e) => { if (!readOnly) openMenu(e, null, 'root'); }} {...dropProps('')}>
      {shown.length === 0 && !edit && <div className="muted" style={{ padding: 10 }}>{files.length ? 'No file matches.' : 'No files yet. Create one with the New File button above, or start from a project template.'}</div>}
      {renderDir(tree, 0)}
      {menu && !readOnly && createPortal(
        <div className="ctx-menu" role="menu" style={{ left: menu.x, top: menu.y }} onMouseDown={(e) => e.stopPropagation()} onContextMenu={(e) => e.preventDefault()}>
          {menuItems().map((item, i) => (item
            ? <button key={item[0]} type="button" role="menuitem" onClick={() => { setMenu(null); item[1](); }}><span>{item[0]}</span>{item[2] && <kbd>{item[2]}</kbd>}</button>
            : <hr key={`sep${i}`} />))}
        </div>, document.body)}
    </div>
  );
});

export default FileTree;

import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { buildTree } from '../pages/workspace/FileTree';
import FileTree from '../pages/workspace/FileTree';
import Palette from '../pages/workspace/Palette';
import { searchFiles } from '../pages/workspace/SearchPanel';
import { buildPreview, pickHtml, resolveRef } from '../pages/workspace/preview';

const F = (id, path, content = '') => ({ id, path, content });

describe('IDE building blocks', () => {
  it('builds a nested tree from flat paths', () => {
    const t = buildTree([F(1, 'src/app.js'), F(2, 'src/lib/util.js'), F(3, 'index.html')]);
    expect(Object.keys(t.dirs)).toEqual(['src']);
    expect(t.files.map((f) => f.name)).toEqual(['index.html']);
    expect(t.dirs.src.dirs.lib.files[0].path).toBe('src/lib/util.js');
  });

  it('explorer creates and renames inside the tree like VS Code: inline name box, Enter / Esc, name checks', () => {
    const files = [F(1, 'src/app.js'), F(2, 'src/lib/util.js'), F(3, 'index.html'), F(4, 'empty/.gitkeep')];
    const made = []; const renamed = [];
    const ref = { current: null };
    render(<FileTree ref={ref} files={files} activeId={null} dirty={{}} readOnly={false} filter="" onOpen={() => {}} onAction={() => {}} onMove={() => {}}
      onDropFiles={() => {}} onCreate={(mode, path) => made.push([mode, path])} onRename={(from, to) => renamed.push([from, to])} />);
    expect(screen.queryByText('.gitkeep')).toBeNull();                              // the placeholder of an empty folder is hidden
    expect(screen.getByText('empty')).toBeInTheDocument();
    // New File with nothing selected: the box appears at the top level
    act(() => ref.current.newFile());
    const box = screen.getByLabelText('New file name');
    expect(box).toHaveFocus();
    fireEvent.change(box, { target: { value: 'index.html' } });
    expect(screen.getByRole('alert')).toHaveTextContent('already exists at this location');
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(made).toEqual([]);                                                       // a taken name is not created
    fireEvent.change(box, { target: { value: 'bad:name.js' } });
    expect(screen.getByRole('alert')).toHaveTextContent('is not valid');
    fireEvent.change(box, { target: { value: 'main.py' } });
    expect(screen.queryByRole('alert')).toBeNull();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(made).toEqual([['file', 'main.py']]);
    expect(screen.queryByLabelText('New file name')).toBeNull();
    // a selected folder is where new things go; a path with / creates the folders on the way
    fireEvent.click(screen.getByText('lib'));          // selects src/lib (and collapses it)
    act(() => ref.current.newFile());
    fireEvent.change(screen.getByLabelText('New file name'), { target: { value: 'deep/more.js' } });
    fireEvent.keyDown(screen.getByLabelText('New file name'), { key: 'Enter' });
    act(() => ref.current.newFolder());
    fireEvent.change(screen.getByLabelText('New folder name'), { target: { value: 'components' } });
    fireEvent.blur(screen.getByLabelText('New folder name'));                       // clicking elsewhere confirms
    expect(made.slice(1)).toEqual([['file', 'src/lib/deep/more.js'], ['folder', 'src/lib/components']]);
    // Esc cancels; an empty name cancels
    act(() => ref.current.newFolder(''));
    fireEvent.change(screen.getByLabelText('New folder name'), { target: { value: 'nope' } });
    fireEvent.keyDown(screen.getByLabelText('New folder name'), { key: 'Escape' });
    act(() => ref.current.newFile(''));
    fireEvent.keyDown(screen.getByLabelText('New file name'), { key: 'Enter' });
    expect(made).toHaveLength(3);
    // F2 renames the selected file in place; the right-click menu renames a folder
    fireEvent.click(screen.getByText('index.html'));
    fireEvent.keyDown(screen.getByRole('tree'), { key: 'F2' });
    const rn = screen.getByLabelText('Rename file');
    expect(rn).toHaveValue('index.html');
    expect([rn.selectionStart, rn.selectionEnd]).toEqual([0, 5]);                   // "index" is selected, the extension is not
    fireEvent.change(rn, { target: { value: 'home.html' } });
    fireEvent.keyDown(rn, { key: 'Enter' });
    fireEvent.contextMenu(screen.getByText('src'));
    fireEvent.click(screen.getByRole('menuitem', { name: /^Rename/ }));
    fireEvent.change(screen.getByLabelText('Rename folder'), { target: { value: 'source' } });
    fireEvent.keyDown(screen.getByLabelText('Rename folder'), { key: 'Enter' });
    expect(renamed).toEqual([['index.html', 'home.html'], ['src', 'source']]);
    // right-click on the empty area offers New File / New Folder for the top level
    fireEvent.contextMenu(screen.getByRole('tree'));
    expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['New File…', 'New Folder…', 'New File from Template…']);
  });

  it('file tree shows 50+ files in folders, collapses, filters, and reports actions', () => {
    const files = Array.from({ length: 60 }, (_, i) => F(i + 1, `pages/page${i}.html`)).concat([F(100, 'css/style.css'), F(101, 'index.html')]);
    const seen = [];
    const { rerender } = render(<FileTree files={files} activeId={101} dirty={{ 100: true }} readOnly={false} filter="" onOpen={(id) => seen.push(['open', id])}
      onAction={(type, node) => seen.push([type, node.path])} onMove={() => {}} onDropFiles={() => {}} />);
    expect(screen.getAllByRole('treeitem')).toHaveLength(64);                     // 62 files + 2 folders
    expect(screen.getByText('style.css ●')).toBeInTheDocument();                   // unsaved marker
    fireEvent.click(screen.getByText('pages'));                                    // collapse
    expect(screen.getAllByRole('treeitem')).toHaveLength(4);
    fireEvent.click(screen.getByText('index.html'));
    // right-click menu, as in VS Code
    fireEvent.contextMenu(screen.getByText('css'));
    fireEvent.click(screen.getByRole('menuitem', { name: /^Delete/ }));
    fireEvent.contextMenu(screen.getByText('index.html'));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Duplicate…' }));
    expect(screen.queryByRole('menu')).toBeNull();
    // keyboard: Delete on the selected item
    fireEvent.keyDown(screen.getByRole('tree'), { key: 'Delete' });
    expect(seen).toEqual([['open', 101], ['deleteFolder', 'css'], ['copy', 'index.html'], ['delete', 'index.html']]);
    rerender(<FileTree files={files} activeId={101} dirty={{}} readOnly filter="style" onOpen={() => {}} onAction={() => {}} onMove={() => {}} onDropFiles={() => {}} />);
    expect(screen.getAllByRole('treeitem')).toHaveLength(2);                       // css + style.css
    fireEvent.contextMenu(screen.getByText('style.css'));
    expect(screen.queryByRole('menu')).toBeNull();                                 // read-only: no menu, no actions
    fireEvent.keyDown(screen.getByRole('tree'), { key: 'F2' });
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('searches text across files with line numbers', () => {
    const files = [F(1, 'a.js', 'const x = 1;\nconsole.log(X);'), F(2, 'b/c.py', 'print("x")')];
    expect(searchFiles(files, 'x').map((r) => `${r.path}:${r.line}:${r.column}`)).toEqual(['a.js:1:7', 'a.js:2:13', 'b/c.py:1:8']);
    expect(searchFiles(files, 'X', true).map((r) => `${r.path}:${r.line}`)).toEqual(['a.js:2']);
    expect(searchFiles(files, '')).toEqual([]);
  });

  it('palette filters, runs the chosen command with Enter and skips disabled ones', () => {
    const ran = [];
    let closed = 0;
    render(<Palette title="Command palette" placeholder="" onClose={() => { closed += 1; }} items={[
      { label: 'File: Save all', run: () => ran.push('save') }, { label: 'View: Terminal', run: () => ran.push('term') },
      { label: 'Task: Submit', disabled: true, run: () => ran.push('submit') }]} />);
    const input = screen.getByRole('textbox', { name: 'Command palette' });
    fireEvent.change(input, { target: { value: 'term' } });
    expect(screen.getAllByRole('option')).toHaveLength(1);
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.change(input, { target: { value: 'submit' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(ran).toEqual(['term']);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(closed).toBe(2);
  });

  it('preview inlines CSS and JS from sub-folders and adds the console bridge', () => {
    expect(resolveRef('pages/', '../css/a.css')).toBe('css/a.css');
    expect(resolveRef('', './js/app.js?v=2')).toBe('js/app.js');
    expect(resolveRef('', 'https://cdn.example.com/x.js')).toBeNull();
    const files = [F(1, 'pages/about.html', '<html><head><link rel="stylesheet" href="../css/a.css"><link rel="icon" href="../css/a.css"></head><body><script src="../js/app.js"></script><script src="https://cdn.example.com/x.js"></script></body></html>'),
      F(2, 'css/a.css', 'body{color:red}'), F(3, 'js/app.js', 'console.log("</script>")'), F(4, 'index.html', '<h1>home</h1>')];
    const html = buildPreview(files[0], files, 'k1');
    expect(html).toContain('<style>\nbody{color:red}\n</style>');
    expect(html).toContain('<link rel="icon" href="../css/a.css">');               // only stylesheets are inlined
    expect(html).toContain('console.log("<\\/script>")');                           // cannot break out of the script tag
    expect(html).toContain('src="https://cdn.example.com/x.js"');                   // external scripts untouched
    expect(html).toContain('wcPreview:"k1"');
    expect(pickHtml(files[2], files).path).toBe('index.html');
    expect(pickHtml(files[0], files).path).toBe('pages/about.html');
    expect(pickHtml(null, [files[1]])).toBeNull();
  });
});

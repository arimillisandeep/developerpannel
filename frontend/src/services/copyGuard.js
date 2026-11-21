/**
 * Copy protection: code must not leave WORKCODE through the clipboard, but pasting INTO WORKCODE must work.
 *
 * When it is on (every role except Admin):
 *  - copy / cut anywhere in the app never put the real text on the computer's clipboard. The text is kept in
 *    memory inside this tab, and a short notice is put on the clipboard instead.
 *  - paste: text copied in another program is pasted normally. If the clipboard holds our notice, the text
 *    kept in memory is pasted, so copy/paste between files inside WORKCODE still works.
 *  - dragging selected text out of the page is blocked.
 * Ctrl+A, Ctrl+Z and Ctrl+Y are not touched.
 *
 * This is a deterrent in the browser, not a guarantee: screenshots, retyping, a phone camera and the
 * browser's developer tools cannot be stopped by a web page.
 */
export const NOTICE = 'Copying out of WORKCODE is not allowed.';
let held = '';                 // what the user copied inside WORKCODE (this tab only)
let on = false;
let editor = null;             // the Monaco editor of the open workspace, if any
const listeners = new Set();   // told when a copy was held back, so the page can show a hint

export const guardOn = () => on;
export const setGuardEditor = (ed) => { editor = ed; };
export const onGuard = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
const tell = (what) => listeners.forEach((fn) => fn(what));

const inEditor = (el) => !!(editor && el?.closest?.('.monaco-editor'));
const isField = (el) => el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !['checkbox', 'radio', 'button', 'submit', 'file'].includes(el.type)));

function selectedText(target) {
  if (inEditor(target)) {
    const model = editor.getModel?.();
    const sels = editor.getSelections?.() || [];
    if (!model) return '';
    const parts = sels.map((s) => (s.isEmpty() ? `${model.getLineContent(s.startLineNumber)}\n` : model.getValueInRange(s)));   // empty selection = whole line, like VS Code
    return parts.join(sels.length > 1 ? '\n' : '');
  }
  if (isField(target)) {
    if (target.type === 'password') return '';
    try { return target.value.slice(target.selectionStart, target.selectionEnd); } catch { return ''; }
  }
  return String(window.getSelection?.() || '');
}

function removeSelection(target) {
  if (inEditor(target)) {
    if (editor.getOption && editor.getRawOptions?.().readOnly) return;
    const model = editor.getModel();
    const edits = (editor.getSelections() || []).map((s) => ({
      range: s.isEmpty() ? { startLineNumber: s.startLineNumber, startColumn: 1, endLineNumber: Math.min(s.startLineNumber + 1, model.getLineCount()), endColumn: s.startLineNumber < model.getLineCount() ? 1 : model.getLineMaxColumn(s.startLineNumber) } : s,
      text: '' }));
    editor.pushUndoStop(); editor.executeEdits('cut', edits); editor.pushUndoStop();
  } else if (isField(target) && !target.readOnly && !target.disabled) {
    document.execCommand?.('delete');
  }
}

function onCopy(e) {
  if (!on) return;
  const text = selectedText(e.target);
  e.preventDefault(); e.stopImmediatePropagation();          // the editor's own copy handler must not run: it would write the real code
  if (!text) return;
  held = text;
  try { e.clipboardData?.setData('text/plain', NOTICE); } catch { /* nothing to do */ }
  if (e.type === 'cut') removeSelection(e.target);
  tell(e.type);
}

function onPaste(e) {
  if (!on) return;
  let text = '';
  try { text = e.clipboardData?.getData('text/plain') || ''; } catch { /* unreadable */ }
  if (text.trim() !== NOTICE || !held) return;                // came from another program: normal paste
  e.preventDefault(); e.stopImmediatePropagation();
  if (inEditor(e.target)) { editor.focus?.(); editor.trigger('keyboard', 'paste', { text: held }); }
  else if (isField(e.target)) document.execCommand?.('insertText', false, held);
}

function onDrag(e) {
  if (!on) return;
  const t = e.target;
  if (t?.nodeType === 3 || inEditor(t) || isField(t) || String(window.getSelection?.() || '')) { e.preventDefault(); tell('drag'); }
}

/** Copy button helper. Returns true when the text is available for pasting (inside WORKCODE when protected). */
export async function copyText(text) {
  if (on) {
    held = text;
    try { await navigator.clipboard.writeText(NOTICE); } catch { /* the paste shortcut then needs the notice; see pasteHeld */ }
    tell('copy');
    return true;
  }
  try { await navigator.clipboard.writeText(text); return true; } catch { /* blocked in some embedded pages */ }
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  return ok;
}

/** Switch protection on or off. Returns a function that removes it. */
export function installCopyGuard(enabled) {
  on = !!enabled;
  if (!on) { held = ''; return () => {}; }
  const opts = true;   // capture: run before the editor's handlers
  document.addEventListener('copy', onCopy, opts);
  document.addEventListener('cut', onCopy, opts);
  document.addEventListener('paste', onPaste, opts);
  document.addEventListener('dragstart', onDrag, opts);
  return () => {
    on = false; held = '';
    document.removeEventListener('copy', onCopy, opts);
    document.removeEventListener('cut', onCopy, opts);
    document.removeEventListener('paste', onPaste, opts);
    document.removeEventListener('dragstart', onDrag, opts);
  };
}

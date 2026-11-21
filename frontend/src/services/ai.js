import { rawRequest } from './api';

/** Reads "data: {...}" server-sent events from a text stream; returns the unfinished rest. */
export function readEvents(buffer, onEvent) {
  let rest = buffer;
  for (;;) {
    const cut = rest.indexOf('\n\n');
    if (cut < 0) return rest;
    const block = rest.slice(0, cut);
    rest = rest.slice(cut + 2);
    for (const line of block.split('\n')) {
      if (!line.startsWith('data:')) continue;
      try { onEvent(JSON.parse(line.slice(5).trim())); } catch { /* ignore a broken line */ }
    }
  }
}

/** POST a question and receive the answer piece by piece. Rejects with {message, status} when it cannot start. */
export async function streamChat(path, body, onEvent, signal) {
  const { url, headers } = rawRequest(path);
  let res;
  try { res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body), signal }); }
  catch (e) { if (e?.name === 'AbortError') return; throw { message: 'Cannot reach the server. Check that the backend is running.' }; }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { const d = (await res.json()).detail; if (typeof d === 'string') detail = d; else if (Array.isArray(d) && d[0]?.msg) detail = d[0].msg; } catch { /* not JSON */ }
    throw { message: detail, status: res.status };
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer = readEvents(buffer + decoder.decode(value, { stream: true }), onEvent);
    }
    readEvents(`${buffer}\n\n`, onEvent);
  } catch (e) { if (e?.name !== 'AbortError') throw { message: 'The connection was lost while the answer was being written.' }; }
}

const SHELL = ['bash', 'sh', 'shell', 'zsh', 'console', 'powershell', 'ps1', 'cmd', 'bat', 'terminal'];
export const isShell = (lang) => SHELL.includes((lang || '').toLowerCase());
const RISKY = [/\brm\s+(-[a-z]*\s+)*-?[a-z]*[rf]/i, /\brmdir\b/i, /\bdel\s+\/[sqf]/i, /\bformat\s+[a-z]:/i, /\bmkfs/i, /\bdd\s+if=/i, /\bdrop\s+(table|database)/i,
  /\btruncate\s+table/i, /git\s+reset\s+--hard/i, /git\s+clean\s+-[a-z]*f/i, /git\s+push\s+.*--force/i, /\bshutdown\b/i, /\breboot\b/i, />\s*\/dev\/sd/i,
  /\bchmod\s+-R\s+777/i, /curl[^|]*\|\s*(sudo\s+)?(ba)?sh/i, /\bsudo\b/i, /:\(\)\s*\{/];
/** True when a command can delete or overwrite data, or needs admin rights. Such commands need an extra confirmation. */
export const isRisky = (cmd) => RISKY.some((r) => r.test(cmd));

/** Splits an answer into text and code blocks. A block may carry `path=src/App.jsx`: then it is a whole proposed file. */
export function parseBlocks(markdown) {
  const out = [];
  const lines = (markdown || '').split('\n');
  let text = [];
  let code = null;
  const flush = () => { if (text.length && text.join('\n').trim()) out.push({ type: 'text', text: text.join('\n') }); text = []; };
  for (const line of lines) {
    if (code) {
      if (line.trimEnd() === code.fence || (line.startsWith(code.fence) && !line.slice(code.fence.length).trim())) { out.push({ ...code, code: code.lines.join('\n'), closed: true }); code = null; }
      else code.lines.push(line);
      continue;
    }
    const m = /^(`{3,}|~{3,})\s*([^\s`]*)\s*(.*)$/.exec(line);
    if (m) {
      flush();
      const info = m[3] || '';
      const path = /(?:path|file|filename)\s*[=:]\s*"?([^\s"`]+)"?/i.exec(info)?.[1] || (/^[\w@()[\].-]+(\/[\w@()[\].-]+)*\.[A-Za-z0-9]+$/.test(info.trim()) ? info.trim() : null);
      let lang = m[2] || '';
      let p = path;
      if (!p && /^(?:path|file)=/i.test(lang)) { p = lang.replace(/^(?:path|file)=/i, ''); lang = ''; }
      code = { type: 'code', fence: m[1], lang: lang.toLowerCase(), path: p ? p.replace(/^\.?\//, '') : null, lines: [] };
    } else text.push(line);
  }
  if (code) out.push({ ...code, code: code.lines.join('\n'), closed: false });
  flush();
  return out.map(({ lines: _l, fence: _f, ...b }) => b);
}

/** Whole-file blocks of an answer, one per path (the last one wins). */
export function proposedFiles(markdown) {
  const map = new Map();
  for (const b of parseBlocks(markdown)) if (b.type === 'code' && b.path && b.closed) map.set(b.path, b.code.endsWith('\n') ? b.code : `${b.code}\n`);
  return [...map].map(([path, content]) => ({ path, content }));
}

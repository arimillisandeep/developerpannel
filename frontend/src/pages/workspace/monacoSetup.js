// The Monaco editor engine is downloaded by @monaco-editor/react from the jsDelivr CDN the
// first time the workspace opens (the browser needs internet access for that).
// To serve it from your own server instead, see "Offline Monaco" in the README.
const LANG = { js: 'javascript', jsx: 'javascript', mjs: 'javascript', ts: 'typescript', tsx: 'typescript', py: 'python', java: 'java',
  c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', hpp: 'cpp', html: 'html', htm: 'html', css: 'css', json: 'json', md: 'markdown', sql: 'sql',
  sh: 'shell', yml: 'yaml', yaml: 'yaml', xml: 'xml', dart: 'dart', go: 'go', rs: 'rust', php: 'php' };
/** Language entry (from GET /api/languages) for a file path, or null. */
export const langOf = (path, langs = []) => {
  const name = path.split('/').pop().toLowerCase();
  if (name === 'dockerfile') return langs.find((l) => l.id === 'dockerfile') || null;
  if (!name.includes('.')) return null;
  const ext = name.split('.').pop();
  return langs.find((l) => l.extensions.includes(ext)) || null;
};
export const languageFor = (path, langs) => langOf(path, langs)?.monaco || LANG[path.split('.').pop().toLowerCase()] || 'plaintext';

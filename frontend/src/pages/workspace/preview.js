// Builds one self-contained HTML document from the project files, so the preview needs no network,
// and forwards console output / runtime errors from the sandboxed frame to the IDE.
const dirOf = (p) => (p.includes('/') ? p.slice(0, p.lastIndexOf('/') + 1) : '');

/** Resolve a relative reference such as "../css/a.css" against the folder of the HTML file. */
export function resolveRef(fromDir, ref) {
  const clean = ref.split(/[?#]/)[0];
  if (/^([a-z]+:)?\/\//i.test(clean) || clean.startsWith('data:')) return null;
  const parts = (clean.startsWith('/') ? clean.slice(1) : fromDir + clean).split('/');
  const out = [];
  for (const part of parts) {
    if (part === '..') out.pop(); else if (part && part !== '.') out.push(part);
  }
  return out.join('/');
}

const BRIDGE = (id) => `<script>(function(){var send=function(level,args){try{parent.postMessage({wcPreview:${JSON.stringify(id)},level:level,text:args.map(function(a){
if(a instanceof Error)return a.stack||a.message;if(typeof a==='object'){try{return JSON.stringify(a)}catch(e){return String(a)}}return String(a)}).join(' ')},'*')}catch(e){}};
['log','info','warn','error','debug'].forEach(function(l){var o=console[l];console[l]=function(){send(l,[].slice.call(arguments));o&&o.apply(console,arguments)}});
window.addEventListener('error',function(e){send('error',[(e.message||'Error')+(e.lineno?' (line '+e.lineno+')':'')])});
window.addEventListener('unhandledrejection',function(e){send('error',['Unhandled promise rejection: '+(e.reason&&e.reason.message||e.reason)])});})();</scr`+`ipt>`;

export function buildPreview(htmlFile, files, id = 'p') {
  const dir = dirOf(htmlFile.path);
  const find = (ref) => { const p = resolveRef(dir, ref); return p == null ? null : files.find((f) => f.path === p); };
  const esc = (s) => s.replace(/<\/script>/gi, '<\\/script>');
  let html = htmlFile.content
    .replace(/<link\b[^>]*\bhref=["']([^"']+)["'][^>]*>/gi, (m, href) => {
      if (!/rel=["']?stylesheet/i.test(m)) return m;
      const f = find(href); return f ? `<style>\n${f.content}\n</style>` : m; })
    .replace(/<script\b([^>]*)\bsrc=["']([^"']+)["']([^>]*)>\s*<\/script>/gi, (m, a, src, b) => {
      const f = find(src); return f ? `<script${a}${b}>\n${esc(f.content)}\n</script>` : m; });
  const bridge = BRIDGE(id);
  html = /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, (m) => m + bridge) : bridge + html;
  return html;
}

export const pickHtml = (active, files) => (active && /\.html?$/i.test(active.path) ? active
  : files.find((f) => /^index\.html?$/i.test(f.path)) || files.find((f) => /(^|\/)index\.html?$/i.test(f.path)) || null);

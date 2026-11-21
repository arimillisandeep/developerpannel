import { parseCode } from './classify.js';

const $ = (id) => document.getElementById(id);
const CATEGORY = { workcode: 'WORKCODE is in front', approved: 'Approved website', unapproved: 'Website not approved', unfocused: 'Browser not in front' };
const MODE = { RUNNING: ['Timer running', 'ok'], PAUSED_INACTIVE: ['Timer paused: no activity', 'warn'], PAUSED_EXTERNAL: ['Timer paused: not on an approved page', 'warn'],
  PAUSED_MANUAL: ['Timer paused by you', 'warn'], STOPPED: ['No running session in WORKCODE', 'warn'] };

async function render() {
  const { origin, token, last } = await chrome.storage.local.get(['origin', 'token', 'last']);
  const connected = !!(origin && token);
  $('connected').hidden = !connected;
  $('setup').hidden = connected;
  if (!connected) { $('error').textContent = last?.error || ''; return; }
  $('origin').textContent = new URL(origin).host;
  if (!last) { $('state').textContent = 'Waiting for the first report…'; return; }
  if (last.error) { $('state').textContent = last.error; $('state').className = 'bad'; }
  else {
    const [text, tone] = MODE[last.mode] || [last.mode, ''];
    $('state').textContent = `${text} · ${CATEGORY[last.category]}${last.domain ? ` (${last.domain})` : ''}`;
    $('state').className = tone;
  }
  $('when').textContent = `${last.meeting ? 'Meeting timer running · ' : ''}Last report ${new Date(last.at).toLocaleTimeString()}`;
}

$('connect').addEventListener('click', async () => {
  const parsed = parseCode($('code').value);
  if (!parsed) { $('error').textContent = 'This is not a WORKCODE connection code.'; return; }
  // Ask for access to the WORKCODE server only (needed to send the report).
  const granted = await chrome.permissions.request({ origins: [`${parsed.origin}/*`] });
  if (!granted) { $('error').textContent = 'Permission for the WORKCODE address was not granted.'; return; }
  await chrome.storage.local.remove(['config', 'configAt', 'last']);
  await chrome.storage.local.set(parsed);
  await chrome.runtime.sendMessage('report-now');
  render();
});

$('disconnect').addEventListener('click', async () => {
  const { origin } = await chrome.storage.local.get('origin');
  await chrome.storage.local.clear();
  if (origin) await chrome.permissions.remove({ origins: [`${origin}/*`] }).catch(() => {});
  render();
});

chrome.storage.onChanged.addListener(render);
render();

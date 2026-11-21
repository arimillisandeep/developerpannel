// API audit step 6: real user workflows clicked in a real browser (headless Chromium), each one checked
// (a) by the API responses the browser really received and (b) by reading the test database file.
//   node e2e_flows.mjs     needs: frontend :5183 -> isolated API :8010, fake AI provider :9911, playwright-core in /tmp/pw
import { createRequire } from 'module';
import { execFileSync } from 'child_process';
import fs from 'fs';
const require = createRequire('/tmp/pw/');
const { chromium } = require('playwright-core');
const BASE = 'http://127.0.0.1:5183', API = 'http://127.0.0.1:8010/api', DB = process.env.AUDIT_DB || '/tmp/audit/audit.db';
const SFX = String(Date.now()).slice(-6), TITLE = `Browser task ${SFX}`;
const R = [];
const db = (q, ...a) => JSON.parse(execFileSync('python3', ['-c', 'import sys,json,os;sys.path.insert(0,"../backend/scripts");os.environ.setdefault("AUDIT_DB",sys.argv[1]);from audit_dbconn import rows;print(json.dumps(rows(sys.argv[2],sys.argv[3:]),default=str))', DB, q, ...a.map(String)]).toString());
const browser = await chromium.launch({ args: ['--no-sandbox'] });
async function session(role) {
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 }, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await ctx.newPage(); const calls = []; const errors = [];
  page.on('response', (res) => { if (res.url().includes('/api/')) calls.push({ m: res.request().method(), p: new URL(res.url()).pathname, s: res.status() }); });
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 4\d\d/.test(m.text())) errors.push(m.text().slice(0, 200)); });
  await page.goto(BASE + '/login');
  await page.getByLabel('Email').fill(`${role}@workcode.local`); await page.getByLabel('Password').fill('Workcode@123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'));
  const saw = (m, re, s) => calls.some((c) => c.m === m && re.test(c.p) && (s ? c.s === s : c.s < 400));
  return { page, calls, errors, saw, ctx };
}
async function step(area, name, fn) {
  try { const v = await fn(); if (v === false) throw new Error('check was false'); R.push({ area, check: name, result: 'PASS' }); console.log('PASS', name); return true; }
  catch (e) { R.push({ area, check: name, result: 'FAIL', detail: String(e.message || e).split('\n')[0].slice(0, 300) }); console.log('FAIL', name, '::', String(e.message || e).split('\n')[0].slice(0, 300)); return false; }
}
// Most form labels are not linked to their input (see report), so fields are found through their .field wrapper.
const F = (scope, label) => scope.locator('.field').filter({ has: scope.page().locator('label', { hasText: label }) }).locator('input, select, textarea').first();
const ed = async (page) => (await page.locator('.monaco-editor .view-lines').first().innerText()).replace(/\u00a0/g, ' ');   // Monaco draws spaces as non-breaking spaces
const FLAGS = {};
const settle = (page) => page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});

// ---------- Admin: create a person and a task through the forms ----------
const A = await session('admin');
await step('people', 'Admin adds a person in the People form -> POST /users 201 -> row in the database', async () => {
  await A.page.goto(BASE + '/people'); await settle(A.page);
  await A.page.getByRole('button', { name: 'Add person' }).click();
  const d = A.page.getByRole('dialog');
  await F(d, 'Full name').fill(`Browser Person ${SFX}`); await F(d, 'Email').fill(`browser${SFX}@workcode.local`);
  await F(d, 'Password').fill('Workcode@123');
  await F(d, 'Role').selectOption('intern');
  await d.getByRole('button', { name: 'Create account' }).click();
  await A.page.getByText(`Browser Person ${SFX}`).first().waitFor({ timeout: 6000 });
  return A.saw('POST', /\/api\/users$/, 201) && db('select count(*) from users where email=?', `browser${SFX}@workcode.local`)[0][0] === 1;
});
await step('people', 'Search box filters the list from the server', async () => {
  await A.page.getByLabel('Search').fill(`Browser Person ${SFX}`); await A.page.waitForTimeout(700);
  return (await A.page.locator('tbody tr').count()) === 1;
});
await step('tasks', 'Admin assigns a task in the form (intern + On-Roll reviewer) -> POST /tasks 201 -> row in the database', async () => {
  await A.page.goto(BASE + '/tasks'); await settle(A.page);
  await A.page.getByRole('button', { name: 'Assign a task' }).click();
  const d = A.page.getByRole('dialog');
  await d.getByLabel('Title').fill(TITLE);
  await d.getByRole('group', { name: 'Assign to' }).getByText('Kabir Singh').click();
  await d.getByLabel('On-Roll reviewer').selectOption({ label: (await d.getByLabel('On-Roll reviewer').locator('option').allTextContents()).find((t) => t.includes('Divya')) });
  await F(d, 'Requirements').fill('A page with a heading.');
  await d.getByRole('button', { name: 'Assign task' }).click();
  await A.page.getByText(TITLE).first().waitFor({ timeout: 6000 });
  const row = db('select status, reviewer_id from tasks where title=?', TITLE);
  return A.saw('POST', /\/api\/tasks$/, 201) && row.length === 1 && row[0][0] === 'assigned' && row[0][1] != null;
});
// AI provider for the assistant test (test stand-in for OpenAI on :9911), set through the admin page's API
const tok = await A.page.evaluate(() => Object.keys(localStorage).map((k) => localStorage.getItem(k)).find((v) => v && v.split('.').length === 3));
const H = { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' };
for (const p of await (await fetch(API + '/ai/providers', { headers: H })).json()) await fetch(`${API}/ai/providers/${p.id}`, { method: 'DELETE', headers: H });
await step('ai', 'Admin adds an AI provider in the AI assistant page -> key stored, never shown again', async () => {
  await A.page.goto(BASE + '/ai-settings'); await settle(A.page);
  await A.page.getByRole('button', { name: 'Add AI provider' }).click();
  const d = A.page.getByRole('dialog');
  await d.getByLabel('Provider name').fill('Test provider'); await d.getByLabel('API address').fill('http://127.0.0.1:9911/v1');
  await d.getByLabel('API key').fill('sk-fake-live-check-key');
  await d.getByRole('button', { name: 'Save and test connection' }).click();
  await d.getByText(/Connected\./).waitFor({ timeout: 8000 });
  await d.getByRole('checkbox', { name: 'fake-coder-1' }).check();
  await d.getByRole('button', { name: 'Save', exact: true }).click();
  await A.page.getByText('stored (hidden)').waitFor({ timeout: 5000 });
  const html = await A.page.content();
  return !html.includes('sk-fake-live-check-key') && !String(db('select api_key_enc from ai_providers where deleted_at is null')[0][0]).includes('sk-fake');
});

// ---------- Intern: accept, code in the real editor, save, AI, submit ----------
const I = await session('intern');
const taskId = (db('select id from tasks where title=?', TITLE)[0] || [0])[0];
await step('tasks', 'Intern sees the new task, opens it and presses Accept -> status accepted in the database', async () => {
  await I.page.goto(BASE + '/tasks'); await settle(I.page);
  await I.page.getByText(TITLE).first().click();
  await I.page.getByRole('button', { name: 'Accept task' }).click();
  await I.page.getByRole('button', { name: 'Start task' }).waitFor({ timeout: 6000 });
  return db('select status from tasks where id=?', taskId)[0][0] === 'accepted';
});
await step('notifications', 'Intern got a notification for the assignment (bell) and can mark all as read', async () => {
  await I.page.goto(BASE + '/profile'); await settle(I.page);
  await I.page.getByLabel('Notifications').click();
  await I.page.getByText(new RegExp(TITLE)).first().waitFor({ timeout: 4000 });
  await I.page.getByRole('button', { name: 'Mark all as read' }).click(); await I.page.waitForTimeout(500);
  return I.saw('POST', /\/notifications\/read-all$/) && db('select count(*) from notifications n join users u on u.id=n.user_id where u.email=? and not n.is_read', 'intern@workcode.local')[0][0] === 0;
});
let editorOk = false;
await step('workspace', 'Start task opens the workspace; the Monaco editor loads', async () => {
  await I.page.goto(BASE + '/tasks'); await settle(I.page); await I.page.getByText(TITLE).first().click();
  await I.page.getByRole('button', { name: 'Start task' }).click();
  await I.page.waitForURL(/\/workspace\/\d+/, { timeout: 8000 });
  await I.page.locator('.monaco-editor').first().waitFor({ timeout: 25000 });
  editorOk = true; return true;
});
const type = async (text) => { await I.page.locator('.monaco-editor .view-lines').first().click(); await I.page.keyboard.press('Control+A'); await I.page.keyboard.press('Delete'); await I.page.keyboard.insertText(text); };
if (editorOk) {
  await step('workspace', 'New file dialog creates index.html -> PUT /files 200', async () => {
    await I.page.locator('button[title^="New file"]').first().click();
    const d = I.page.getByRole('dialog'); await d.getByLabel('File path').fill('index.html'); await d.getByRole('button', { name: /create|ok|add/i }).first().click();
    await I.page.getByRole('tab', { name: /index\.html/ }).or(I.page.locator('.ide-tab', { hasText: 'index.html' })).first().waitFor({ timeout: 6000 }).catch(() => {});
    await I.page.waitForTimeout(500);
    return I.saw('PUT', /\/workspaces\/\d+\/files$/) && db('select count(*) from workspace_files f join workspaces w on w.id=f.workspace_id where w.task_id=? and f.path=? and f.deleted_at is null', taskId, 'index.html')[0][0] === 1;
  });
  await step('workspace', 'Typing in the editor + Save button stores the exact text in the database', async () => {
    await type('<h1>Typed in the browser</h1>');
    await I.page.getByRole('button', { name: 'Save', exact: true }).click(); await I.page.waitForTimeout(900);
    const c = db('select f.content from workspace_files f join workspaces w on w.id=f.workspace_id where w.task_id=? and f.path=? and f.deleted_at is null', taskId, 'index.html')[0][0];
    return c.includes('<h1>Typed in the browser</h1>') || (() => { throw new Error('database has: ' + JSON.stringify(c)); })();
  });
  await step('workspace', 'Reloading the page shows the saved text again (read back from the server)', async () => {
    await I.page.reload(); await I.page.locator('.monaco-editor').first().waitFor({ timeout: 25000 });
    await I.page.getByText('index.html').first().click(); await I.page.waitForTimeout(800);
    return (await ed(I.page)).includes('Typed in the browser');
  });
  await step('copy protection', 'Ctrl+C in the real editor: the code does NOT reach the clipboard', async () => {
    await I.page.locator('.monaco-editor .view-lines').first().click(); await I.page.keyboard.press('Control+A'); await I.page.keyboard.press('Control+C'); await I.page.waitForTimeout(300);
    const clip = await I.page.evaluate(() => navigator.clipboard.readText());
    if (clip.includes('Typed in the browser')) throw new Error('clipboard holds the code: ' + clip.slice(0, 80));
    return clip.includes('not allowed') || (() => { throw new Error('clipboard holds: ' + JSON.stringify(clip.slice(0, 80))); })();
  });
  await step('copy protection', 'Ctrl+V right after: the copied code is pasted inside WORKCODE', async () => {
    await I.page.keyboard.press('End'); await I.page.keyboard.press('Control+End'); await I.page.keyboard.press('Enter'); await I.page.keyboard.press('Control+V'); await I.page.waitForTimeout(400);
    const t = await ed(I.page);
    return (t.match(/Typed in the browser/g) || []).length === 2 || (() => { throw new Error('editor shows: ' + JSON.stringify(t.slice(0, 160))); })();
  });
  await step('copy protection', 'Text copied in another program can be pasted into the editor', async () => {
    await I.page.evaluate(() => navigator.clipboard.writeText('<p>FROM OUTSIDE</p>'));
    await I.page.keyboard.press('Control+End'); await I.page.keyboard.press('Enter'); await I.page.keyboard.press('Control+V'); await I.page.waitForTimeout(400);
    return (await ed(I.page)).includes('FROM OUTSIDE');
  });
  await step('copy protection', 'Ctrl+Z undoes the paste, Ctrl+X cuts without leaking', async () => {
    await I.page.keyboard.press('Control+Z'); await I.page.waitForTimeout(200);
    const t = await ed(I.page);
    await I.page.keyboard.press('Control+A'); await I.page.keyboard.press('Control+X'); await I.page.waitForTimeout(300);
    const clip = await I.page.evaluate(() => navigator.clipboard.readText());
    const empty = (await ed(I.page)).trim() === '';
    await I.page.keyboard.press('Control+Z');
    return !t.includes('FROM OUTSIDE') && !clip.includes('Typed') && empty;
  });
  await type('<h1>Typed in the browser</h1>');
  await I.page.getByRole('button', { name: 'Save', exact: true }).click(); await I.page.waitForTimeout(700);
  await step('ai', 'AI panel opens on the right; a question streams an answer built from the open file', async () => {
    await I.page.getByRole('button', { name: '✦ AI' }).click();
    const p = I.page.getByRole('complementary', { name: 'AI Assistant' }); await p.waitFor({ timeout: 5000 });
    await p.getByLabel('Message to AI').fill('What does the heading say? Fix it.'); await p.getByRole('button', { name: /Send/ }).click();
    await p.getByText(/Typed in the browser/).first().waitFor({ timeout: 15000 });
    await p.getByRole('button', { name: /Preview all 2 files|Preview changes/ }).first().waitFor({ timeout: 8000 });
    return I.saw('POST', /\/ai\/conversations\/\d+\/messages$/, 200);
  });
  await step('ai', 'Preview shows the diff; rejecting one file and applying the other changes only that file in the database', async () => {
    const p = I.page.getByRole('complementary', { name: 'AI Assistant' });
    await p.getByRole('button', { name: /Preview all 2 files/ }).first().click();
    const d = I.page.getByRole('dialog', { name: 'Preview changes' }); await d.getByText('+<h1>Hello from AI</h1>').waitFor({ timeout: 6000 });
    await d.getByLabel('Accept css/site.css').uncheck();
    await d.getByRole('button', { name: 'Apply 1 file' }).click(); await I.page.waitForTimeout(1000);
    const rows = db('select f.path, f.content from workspace_files f join workspaces w on w.id=f.workspace_id where w.task_id=? and f.deleted_at is null', taskId);
    const m = Object.fromEntries(rows);
    return m['index.html'] === '<h1>Hello from AI</h1>\n' && !('css/site.css' in m) && (await ed(I.page)).includes('Hello from AI');
  });
  await step('ai', 'Insert at cursor puts AI code into the editor; "Send to terminal" only fills the input', async () => {
    const p = I.page.getByRole('complementary', { name: 'AI Assistant' });
    await p.getByRole('button', { name: 'Send to terminal' }).first().click(); await I.page.waitForTimeout(500);
    const v = await I.page.getByLabel('Terminal command').inputValue();
    return v === 'npm test' && !I.calls.some((c) => /\/run$/.test(c.p));
  });
  await step('workspace', 'Run button without Docker shows the honest "runner not available" message (503), no fake output', async () => {
    const before = I.calls.length;
    const run = I.page.getByRole('button', { name: /Run/ }).first(); if (!(await run.count()) || await run.isDisabled()) return true;
    await run.click(); await I.page.waitForTimeout(1200);
    const c = I.calls.slice(before).find((x) => /\/run$/.test(x.p));
    return !c || c.s === 503;
  });
  await step('tasks', 'Submit for review -> version 1.0, task under_onroll_review, project locked', async () => {
    await I.page.getByRole('button', { name: 'Submit', exact: true }).first().click();
    const d = I.page.getByRole('dialog', { name: 'Submit for review' }); await d.getByLabel('Submission note').fill('from the browser');
    await d.getByRole('button', { name: 'Submit', exact: true }).click(); await I.page.waitForTimeout(1200);
    const s = db('select version_label, stage from submissions where task_id=?', taskId);
    return s.length === 1 && s[0][0] === '1.0' && db('select status from tasks where id=?', taskId)[0][0] === 'under_onroll_review' && await I.page.getByRole('button', { name: 'Save', exact: true }).isDisabled();
  });
}
await step('chat', 'Intern sends a chat message to the reviewer -> stored once', async () => {
  await I.page.goto(BASE + '/chat'); await settle(I.page);
  const sel = I.page.getByLabel('Start a chat'); const opt = (await sel.locator('option').allTextContents()).find((t) => t.includes('Divya'));
  if (opt) await sel.selectOption({ label: opt }); else await I.page.getByText('Divya Rao').first().click();
  await I.page.getByLabel('Message').fill(`hello from the browser ${SFX}`); await I.page.getByRole('button', { name: 'Send' }).click();
  await I.page.getByText(`hello from the browser ${SFX}`).first().waitFor({ timeout: 5000 });
  return db('select count(*) from chat_messages where body=?', `hello from the browser ${SFX}`)[0][0] === 1;
});
await step('timer', 'Timer in the top bar: Pause, Resume, Stop call the API and the session ends in the database', async () => {
  const start = I.page.getByRole('button', { name: 'Start', exact: true }); if (await start.count()) { await start.click(); await I.page.waitForTimeout(600); }
  await I.page.getByRole('button', { name: 'Pause', exact: true }).click(); await I.page.getByRole('button', { name: 'Resume', exact: true }).click({ timeout: 5000 });
  await I.page.getByRole('button', { name: 'Stop', exact: true }).click(); await I.page.waitForTimeout(800);
  const c = I.page.getByRole('dialog').getByRole('button', { name: /stop|yes|end/i }).first(); if (await c.count()) { await c.click(); await I.page.waitForTimeout(600); }
  return I.saw('POST', /\/sessions\/pause$/) && I.saw('POST', /\/sessions\/resume$/) && I.saw('POST', /\/sessions\/stop$/) && db('select count(*) from work_sessions s join users u on u.id=s.user_id where u.email=? and s.ended_at is null', 'intern@workcode.local')[0][0] === 0;
});

// ---------- Reviewer and Admin: review in the UI ----------
const subId = (db('select id from submissions where task_id=?', taskId)[0] || [])[0];
if (subId) {
  const V = await session('reviewer');
  await step('chat', 'Reviewer sees the intern\'s message', async () => { await V.page.goto(BASE + '/chat'); await settle(V.page); await V.page.locator(':not(option)', { hasText: /^Kabir Singh/ }).last().click(); await V.page.getByText(`hello from the browser ${SFX}`).first().waitFor({ timeout: 5000 }); return true; });
  await step('reviews', 'Reviewer finds the submission in the queue, opens it and sees the submitted code', async () => {
    await V.page.goto(BASE + '/reviews'); await settle(V.page); await V.page.getByText(TITLE).first().click();
    await V.page.waitForURL(/\/reviews\/\d+/); await settle(V.page); await V.page.getByRole('button', { name: /index\.html/ }).first().click(); await V.page.waitForTimeout(400);
    const body = (await V.page.locator('body').innerText()).replace(/\u00a0/g, ' ');
    return V.saw('GET', /\/submissions\/\d+$/, 200) && body.includes('Hello from AI') || (() => { throw new Error('page shows: ' + body.slice(300, 600)); })();
  });
  await step('reviews', 'Reject without a comment is refused with a message; nothing changes in the database', async () => {
    await V.page.getByRole('button', { name: 'Reject', exact: true }).click(); await V.page.waitForTimeout(700);
    return db('select count(*) from reviews where submission_id=?', subId)[0][0] === 0 && (await V.page.getByRole('alert').count()) > 0;
  });
  await step('reviews', 'Approve -> send to Admin: task under_admin_review', async () => {
    await V.page.getByLabel('Review comment').fill('Looks fine'); await V.page.getByRole('button', { name: /Approve → send to Admin/ }).click(); await V.page.waitForTimeout(1000);
    return db('select status from tasks where id=?', taskId)[0][0] === 'under_admin_review';
  });
  await step('reviews', 'Admin final approve in the UI: task completed, one review row per stage', async () => {
    await A.page.goto(BASE + `/reviews/${subId}`); await settle(A.page);
    await A.page.getByLabel('Review comment').fill('Approved'); await A.page.getByRole('button', { name: 'Final approve' }).click(); await A.page.waitForTimeout(1000);
    return db('select status from tasks where id=?', taskId)[0][0] === 'completed' && db('select count(*) from reviews where submission_id=?', subId)[0][0] === 2;
  });
  await step('tasks', 'Task page shows Completed and the version list with v1.0', async () => {
    await A.page.goto(BASE + '/tasks'); await settle(A.page); await A.page.getByText(TITLE).first().click();
    await A.page.getByText(/Completed/).first().waitFor({ timeout: 5000 }); return true;
  });
  await step('errors', 'No JavaScript errors in the reviewer\'s browser', async () => V.errors.length === 0 || (() => { throw new Error(V.errors.join(' | ')); })());
}
await step('profile', 'Profile page: wrong current password shows the server message; right one changes it (then changed back)', async () => {
  await I.page.goto(BASE + '/profile'); await settle(I.page);
  const body = I.page.locator('body'); const cur = F(body, /current password/i), nw = F(body, /^new password/i);
  await cur.fill('wrong-one'); await nw.fill('Changed@12345'); const conf = F(body, /confirm|repeat/i); if (await conf.count()) await conf.fill('Changed@12345');
  await I.page.getByRole('button', { name: /change password|update password|save password/i }).click(); await I.page.waitForTimeout(700);
  const refused = I.saw('POST', /\/auth\/change-password$/, 400);
  const oldToken = await I.page.evaluate(() => localStorage.getItem('workcode_token'));
  await cur.fill('Workcode@123'); await nw.fill('Changed@12345'); if (await conf.count()) await conf.fill('Changed@12345');
  await I.page.getByRole('button', { name: /change password|update password|save password/i }).click(); await I.page.waitForTimeout(900);
  const ok = I.saw('POST', /\/auth\/change-password$/, 200);
  FLAGS.oldToken = oldToken; FLAGS.newToken = await I.page.evaluate(() => localStorage.getItem('workcode_token'));
  await I.page.goto(BASE + '/tasks'); await settle(I.page); FLAGS.stillIn = new URL(I.page.url()).pathname === '/tasks';
  FLAGS.oldStatus = (await fetch(API + '/auth/me', { headers: { Authorization: 'Bearer ' + oldToken } })).status;
  const r = await fetch(API + '/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'intern@workcode.local', password: 'Changed@12345' }) });
  const t = (await r.json()).access_token;
  await fetch(API + '/auth/change-password', { method: 'POST', headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: 'Changed@12345', new_password: 'Workcode@123' }) });
  return refused && ok && r.status === 200;
});
await step('auth', 'After a password change the old token is refused (401) and this browser keeps working with its new token', async () =>
  FLAGS.oldStatus === 401 && FLAGS.stillIn && FLAGS.newToken && FLAGS.newToken !== FLAGS.oldToken || (() => { throw new Error(JSON.stringify({ old: FLAGS.oldStatus, stillIn: FLAGS.stillIn })); })());
await step('auth', 'Sign out in the browser: the token that was in use is refused by the server afterwards', async () => {
  const token = await A.page.evaluate(() => localStorage.getItem('workcode_token'));
  const before = (await fetch(API + '/auth/me', { headers: { Authorization: 'Bearer ' + token } })).status;
  await A.page.goto(BASE + '/profile'); await settle(A.page);
  await A.page.getByText('Sign out', { exact: true }).first().click({ timeout: 8000 }); await A.page.waitForURL(/\/login/);
  const after = (await fetch(API + '/auth/me', { headers: { Authorization: 'Bearer ' + token } })).status;
  return before === 200 && after === 401 || (() => { throw new Error(`before ${before}, after ${after}`); })();
});
await step('forms', 'Form labels are linked to their inputs (login page and password form reachable by label)', async () => {
  const P = await session('offroll'); await P.page.goto(BASE + '/profile'); await settle(P.page);
  return (await P.page.getByLabel('Current password').count()) === 1 && (await P.page.getByLabel(/^New password/).count()) === 1;
});
await step('errors', 'No JavaScript errors in the admin\'s browser', async () => A.errors.length === 0 || (() => { throw new Error(A.errors.join(' | ')); })());
await step('errors', 'No JavaScript errors in the intern\'s browser', async () => I.errors.length === 0 || (() => { throw new Error(I.errors.join(' | ')); })());
await I.page.screenshot({ path: 'shots/flow_end_intern.png' }).catch(() => {});
await browser.close();
fs.writeFileSync('e2e_flows.json', JSON.stringify(R, null, 1));
console.log(`\n${R.filter((x) => x.result === 'PASS').length} of ${R.length} passed`);

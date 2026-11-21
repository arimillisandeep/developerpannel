// API audit step 5: a REAL browser (headless Chromium) logs in as every role and opens every page in the menu.
// It records every /api request the pages really send, the status that came back, console errors and page crashes.
//   node e2e_sweep.mjs            (needs: frontend on :5183 proxying to the isolated API on :8010, playwright-core in /tmp/pw)
import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire('/tmp/pw/');
const { chromium } = require('playwright-core');
const BASE = process.env.AUDIT_WEB || 'http://127.0.0.1:5183';
const ROLES = ['admin', 'reviewer', 'onroll', 'offroll', 'intern'];
const norm = (u) => new URL(u).pathname.replace(/\/\d+(?=\/|$)/g, '/{id}');
const out = { roles: {}, calls: {} };
const browser = await chromium.launch({ args: ['--no-sandbox'] });
for (const role of ROLES) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const r = { pages: [], consoleErrors: [], pageErrors: [], failed: [], noAuthHeader: [] };
  let where = 'login';
  page.on('console', (m) => { if (m.type() === 'error') r.consoleErrors.push(`[${where}] ${m.text().slice(0, 200)}`); });
  page.on('pageerror', (e) => r.pageErrors.push(`[${where}] ${String(e).slice(0, 200)}`));
  page.on('websocket', (ws) => { const key = 'WS ' + new URL(ws.url()).pathname; out.calls[key] = out.calls[key] || { statuses: {}, pages: [] }; out.calls[key].statuses.open = (out.calls[key].statuses.open || 0) + 1; ws.on('socketerror', (e) => r.failed.push(`[${where}] ${key} ${e}`)); });
  page.on('response', async (res) => {
    const u = res.url(); if (!u.includes('/api/')) return;
    const req = res.request(); const key = `${req.method()} ${norm(u)}`;
    const c = out.calls[key] = out.calls[key] || { statuses: {}, pages: [] };
    c.statuses[res.status()] = (c.statuses[res.status()] || 0) + 1;
    if (!c.pages.includes(`${role}:${where}`)) c.pages.push(`${role}:${where}`);
    const h = req.headers();
    if (!h.authorization && !u.endsWith('/auth/login') && !u.includes('/debug/client')) r.noAuthHeader.push(`[${where}] ${key}`);
    if (res.status() >= 400 && !(where === 'login-wrong' && res.status() === 401)) r.failed.push(`[${where}] ${key} -> ${res.status()}`);
  });
  page.on('requestfailed', (req) => { if (req.url().includes('/api/')) r.failed.push(`[${where}] ${req.method()} ${norm(req.url())} FAILED ${req.failure()?.errorText}`); });

  await page.goto(BASE + '/login');
  where = 'login-wrong';
  await page.getByLabel('Email').fill(`${role}@workcode.local`); await page.getByLabel('Password').fill('wrong-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('alert').first().waitFor({ timeout: 5000 }).catch(() => {});
  r.wrongPasswordMessage = await page.getByRole('alert').first().textContent().catch(() => null);
  where = 'login';
  await page.getByLabel('Password').fill('Workcode@123');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 10000 });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1500);   // the dashboard is drawn without a page load, so 'networkidle' is already true: give its first requests time to finish
  r.landed = new URL(page.url()).pathname;
  const links = await page.$$eval('nav a[href], aside a[href]', (as) => [...new Set(as.map((a) => a.getAttribute('href')))].filter((h) => h && h.startsWith('/')));
  r.menu = links;
  for (const href of links) {
    where = href;
    await page.goto(BASE + href); await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(400);
    const text = (await page.locator('body').innerText()).slice(0, 4000);
    const crashed = /Something went wrong|Cannot read prop|is not a function|undefined is not/.test(text);
    const empty = text.replace(/\s/g, '').length < 40;
    r.pages.push({ href, ok: !crashed && !empty, h1: await page.locator('h1').first().textContent().catch(() => '') });
    if (role === 'admin' || href === '/workspace' || href === '/tasks') await page.screenshot({ path: `shots/${role}${href.replace(/\//g, '_')}.png` }).catch(() => {});
  }
  // pages of other roles typed into the address bar: the app must not show them or call their APIs successfully
  where = 'forbidden-url';
  if (role !== 'admin') {
    const before = r.failed.length;
    for (const href of ['/people', '/audit', '/ai-settings', '/monitoring']) {
      await page.goto(BASE + href); await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
      r.pages.push({ href: 'typed ' + href, ok: new URL(page.url()).pathname !== href, h1: new URL(page.url()).pathname });
    }
    r.forbiddenCalls = r.failed.slice(before);
  }
  // logout through the UI
  where = 'logout';
  await page.goto(BASE + '/profile'); await page.waitForLoadState('networkidle').catch(() => {});
  const lo = page.getByRole('button', { name: /log ?out|sign ?out/i }).first();
  if (await lo.count()) { await lo.click(); await page.waitForURL((u) => u.pathname.startsWith('/login'), { timeout: 8000 }).catch(() => {}); }
  r.loggedOut = new URL(page.url()).pathname.startsWith('/login');
  r.tokenGone = await page.evaluate(() => !Object.keys(localStorage).concat(Object.keys(sessionStorage)).some((k) => /token/i.test(k) && (localStorage.getItem(k) || sessionStorage.getItem(k))));
  await page.goto(BASE + '/tasks'); await page.waitForTimeout(600);
  r.protectedAfterLogout = new URL(page.url()).pathname.startsWith('/login');
  out.roles[role] = r;
  await ctx.close();
  console.log(role, 'landed', r.landed, '| pages', r.pages.filter((p) => p.ok).length + '/' + r.pages.length, '| failed api', r.failed.length, '| console errors', r.consoleErrors.length, '| crashes', r.pageErrors.length, '| no auth header', r.noAuthHeader.length, '| logout', r.loggedOut, r.tokenGone, r.protectedAfterLogout);
  for (const x of [...r.failed, ...r.consoleErrors, ...r.pageErrors, ...r.noAuthHeader, ...r.pages.filter((p) => !p.ok).map((p) => 'PAGE ' + JSON.stringify(p))].slice(0, 14)) console.log('   ', x);
}
await browser.close();
fs.writeFileSync('e2e_sweep.json', JSON.stringify(out, null, 1));
console.log('distinct API calls seen in the browser:', Object.keys(out.calls).length);

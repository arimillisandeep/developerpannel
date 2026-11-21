import test from 'node:test';
import assert from 'node:assert/strict';
import { classify, isMeetingTab, openMeetings, parseCode } from './classify.js';

const approved = [{ domain: 'meet.google.com', ignore_inactivity: true }, { domain: 'chatgpt.com' }, { domain: 'www.chatgpt.com' }];
const at = (url, focused = true) => classify({ focused, url, workcodeHost: 'localhost:5173', approved });

test('WORKCODE itself', () => {
  assert.deepEqual(at('http://localhost:5173/intern'), { category: 'workcode', domain: null });
  assert.equal(at('http://localhost:3000/').category, 'unapproved');           // another local app is not WORKCODE
});
test('approved websites', () => {
  assert.deepEqual(at('https://meet.google.com/abc-defg-hij'), { category: 'approved', domain: 'meet.google.com' });
  assert.deepEqual(at('https://chatgpt.com/c/1'), { category: 'approved', domain: 'chatgpt.com' });
  assert.equal(at('https://www.chatgpt.com/').category, 'approved');
});
test('everything else pauses and its address is not kept', () => {
  for (const url of ['https://youtube.com/watch?v=1', 'https://mail.google.com/', 'https://evil-chatgpt.com/', 'https://chatgpt.com.evil.io/',
    'chrome://newtab/', 'file:///C:/x.html', '', undefined]) {
    assert.deepEqual(at(url), { category: 'unapproved', domain: null }, String(url));
  }
});
test('browser not in front', () => {
  assert.deepEqual(at('https://chatgpt.com/', false), { category: 'unfocused', domain: null });
});
test('connection code', () => {
  assert.deepEqual(parseCode(' http://localhost:5173|a.b.c \n'), { origin: 'http://localhost:5173', token: 'a.b.c' });
  for (const bad of ['', 'a.b.c', 'ftp://x|a.b.c', 'http://x|abc', 'nonsense|a.b.c']) assert.equal(parseCode(bad), null, bad);
});

test('meeting tab: Google Meet by meeting code', () => {
  const link = 'https://meet.google.com/abc-defg-hij';
  assert.equal(isMeetingTab(link, 'https://meet.google.com/abc-defg-hij?authuser=1'), true);
  assert.equal(isMeetingTab(link, 'https://meet.google.com/ABC-defg-hij'), true);
  assert.equal(isMeetingTab(link, 'https://meet.google.com/xyz-defg-hij'), false);      // someone else's meeting
  assert.equal(isMeetingTab(link, 'https://meet.google.com/'), false);                  // Meet home page
  assert.equal(isMeetingTab(link, 'https://evil.example/abc-defg-hij'), false);
});
test('meeting tab: Zoom by meeting number, web client included', () => {
  const link = 'https://us05web.zoom.us/j/81234567890?pwd=abc';
  assert.equal(isMeetingTab(link, 'https://us05web.zoom.us/j/81234567890?pwd=abc#success'), true);
  assert.equal(isMeetingTab(link, 'https://app.zoom.us/wc/81234567890/join?fromPWA=1'), true);
  assert.equal(isMeetingTab(link, 'https://zoom.us/j/89999999999'), false);
  assert.equal(isMeetingTab(link, 'https://zoom.us/profile'), false);
});
test('meeting tab: Teams by site, other services by path', () => {
  const teams = 'https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0';
  assert.equal(isMeetingTab(teams, 'https://teams.microsoft.com/v2/?meetingjoin=true'), true);
  assert.equal(isMeetingTab(teams, 'https://teams.live.com/meet/9412345'), true);
  assert.equal(isMeetingTab(teams, 'https://outlook.office.com/mail'), false);
  assert.equal(isMeetingTab('https://meet.jit.si/TeamRoom', 'https://meet.jit.si/TeamRoom#config'), true);
  assert.equal(isMeetingTab('https://meet.jit.si/TeamRoom', 'https://meet.jit.si/TeamRoomTwo'), false);
  assert.equal(isMeetingTab('https://meet.jit.si/TeamRoom', 'chrome://newtab/'), false);
  assert.equal(isMeetingTab('not a link', 'https://meet.jit.si/TeamRoom'), false);
});
test('open meetings: only ids are produced, from any tab', () => {
  const meetings = [{ id: 7, link: 'https://meet.google.com/abc-defg-hij' }, { id: 9, link: 'https://zoom.us/j/81234567890' }];
  assert.deepEqual(openMeetings(meetings, ['https://mail.google.com/', 'https://meet.google.com/abc-defg-hij', undefined]), [7]);
  assert.deepEqual(openMeetings(meetings, ['https://www.youtube.com/']), []);
  assert.deepEqual(openMeetings([], ['https://meet.google.com/abc-defg-hij']), []);
});

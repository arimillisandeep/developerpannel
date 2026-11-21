import { StrictMode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// ---- fake backend -------------------------------------------------------
const state = { user: null, calls: [], handlers: {} };
const USERS = {
  admin: { id: 1, full_name: 'Arun Kumar', role: 'admin', email: 'a@x.io', teams: [] },
  developer: { id: 2, full_name: 'Divya Rao', role: 'developer', email: 'd@x.io', employee_code: 'WC-E0002', teams: [] },
  onroll: { id: 3, full_name: 'Ravi Teja', role: 'onroll', email: 'o@x.io', employee_code: 'WC-E0003', teams: [] },
  offroll: { id: 4, full_name: 'Sandeep K', role: 'offroll', email: 'f@x.io', employee_code: 'WC-E0004', teams: [] },
  intern: { id: 5, full_name: 'Kabir Singh', role: 'intern', email: 'i@x.io', employee_code: 'WC-E0005', teams: [] },
};
const counts = { total: 2, by_status: { assigned: 1, completed: 1 }, pending: 1, under_review: 0, completed: 1, rejected: 0 };
const hours = { today: 1, week: 2, month: 3, range_total: 4, daily: [{ day: '2026-11-11', hours: 1 }, { day: '2026-11-12', hours: 2 }] };
const TASK = { id: 7, code: 'WC-0007', title: 'Build page', status: 'in_progress', review_status: 'none', priority: 'high',
  assigned_to: 5, assigned_to_name: 'Kabir Singh', assigned_by: 1, assigned_by_name: 'Arun Kumar', deadline: '2026-12-01' };
const SESSION = { session: { id: 1, state: 'running', client_state: 'active', active_seconds: 65, away_seconds: 0, idle_seconds: 0,
  started_at: new Date(Date.now() - 600000).toISOString(), last_return_at: null, schedule: 'regular' }, is_reporting_tab: true,
  last_logout_at: new Date(2026, 10, 11, 21, 0, 0).toISOString(),
  heartbeat_seconds: 15, today: { active_seconds: 65, away_seconds: 0, paused_seconds: 0, extra_seconds: 0 },
  schedule_target_seconds: 28800, regular_completed: false, regular_completed_at: null,
  regular_remaining_seconds: 28735, extra_seconds_today: 0 };

function respond(method, url, body) {
  state.calls.push({ method, url, body });
  for (const [key, fn] of Object.entries(state.handlers)) {
    const [m, u] = key.split(' ');
    if (m === method && url.startsWith(u)) return fn(body);
  }
  const role = state.user?.role;
  const table = {
    'get /auth/me': () => state.user,
    'post /sessions/': () => SESSION,
    'get /notifications': () => ({ unread: 1, items: [{ id: 1, title: 'New task: Build page', is_read: false, created_at: '2026-11-12T10:00:00Z', link: '/tasks/7' }] }),
    'get /submissions': () => [],
    'get /chat/conversations/4/messages': () => ({ messages: [{ id: 1, conversation_id: 4, sender_id: 2, sender: 'Divya Rao', body: 'Welcome!', created_at: '2026-11-12T10:00:00Z' }], read_by_all_up_to: 0 }),
    'get /chat/conversations': () => [{ id: 4, kind: 'direct', title: 'Divya Rao', unread: 2, can_post: true, members: [{ id: 2, full_name: 'Divya Rao' }], last_message: 'Welcome!' }],
    'get /chat/contacts': () => [{ id: 2, full_name: 'Divya Rao', role: 'developer' }],
    'post /chat/conversations/4/messages': (b) => ({ id: 2, ...b }),
    'post /meetings/timer/ping': () => state.meetingTimer,
    'post /meetings/1/join': () => { state.meetingTimer = { current: { id: 3, meeting_id: 1, title: 'Sprint planning', joined_at: new Date().toISOString(), left_at: null, seconds: 65, source: 'manual', end_reason: null }, today_seconds: 65 }; return state.meetingTimer; },
    'post /meetings/1/leave': () => { state.meetingTimer = { current: null, today_seconds: 65 }; return state.meetingTimer; },
    'get /meetings/timer/report': () => ({ start: '2026-11-12', end: '2026-11-12', rows: [
      { user_id: 5, full_name: 'Kabir Singh', role: 'intern', work_seconds: 7200, meeting_seconds: 1830, meetings: 1, joins: 2,
        in_meeting: { id: 2, meeting_id: 1, title: 'Sprint planning', seconds: 600 },
        stays: [{ id: 1, meeting_id: 1, title: 'Sprint planning', joined_at: '2026-11-12T10:00:00Z', left_at: '2026-11-12T10:20:30Z', seconds: 1230, source: 'extension', end_reason: 'tab_closed' },
          { id: 2, meeting_id: 1, title: 'Sprint planning', joined_at: '2026-11-12T10:30:00Z', left_at: null, seconds: 600, source: 'manual', end_reason: null }] },
      { user_id: 6, full_name: 'Meena R', role: 'onroll', work_seconds: 3600, meeting_seconds: 0, meetings: 0, joins: 0, in_meeting: null, stays: [] }] }),
    'get /meetings/invitable': () => (['admin', 'developer', 'onroll'].includes(role) ? [{ id: 5, full_name: 'Kabir Singh', role: 'intern' }] : []),
    'get /meetings': () => [{ id: 1, title: 'Sprint planning', starts_at: new Date(Date.now() + 3600000).toISOString(), duration_minutes: 30, link: 'https://meet.google.com/x', created_by_name: 'Divya Rao', participants: [{ id: 5, full_name: 'Kabir Singh' }], cancelled: false, can_cancel: false }],
    'get /recordings/policy': () => ({ retention_days: 30, max_bytes: 2000000000, storage: 'Private storage on the company server.' }),
    'get /recordings': () => [{ id: 8, user_id: 5, user: 'Kabir Singh', status: 'interrupted', started_at: '2026-11-12T10:00:00Z', duration_seconds: 90, size_bytes: 2097152, task: null }],
    'get /reports/summary': () => ({ rows: [{ user_id: 5, employee_code: 'WC-E0005', full_name: 'Kabir Singh', role: 'intern', days_present: 3, active_hours: 4.5, away_hours: 1,
      avg_hours_per_day: 1.5, extra_hours: 0.5, total_hours: 5.0, full_days: 1, tasks_assigned: 2, tasks_completed: 1, tasks_open: 1, tasks_rejected: 0, completion_percent: 50, submissions: 1, recordings: 1 }] }),
    'get /timer/overview': () => ({ start: '2026-11-12', end: '2026-11-12', rows: [{ user_id: 5, full_name: 'Kabir Singh', role: 'intern', state: 'PAUSED_INACTIVE',
      pause_reason: 'inactivity', category: null, today_active_seconds: 3600, active_seconds: 7200, paused_seconds: 900, inactive_seconds: 600,
      inactive_for_seconds: 420, last_activity_at: '2026-11-12T10:00:00Z', session_start: '2026-11-12T09:00:00Z', session_end: null,
      recording: 'recording', schedule: 'regular', session_schedule: 'regular', extra_seconds_today: 1800,
      extra_seconds: 5400, schedule_label: 'Regular', extra_running: false, extra_start: '2026-11-12T09:00:00Z', extra_end: null,
      regular_completed: false, regular_completed_at: null, schedule_target_seconds: 28800,
      meeting_seconds: 5400, meetings: 2, meeting_joins: 3, in_meeting: true,
      meeting_start: '2026-11-12T09:10:00Z', meeting_end: '2026-11-12T11:00:00Z',
      meeting_work_seconds: 3600, meeting_outside_seconds: 1800, total_seconds: 12600, grand_total_seconds: 18000,
      work_overlap_seconds: 0 }],
      totals: { people: 1, regular_seconds: 7200, extra_seconds: 5400, meeting_seconds: 5400, meeting_work_seconds: 3600,
        meeting_outside_seconds: 1800, active_seconds: 12600, paused_seconds: 900, inactive_seconds: 600,
        total_seconds: 12600, grand_total_seconds: 18000, meetings: 2, meeting_joins: 3, work_overlap_seconds: 0 } }),
    'get /timer/sessions': () => [{ id: 1, started_at: '2026-11-12T09:00:00Z', ended_at: null, state: 'PAUSED_INACTIVE', active_seconds: 3600, paused_seconds: 600,
      events: [{ at: '2026-11-12T09:00:00Z', to: 'RUNNING', reason: 'auto_start' }, { at: '2026-11-12T10:05:00Z', to: 'PAUSED_INACTIVE', reason: 'inactivity' }] }],
    'get /timer/allowlist': () => [{ id: 1, domain: 'meet.google.com', label: 'Google Meet', ignore_inactivity: true }, { id: 2, domain: 'chatgpt.com', label: 'ChatGPT', ignore_inactivity: false }],
    'post /timer/allowlist': (b) => ({ id: 3, ...b }),
    'post /extension/token': () => ({ token: 'ext.jwt.token', expires_in_minutes: 43200 }),
    'get /sessions/live': () => [],
    'get /attendance': () => [{ day: '2026-11-12', active_seconds: 65, away_seconds: 0, paused_seconds: 0, extra_seconds: 300, regular_completed_at: null, status: 'present' }],
    'get /dashboard/admin': () => ({ range: { start: '2026-11-01', end: '2026-11-12' },
      people: { total_employees: 4, developers: 1, onroll: 1, offroll: 1, interns: 2, admins: 1, active: 5, inactive: 0 },
      live: { working: 2, idle: 1 }, tasks: counts, hours, active_recordings: 0, projects: 1, teams: 1,
      review_queue: { onroll: 1, admin: 0 }, intern_headcount: { target: 10, filled: 2, vacant: 8 } }),
    'get /dashboard/developer': () => ({ team: { total: 3, onroll: 1, offroll: 1, interns: 1, progress_percent: 50 },
      live: { working: 1, idle: 0 }, tasks: counts, pending_reviews: 2, hours, my_tasks: counts }),
    'get /dashboard/me': () => ({ tasks: counts, overdue: 0, active_projects: 1, hours, assigned_by_me: 3,
      training_period: role === 'onroll' ? null : { start: '2026-09-22', end: '2027-03-22', days_left: 130, progress_percent: 28 },
      recent_tasks: [TASK], recent_submissions: [] }),
    'get /tasks/7/workspace': () => ({ id: 9, task_id: 7, user_id: 5, task_code: 'WC-0007', task_title: 'Build page', task_status: 'in_progress',
      read_only: false, last_saved_at: null, submissions: [], files: [{ id: 11, path: 'index.html', content: '<h1>Hi</h1>' }] }),
    'get /languages': () => ({ runner: { available: state.docker !== false, reason: 'Docker is not installed on the server.' }, languages: [
      { id: 'python', name: 'Python', extensions: ['py'], monaco: 'python', kind: 'run', file: 'main.py', template: 'print("Hello from WORKCODE")\n', image: 'python:3.12-alpine', image_state: 'missing', note: null },
      { id: 'html', name: 'HTML', extensions: ['html'], monaco: 'html', kind: 'preview', file: 'index.html', template: '<h1></h1>', note: null },
      { id: 'react', name: 'React (JSX)', extensions: ['jsx'], monaco: 'javascript', kind: 'edit', file: 'App.jsx', template: '', note: 'Needs npm packages.' }] }),
    'post /workspaces/9/run': (b) => ({ status: 'ok', exit_code: 0, stdout: `hello ${b.stdin}`, stderr: '', duration_ms: 120, file: 'main.py', language: 'python', time_limit_seconds: 20 }),
    'post /languages/python/pull': () => ({ image_state: 'pulling' }),
    'get /templates': () => [{ id: 'react', name: 'React (Vite)', group: 'Frontend', verified: true, needs: 'Node.js + packages (npm install).', open: 'src/App.jsx', files: ['package.json', 'src/App.jsx'] },
      { id: 'flutter', name: 'Flutter', group: 'Mobile', verified: false, needs: 'Flutter SDK.', open: 'lib/main.dart', files: ['lib/main.dart'] }],
    'post /workspaces/9/template': () => ({ template: 'react', open: 'src/App.jsx', replaced: [], files: [] }),
    'post /workspaces/9/move': () => ({ files: [] }),
    'get /ai/status': () => ({ can_use: true, reason: null, configured: true, used_today: 3, daily_limit: 100, max_context_chars: 60000,
      models: [{ id: '1:gpt-test', provider: 'OpenAI', model: 'gpt-test', default: true }, { id: '1:gpt-mini', provider: 'OpenAI', model: 'gpt-mini', default: false }] }),
    'post /ai/conversations': () => ({ id: 21, title: 'New chat' }),
    'get /tasks': () => [TASK],
    'get /users/assignable': () => (['admin', 'developer', 'onroll'].includes(role) ? [{ id: 5, full_name: 'Kabir Singh', role: 'intern' }] : []),
    'get /projects': () => [],
    'put /workspaces/9/files': (b) => ({ file: { id: 11, path: b.path, content: b.content }, last_saved_at: '2026-11-12T10:00:00Z', task_status: 'saved' }),
    'post /workspaces/9/submit': () => ({ id: 3, version_no: 1, version: '1.0', stage: 'onroll_review', status: 'pending_onroll_review', task_status: 'under_onroll_review' }),
    'get /workspaces/9/history': () => [{ id: 1, path: 'index.html', action: 'edited', modified_by_name: 'Kabir Singh', at: '2026-11-12T10:00:00Z', previous_version: 1, new_version: 2, summary: '+1 -1 lines' }],
    'get /users/reviewers': () => [{ id: 6, full_name: 'Meena R', role: 'onroll' }],
  };
  const key = Object.keys(table).find((k) => { const [m, u] = k.split(' '); return m === method && url.startsWith(u); });
  if (!key) return Promise.reject({ response: { status: 404, data: { detail: `no mock for ${method} ${url}` } } });
  return Promise.resolve({ data: table[key](body) });
}

vi.mock('../services/api', () => ({
  default: { get: (u, c) => respond('get', u, c?.params), post: (u, b) => respond('post', u, b), put: (u, b) => respond('put', u, b),
    patch: (u, b) => respond('patch', u, b), delete: (u) => respond('delete', u) },
  getToken: () => (state.user ? 'token' : null),
  setToken: () => {},
  // same shape as the real helper: <base><path>?token=...&<extra>
  wsUrl: (path, extra = {}) => `ws://localhost${path}?` + Object.entries({ token: 'token', ...extra })
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&'),
  BUILD: 'test',
  report: () => {},
  errMsg: (e) => e?.response?.data?.detail || 'error',
}));
vi.mock('../services/ai', async (original) => ({ ...(await original()), streamChat: (...args) => state.stream(...args) }));
vi.mock('@monaco-editor/react', async () => {
  const React = await import('react');
  /** A textarea plus the small part of the Monaco API that WORKCODE calls (selection, edits, markers). */
  function FakeEditor({ value, onChange, onMount }) {
    const live = React.useRef({ value, onChange });
    live.current = { value, onChange };
    React.useEffect(() => {
      const editor = {
        getSelection: () => ({ isEmpty: () => !state.selection, endLineNumber: 1 }),
        getModel: () => ({ getValueInRange: () => state.selection || '', getLineMaxColumn: () => 1 }),
        getPosition: () => ({ lineNumber: 1, column: 1 }),
        executeEdits: (source, edits) => { state.edits.push({ source, text: edits[0].text }); live.current.onChange(live.current.value + edits[0].text); },
        pushUndoStop: () => {}, focus: () => {}, addCommand: () => {}, getAction: () => null, onDidChangeCursorPosition: () => {},
      };
      onMount?.(editor, { editor: { getModelMarkers: () => [], onDidChangeMarkers: () => {} }, KeyMod: { Alt: 1, Shift: 2 }, KeyCode: { KeyF: 3 } });
    }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return <textarea aria-label="editor" value={value} onChange={(e) => onChange(e.target.value)} />;
  }
  return { default: FakeEditor };
});

import App from '../App';
import { AuthProvider } from '../context/AuthContext';
import { NotificationProvider } from '../context/NotificationContext';
import { TimerProvider } from '../context/TimerContext';
import { RecordingProvider } from '../context/RecordingContext';

function renderApp(path, role) {
  state.user = role ? USERS[role] : null;
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider><TimerProvider><NotificationProvider><RecordingProvider><App /></RecordingProvider></NotificationProvider></TimerProvider></AuthProvider>
    </MemoryRouter>,
  );
}
const navLabels = () => within(screen.getByRole('navigation')).getAllByRole('link').map((a) => a.querySelector('span:nth-child(2)').textContent);

beforeEach(() => {
  state.meetingTimer = { current: null, today_seconds: 0, week_seconds: 4025, month_seconds: 8425 };
  state.calls = []; state.handlers = {}; state.edits = []; state.selection = ''; state.stream = () => Promise.resolve();
  global.WebSocket = class { constructor() { this.readyState = 0; } close() {} send() {} };
});

describe('login', () => {
  it('redirects anonymous visitors to the login form', async () => {
    renderApp('/admin', null);
    expect(await screen.findByLabelText('Email or username')).toBeInTheDocument();
  });

  it('signs in and opens the dashboard of the user role', async () => {
    renderApp('/login', null);
    state.handlers['post /auth/login'] = (b) => {
      if (b.password !== 'right') return Promise.reject({ response: { status: 401, data: { detail: 'Incorrect email or password' } } });
      state.user = USERS.intern;
      return Promise.resolve({ data: { access_token: 't', user: USERS.intern } });
    };
    fireEvent.change(await screen.findByLabelText('Email or username'), { target: { value: 'i@x.io' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password');
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'right' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Hi Kabir 👋')).toBeInTheDocument();
  });

  it('forgot password: the link on the login page opens the form, the address is sent, the answer is shown; an unknown address is told so', async () => {
    renderApp('/login', null);
    fireEvent.click(await screen.findByRole('link', { name: 'Forgot password?' }));
    state.handlers['post /auth/forgot-password'] = () => Promise.resolve({ data: { ok: true, message: 'A password reset link has been sent to i@x.io.' } });
    fireEvent.change(await screen.findByLabelText('Email address'), { target: { value: ' i@x.io ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    expect(await screen.findByRole('status')).toHaveTextContent('A password reset link has been sent to i@x.io.');
    expect(state.calls.find((c) => c.url === '/auth/forgot-password').body).toEqual({ email: 'i@x.io' });
    // a server without e-mail says so instead of pretending
    fireEvent.click(screen.getByRole('button', { name: 'Send again' }));
    state.handlers['post /auth/forgot-password'] = () => Promise.reject({ response: { status: 503, data: { detail: 'Password reset by e-mail is not set up on this server.' } } });
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'i@x.io' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('not set up');
    // an address without an account is told so
    state.handlers['post /auth/forgot-password'] = () => Promise.reject({ response: { status: 404, data: { detail: 'Email not found, please enter the correct email.' } } });
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'nobody@x.io' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Email not found, please enter the correct email.'));
    expect(screen.queryByRole('status')).toBeNull();
    fireEvent.click(screen.getByRole('link', { name: /Back to sign in/ }));
    expect(await screen.findByLabelText('Email or username')).toBeInTheDocument();
  });

  it('create new password keeps the token in development mode (React StrictMode runs effects twice)', async () => {
    window.history.replaceState(null, '', '/reset-password#token=tok-from-the-mail-1234567890');
    state.handlers['post /auth/reset-password/validate'] = () => Promise.resolve({ data: { valid: true, expires_in_seconds: 1700 } });
    state.handlers['post /auth/reset-password'] = () => Promise.resolve({ data: { ok: true, message: 'Password Reset Successfully' } });
    state.user = null;
    render(
      <StrictMode><MemoryRouter initialEntries={['/reset-password']}>
        <AuthProvider><TimerProvider><NotificationProvider><RecordingProvider><App /></RecordingProvider></NotificationProvider></TimerProvider></AuthProvider>
      </MemoryRouter></StrictMode>,
    );
    fireEvent.change(await screen.findByLabelText('New password'), { target: { value: 'Fresh#Pass2026' } });
    fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: 'Fresh#Pass2026' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save password' }));
    expect(await screen.findByText('Password Reset Successfully')).toBeInTheDocument();
    expect(state.calls.find((c) => c.url === '/auth/reset-password').body).toEqual({ token: 'tok-from-the-mail-1234567890', new_password: 'Fresh#Pass2026' });
  });

  it('create new password: checks the link, the strength and the match, saves, then returns to the login page', async () => {
    window.history.replaceState(null, '', '/reset-password#token=tok-from-the-mail-1234567890');
    state.handlers['post /auth/reset-password/validate'] = () => Promise.resolve({ data: { valid: true, expires_in_seconds: 1700 } });
    state.handlers['post /auth/reset-password'] = () => Promise.resolve({ data: { ok: true, message: 'Password Reset Successfully' } });
    renderApp('/reset-password', null);
    const first = await screen.findByLabelText('New password');
    expect(state.calls.find((c) => c.url === '/auth/reset-password/validate').body).toEqual({ token: 'tok-from-the-mail-1234567890' });
    expect(window.location.hash).toBe('');                                   // the token is gone from the address bar
    const second = screen.getByLabelText('Confirm new password');
    const save = screen.getByRole('button', { name: 'Save password' });
    fireEvent.change(first, { target: { value: 'weakpass' } });
    fireEvent.change(second, { target: { value: 'weakpass' } });
    expect(save).toBeDisabled();
    expect(within(screen.getByLabelText('Password rules')).getByText(/A capital letter/)).not.toHaveClass('ok');
    fireEvent.change(first, { target: { value: 'Fresh#Pass2026' } });
    expect(screen.getByRole('alert')).toHaveTextContent('not the same');
    expect(save).toBeDisabled();
    expect(first).toHaveAttribute('type', 'password');
    fireEvent.click(screen.getByLabelText('Show password'));
    expect(first).toHaveAttribute('type', 'text');
    expect(second).toHaveAttribute('type', 'text');
    fireEvent.change(second, { target: { value: 'Fresh#Pass2026' } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    expect(await screen.findByText('Password Reset Successfully')).toBeInTheDocument();
    expect(state.calls.find((c) => c.url === '/auth/reset-password').body).toEqual({ token: 'tok-from-the-mail-1234567890', new_password: 'Fresh#Pass2026' });
    fireEvent.click(screen.getByRole('link', { name: 'Go to sign in now' }));
    expect(await screen.findByLabelText('Email or username')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Sign in with your new password');
  });

  it('create new password: an expired, used or missing link shows the reason and a way to ask again', async () => {
    window.history.replaceState(null, '', '/reset-password#token=old-token-old-token-old-token');
    state.handlers['post /auth/reset-password/validate'] = () => Promise.reject({ response: { status: 400, data: { detail: 'This reset link is not valid or has expired. Request a new one.' } } });
    const view = renderApp('/reset-password', null);
    expect(await screen.findByRole('alert')).toHaveTextContent('not valid or has expired');
    expect(screen.queryByLabelText('New password')).toBeNull();
    expect(screen.getByRole('link', { name: 'Request a new link' })).toHaveAttribute('href', '/forgot-password');
    view.unmount();
    window.history.replaceState(null, '', '/reset-password');
    renderApp('/reset-password', null);
    expect(await screen.findByRole('alert')).toHaveTextContent('opened from the link in the password reset e-mail');
  });
});

describe('role-based navigation', () => {
  const expected = {
    admin: ['Overview', 'People', 'Teams & projects', 'Tasks', 'Code reviews', 'Monitoring', 'Recordings', 'Reports', 'Languages', 'AI assistant', 'Meetings', 'Chat', 'Audit log', 'Profile'],
    onroll: ['My dashboard', 'Tasks', 'Coding workspace', 'Reviews', 'My team', 'Meetings', 'Recordings', 'Reports', 'Chat', 'Profile'],
    offroll: ['My dashboard', 'My tasks', 'Coding workspace', 'My submissions', 'Meetings', 'My recordings', 'My reports', 'Chat', 'Profile'],
    intern: ['My dashboard', 'My tasks', 'Coding workspace', 'My submissions', 'Meetings', 'My recordings', 'My reports', 'Chat', 'Profile'],
  };
  for (const [role, labels] of Object.entries(expected)) {
    it(`${role} sees only its own menu`, async () => {
      renderApp('/', role);
      await screen.findByRole('navigation');
      expect(navLabels()).toEqual(labels);
    });
  }

  it('sends an intern who types an admin URL back to the intern dashboard', async () => {
    renderApp('/people', 'intern');
    expect(await screen.findByText('Hi Kabir 👋')).toBeInTheDocument();
    expect(state.calls.some((c) => c.url.startsWith('/users?') || c.url === '/users')).toBe(false);
  });
});

describe('dashboards', () => {
  it('admin dashboard shows numbers from the API', async () => {
    renderApp('/admin', 'admin');
    expect(await screen.findByText('Platform overview')).toBeInTheDocument();
    expect(screen.getByText('8 of 10 seats vacant')).toBeInTheDocument();
    expect(screen.getByText('1 with On-Roll · 0 with Admin')).toBeInTheDocument();
  });
  it('there is no Developer panel: the old address opens the user\'s own dashboard', async () => {
    renderApp('/developer', 'onroll');
    expect(await screen.findByText('Employment')).toBeInTheDocument();
    expect(state.calls.some((c) => c.url === '/dashboard/developer')).toBe(false);
  });
  it('intern dashboard shows the internship period and the server timer', async () => {
    renderApp('/intern', 'intern');
    expect(await screen.findByText('Period ends in')).toBeInTheDocument();
    expect(screen.getByText('130d')).toBeInTheDocument();
    expect(screen.getByText('My working time')).toBeInTheDocument();
    expect(screen.getAllByText('00:01:05').length).toBeGreaterThanOrEqual(2);   // header timer and the Active tile agree
    expect(within(screen.getByTestId('card-regular')).getByText('00:01:05')).toBeInTheDocument();  // build 34 card, same number
    expect(screen.getByTestId('card-regular')).toHaveTextContent(/% completed of 08:00:00/);  // the 8 h target is shown too
    expect(screen.getByText('2026-11-11 21:00:00')).toBeInTheDocument();  // last logout from the server
  });
  it('the employee dashboard shows four timers and a grand total that counts meetings again', async () => {
    const today = new Date().toLocaleDateString('en-CA');
    state.meetingTimer = { current: null, today_seconds: 95, week_seconds: 95, month_seconds: 95 };
    state.handlers['get /attendance'] = () => Promise.resolve({ data: [{ day: today, active_seconds: 65, away_seconds: 0,
      paused_seconds: 0, extra_seconds: 0, meeting_seconds: 95, meetings: 1, meeting_joins: 1, total_seconds: 160,
      actual_seconds: 65, regular_completed_at: null, status: 'present' }] });
    renderApp('/intern', 'intern');
    const grid = await screen.findByTestId('working-timers');
    for (const name of ['Regular Work Timer', 'Meeting Timer', 'Extra Work Timer', 'Total Time (All)']) {
      expect(within(grid).getByText(name)).toBeInTheDocument();
    }
    // the meeting timer is automatic: no manual pause, no manual stop
    const meeting = screen.getByTestId('card-meeting');
    expect(within(meeting).queryByRole('button', { name: 'Pause' })).toBeNull();
    expect(within(meeting).queryByRole('button', { name: 'Stop' })).toBeNull();
    expect(within(meeting).getByText('No meeting now')).toBeInTheDocument();
    expect(within(meeting).getByText('1 meeting(s) today · this week 1m 35s · this month 1m 35s')).toBeInTheDocument();
    // 65 s work + 95 s meeting + 0 s extra: the meeting is added, so the grand total is 160 s
    expect(screen.getByTestId('grand-total-value').textContent).toBe('00:02:40');
    expect(screen.getByTestId('actual-time')).toHaveTextContent('Actual working time (no double count): 00:01:05');
    expect(screen.getByTestId('summary-grand').textContent).toBe('00:02:40');
    expect(screen.getByTestId('today-summary')).toHaveTextContent('Meeting Time');
    expect(screen.getByTestId('today-row')).toHaveTextContent('00:01:35');       // the meeting minute in the daily row
    expect(screen.getByTestId('today-row')).toHaveTextContent('00:02:40');       // the same total, from the server
    // the row adds up on screen: what the three columns show is what the Total column shows
    const row = screen.getByTestId('today-row');
    const cells = within(row).getAllByRole('cell').map((c) => c.textContent);
    const toSec = (v) => (v.match(/^\d{2}:\d{2}:\d{2}$/) ? v.split(':').reduce((a, b) => a * 60 + +b, 0) : null);
    expect(toSec(cells[1]) + toSec(cells[4]) + toSec(cells[2])).toBe(toSec(cells[5]));
    expect(screen.getByTestId('total-time-note')).toHaveTextContent('Meeting hours are added again on purpose');
  });

  it('uses the day the server calls today, not the date on the laptop', async () => {
    // a computer whose clock sits on another date must still show the counted time: the row is marked
    state.meetingTimer = { current: null, today_seconds: 120, week_seconds: 120, month_seconds: 120 };
    state.handlers['get /attendance'] = () => Promise.resolve({ data: [
      { day: '2031-04-05', is_today: true, active_seconds: 7200, extra_seconds: 600, away_seconds: 0,
        paused_seconds: 0, meeting_seconds: 300, meetings: 2, meeting_joins: 3, actual_seconds: 7800,
        total_seconds: 8100, regular_completed_at: null, status: 'present' },
      { day: '2031-04-04', is_today: false, active_seconds: 60, extra_seconds: 0, away_seconds: 0,
        paused_seconds: 0, meeting_seconds: 0, meetings: 0, meeting_joins: 0, actual_seconds: 60,
        total_seconds: 60, regular_completed_at: null, status: 'present' },
    ] });
    renderApp('/offroll', 'offroll');
    expect(await screen.findByTestId('grand-total-value')).toHaveTextContent('02:15:00');   // 8100 s
    expect(screen.getByTestId('actual-time')).toHaveTextContent('02:10:00');                 // 7800 s
    expect(screen.getByTestId('today-row')).toHaveTextContent('2031-04-05');
    expect(screen.getByTestId('today-summary')).toHaveTextContent(/Meeting Time\s*00:05:00/);
  });

  it('on-roll dashboard shows "assigned by me" instead of a training period', async () => {
    renderApp('/onroll', 'onroll');
    expect(await screen.findByText('Employment')).toBeInTheDocument();
    expect(screen.queryByText('Period ends in')).not.toBeInTheDocument();
  });
});

describe('tasks', () => {
  it('interns and off-roll users get no assign button', async () => {
    for (const role of ['intern', 'offroll']) {
      const view = renderApp('/tasks', role);
      expect(await screen.findByText('Build page')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Assign a task' })).not.toBeInTheDocument();
      view.unmount();
    }
  });
  it('an on-roll user can create and assign a task', async () => {
    renderApp('/tasks', 'onroll');
    const button = await screen.findByRole('button', { name: 'Assign a task' });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    const dialog = await screen.findByRole('dialog');
    state.handlers['post /tasks'] = (b) => Promise.resolve({ data: { ...TASK, ...b } });
    fireEvent.change(within(dialog).getByLabelText('Title'), { target: { value: 'New feature' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Assign task' }));                 // nobody ticked yet
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Choose at least one person');
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Kabir Singh/ }));
    fireEvent.change(within(dialog).getByLabelText('Expected deliverables'), { target: { value: 'A zip' } });
    fireEvent.change(within(dialog).getByLabelText('On-Roll reviewer'), { target: { value: '6' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Assign task' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'post' && c.url === '/tasks')).toBeTruthy());
    expect(state.calls.find((c) => c.method === 'post' && c.url === '/tasks').body)
      .toMatchObject({ title: 'New feature', assigned_to_ids: [5], reviewer_id: 6, deliverables: 'A zip' });
  });

  it('role tabs filter the list through the API', async () => {
    renderApp('/tasks', 'intern');
    for (const name of ['My tasks', 'In progress', 'Submitted', 'Rework required', 'Completed']) expect(await screen.findByRole('button', { name })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Rework required' }));
    await waitFor(() => expect(state.calls.find((c) => c.url === '/tasks' && c.body?.status === 'rework_required,onroll_rejected,admin_rejected')).toBeTruthy());
    expect(state.calls.find((c) => c.body?.status?.startsWith('rework_required')).body.scope).toBe('mine');
  });

  it('the assignee accepts a task; history and versions with a real diff are shown', async () => {
    let status = 'assigned';
    state.handlers['get /tasks/7/history'] = () => Promise.resolve({ data: [
      { id: 1, action: 'created', user: 'Arun Kumar', user_role: 'admin', from_status: null, to_status: 'created', at: '2026-11-12T09:00:00Z' },
      { id: 2, action: 'onroll_rejected', user: 'Ravi Teja', user_role: 'onroll', from_status: 'under_onroll_review', to_status: 'onroll_rejected', comment: 'Fix the title', version: '1.0', at: '2026-11-12T10:00:00Z' }] });
    state.handlers['get /tasks/7/versions'] = () => Promise.resolve({ data: [2, 1].map((n) => ({ id: n, version: `1.${n - 1}`, submitted_at: '2026-11-12T10:00:00Z',
      submitted_by_name: 'Kabir Singh', submitter_role: 'intern', file_count: 2, status: n === 1 ? 'rejected' : 'pending_onroll_review', note: null,
      changes: { added: [], modified: n === 2 ? ['index.html'] : [], deleted: [] }, reviews: n === 1 ? [{ reviewer: 'Ravi Teja', decision: 'rejected', comment: 'Fix the title' }] : [] })) });
    state.handlers['get /tasks/7/compare'] = () => Promise.resolve({ data: { from: { id: 1, version: '1.0' }, to: { id: 2, version: '1.1' }, unchanged: 1,
      summary: { added: 0, modified: 1, deleted: 0 }, files: [{ path: 'index.html', status: 'modified', lines_added: 1, lines_removed: 1, diff: '--- v1.0/index.html\n+++ v1.1/index.html\n@@ -1 +1 @@\n-<h1>Hi</h1>\n+<h1>Hello</h1>' }] } });
    state.handlers['post /tasks/7/accept'] = () => { status = 'accepted'; return Promise.resolve({ data: {} }); };
    state.handlers['get /tasks/7'] = () => Promise.resolve({ data: { ...TASK, status, is_assignee: true, can_manage: false, attachments: [], deliverables: 'A zip',
      time: { active_seconds: 4500, paused_seconds: 600, total_seconds: 5100, review_seconds: 0 } } });
    renderApp('/tasks/7', 'intern');
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('1h 15m active · 10m 00s paused · 1h 25m total')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Open workspace' })).not.toBeInTheDocument();   // not before accepting
    fireEvent.click(within(dialog).getByRole('button', { name: 'Accept task' }));
    expect(await within(dialog).findByRole('button', { name: 'Start task' })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Task history' }));
    expect(await within(dialog).findByText('Fix the title')).toBeInTheDocument();
    expect(within(dialog).getByText(/Under On-Roll review → On-Roll rejected/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Version history' }));
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Compare versions' }));
    expect(await within(dialog).findByText('+<h1>Hello</h1>')).toHaveClass('add');
    expect(within(dialog).getByText('-<h1>Hi</h1>')).toHaveClass('del');
    expect(state.calls.find((c) => c.url === '/tasks/7/compare').body).toEqual({ a: 1, b: 2 });
  });
  it('opens a reference file from the task screen instead of downloading it', async () => {
    const attachment = { id: 3, kind: 'reference', filename: 'design.pdf', open_mode: 'preview', size_bytes: 2048,
      uploaded_by: 2, uploaded_by_name: 'Arun Kumar', submission_id: null, created_at: '2026-11-12T09:00:00Z' };
    state.handlers['get /tasks/7'] = () => Promise.resolve({ data: { ...TASK, is_assignee: false, can_manage: true,
      attachments: [attachment], time: { active_seconds: 0, paused_seconds: 0, total_seconds: 0, review_seconds: 0 } } });
    state.handlers['post /tasks/7/attachments/3/open'] = () => Promise.resolve({ data: { mode: 'preview', filename: 'design.pdf',
      task_id: 7, attachment_id: 3, content_type: 'application/pdf', url: '/api/tasks/7/attachments/3' } });
    renderApp('/tasks/7', 'onroll');
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Open' }));
    expect(await screen.findByTitle('design.pdf')).toBeInTheDocument();      // the preview window, no download
    expect(state.calls.find((c) => c.url === '/tasks/7/attachments/3/open')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close preview' }));
    expect(screen.queryByTitle('design.pdf')).not.toBeInTheDocument();
  });
  it('draws no Open button for a file that can only be downloaded', async () => {
    const attachment = { id: 4, kind: 'reference', filename: 'assets.zip', open_mode: 'download', size_bytes: 900,
      uploaded_by: 2, uploaded_by_name: 'Arun Kumar', submission_id: null, created_at: '2026-11-12T09:00:00Z' };
    state.handlers['get /tasks/7'] = () => Promise.resolve({ data: { ...TASK, is_assignee: false, can_manage: true,
      attachments: [attachment], time: { active_seconds: 0, paused_seconds: 0, total_seconds: 0, review_seconds: 0 } } });
    renderApp('/tasks/7', 'onroll');
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('button', { name: 'assets.zip' })).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Open' })).not.toBeInTheDocument();
  });
});

const SUBMISSION = { id: 3, task_id: 7, task_code: 'WC-0007', task_title: 'Build page', submitted_by: 5, submitted_by_name: 'Kabir Singh', submitter_role: 'intern',
  version_no: 2, version: '1.1', stage: 'onroll_review', status: 'pending_onroll_review', submitted_at: '2026-11-12T10:00:00Z', note: 'Fixed the title', file_count: 2,
  changes: { added: ['app.py'], modified: ['index.html'], deleted: [] }, files: [{ path: 'app.py', content: 'print(1)' }, { path: 'index.html', content: '<h1>Hello</h1>' }],
  authors: { 'app.py': { name: 'Kabir Singh', at: '2026-11-12T09:59:00Z' } }, task_requirements: 'Make a page', task_deliverables: null, can_review: true, can_restore: false,
  versions: [{ id: 2, version: '1.0', status: 'rejected' }, { id: 3, version: '1.1', status: 'pending_onroll_review' }], attachments: [], reviews: [], comments: [] };

describe('reviews', () => {
  it('an On-Roll reviewer sees the queue tabs, runs the submitted snapshot and must give a reason to reject', async () => {
    state.handlers['get /submissions/3'] = () => Promise.resolve({ data: SUBMISSION });
    state.handlers['post /submissions/3/run'] = (b) => Promise.resolve({ data: { status: 'ok', exit_code: 0, stdout: `ran ${b.path}`, stderr: '' } });
    state.handlers['post /submissions/3/review'] = (b) => (b.decision !== 'approved' && !b.comment
      ? Promise.reject({ response: { status: 422, data: { detail: 'A comment is required' } } })
      : Promise.resolve({ data: { ...SUBMISSION, stage: 'admin_review', status: 'pending_admin_review', can_review: false } }));
    const list = renderApp('/reviews', 'onroll');
    for (const name of ['Pending reviews', 'Intern submissions', 'Off-Roll submissions', 'Approved', 'Rejected', 'Review history']) expect(await screen.findByRole('button', { name })).toBeInTheDocument();
    list.unmount();
    renderApp('/reviews/3', 'onroll');
    expect(await screen.findByText(/Version 1.1 by Kabir Singh \(Intern\)/)).toBeInTheDocument();
    expect(screen.getByText('Last modified by Kabir Singh', { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '▶ Run app.py' }));
    expect(await screen.findByLabelText('Run output')).toHaveTextContent('ran app.py');
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A comment is required');
    fireEvent.click(screen.getByRole('button', { name: 'Approve → send to Admin' }));
    expect(await screen.findByText('Waiting for: Admin final review.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
  });

  it('interns only see their own submissions and get no decision buttons', async () => {
    state.handlers['get /submissions/3'] = () => Promise.resolve({ data: { ...SUBMISSION, can_review: false, can_restore: true } });
    state.handlers['post /submissions/3/restore'] = () => Promise.resolve({ data: { restored: 2 } });
    const list = renderApp('/reviews', 'intern');
    await waitFor(() => expect(state.calls.find((c) => c.url === '/submissions' && c.body?.view === 'mine')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'Pending reviews' })).not.toBeInTheDocument();
    list.unmount();
    renderApp('/reviews/3', 'intern');
    expect(await screen.findByText('Waiting for: On-Roll review.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Restore to workspace' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(state.calls.find((c) => c.url === '/submissions/3/restore')).toBeTruthy());
  });
});

describe('coding workspace', () => {
  it('IDE shell: activity bar, shortcuts, quick open, search, rename through the explorer', async () => {
    renderApp('/workspace/7', 'intern');
    await screen.findByLabelText('editor');
    expect(screen.getByRole('tree', { name: 'Project files' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('1 files');
    fireEvent.keyDown(window, { key: 'b', ctrlKey: true });                               // Ctrl+B hides the sidebar
    expect(screen.queryByRole('tree')).toBeNull();
    fireEvent.keyDown(window, { key: 'F', ctrlKey: true, shiftKey: true });               // Ctrl+Shift+F opens search
    fireEvent.change(screen.getByLabelText('Search in files'), { target: { value: 'Hi' } });
    expect(await screen.findByText(/1 result\(s\) in 1 file/)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'p', ctrlKey: true });                               // Ctrl+P quick open
    expect(screen.getByRole('dialog', { name: 'Go to file' })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Go to file' }), { key: 'Escape' });
    fireEvent.keyDown(window, { key: 'P', ctrlKey: true, shiftKey: true });               // Ctrl+Shift+P commands
    fireEvent.change(screen.getByRole('textbox', { name: 'Command palette' }), { target: { value: 'light theme' } });
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Command palette' }), { key: 'Enter' });
    expect(document.querySelector('.ide.light')).not.toBeNull();
    fireEvent.keyDown(window, { key: '`', ctrlKey: true });                               // Ctrl+` shows the terminal
    expect(screen.getByLabelText('Terminal')).toBeVisible();
    fireEvent.click(screen.getByLabelText('Explorer (Ctrl+B)'));
    fireEvent.click(within(screen.getByRole('tree')).getByText('index.html'));               // select, then F2 renames in place
    fireEvent.keyDown(screen.getByRole('tree'), { key: 'F2' });
    fireEvent.change(screen.getByLabelText('Rename file'), { target: { value: 'pages/home.html' } });
    fireEvent.keyDown(screen.getByLabelText('Rename file'), { key: 'Enter' });
    await waitFor(() => expect(state.calls.find((c) => c.url === '/workspaces/9/move')?.body).toEqual({ from_path: 'index.html', to_path: 'pages/home.html' }));
  });
  it('project wizard lists templates, marks untested ones, and creates the files', async () => {
    renderApp('/workspace/7', 'intern');
    await screen.findByLabelText('editor');
    fireEvent.click(screen.getByLabelText('New project from template'));
    fireEvent.click(await screen.findByRole('button', { name: 'Flutter' }));
    expect(screen.getByText(/Not test-run/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'React (Vite)' }));
    expect(screen.getByText(/installed, built and run/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Create project files' }));
    await waitFor(() => expect(state.calls.find((c) => c.url === '/workspaces/9/template')?.body).toEqual({ template_id: 'react', overwrite: false }));
  });
  it('terminal: keys go straight to the shell, output is shown, and files changed in the shell reload the editor', async () => {
    const sockets = [];
    const Real = global.WebSocket;
    global.WebSocket = class { constructor(url) { this.url = url; this.sent = []; sockets.push(this); } send(d) { this.sent.push(JSON.parse(d)); } close() { this.onclose?.(); } };
    try {
      renderApp('/workspace/7', 'intern');
      await screen.findByLabelText('editor');
      fireEvent.click(screen.getByRole('button', { name: 'Terminal' }));
      expect(screen.getByTestId('terminal').textContent).toContain('No shell yet');
      fireEvent.click(screen.getByRole('button', { name: '＋ New terminal' }));
      const term = sockets.find((s) => s.url.includes('/ws/terminal'));
      expect(term.url).toMatch(/workspace_id=9&language=python&cols=100&rows=30/);
      act(() => term.onopen());
      expect(screen.getByText('connected, waiting for the shell…')).toBeInTheDocument();   // socket up, shell silent

      act(() => globalThis.__xterm.type('l'));                                  // every key is sent as it is typed
      act(() => globalThis.__xterm.type('s\r'));
      act(() => globalThis.__xterm.type('\x03'));                               // Ctrl+C reaches the shell too
      expect(term.sent).toEqual([{ type: 'input', data: 'l' }, { type: 'input', data: 's\r' }, { type: 'input', data: '\x03' }]);
      act(() => term.onmessage({ data: JSON.stringify({ type: 'output', data: 'ls\r\nmain.py\r\n' }) }));
      expect(screen.getByTestId('terminal').textContent).toContain('main.py');
      expect(screen.getByText('connected')).toBeInTheDocument();          // now the shell really answered
      const before = state.calls.filter((c) => c.method === 'get' && c.url === '/tasks/7/workspace').length;
      act(() => term.onmessage({ data: JSON.stringify({ type: 'files' }) }));   // the shell changed files: the editor reloads them
      await waitFor(() => expect(state.calls.filter((c) => c.method === 'get' && c.url === '/tasks/7/workspace').length).toBe(before + 1));
      act(() => term.onmessage({ data: JSON.stringify({ type: 'error', message: 'Docker is not installed on the server.' }) }));
      expect(screen.getByTestId('terminal').textContent).toContain('[not available] Docker is not installed');
      // a dev server started in the shell is offered in the Preview tab, on the port the server published for it
      fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
      expect(screen.queryByRole('group', { name: 'Preview source' })).toBeNull();
      act(() => term.onmessage({ data: JSON.stringify({ type: 'ports', ports: { 3000: 49001, 5173: 49160 } }) }));
      expect(screen.queryByTitle('Terminal server preview')).toBeNull();
      act(() => term.onmessage({ data: JSON.stringify({ type: 'output', data: '  Local:   http://localhost:5173/\r\n  Network: use --host to expose\r\n' }) }));
      expect(screen.getByTitle('Terminal server preview')).toHaveAttribute('src', 'http://localhost:49160/');
      expect(screen.getByLabelText('Server port')).toHaveValue('5173');
      expect(screen.getByRole('link', { name: /Open in new tab/ })).toHaveAttribute('href', 'http://localhost:49160/');
      expect(screen.getByTestId('terminal').textContent).toContain('npm run dev -- --host 0.0.0.0');
      fireEvent.change(screen.getByLabelText('Server port'), { target: { value: '3000' } });
      expect(screen.getByTitle('Terminal server preview')).toHaveAttribute('src', 'http://localhost:49001/');
      // the server reports what really listens in the container, so a white preview explains itself
      expect(term.sent.some((m) => m.type === 'probe' && m.port === '3000')).toBe(true);
      act(() => term.onmessage({ data: JSON.stringify({ type: 'listening', port: '3000', listening: { 5173: 'all' }, http: 'unknown' }) }));
      expect(screen.getByTestId('server-status')).toHaveTextContent('Nothing is listening on port 3000');
      act(() => term.onmessage({ data: JSON.stringify({ type: 'listening', port: '3000', listening: { 3000: 'local' }, http: 'ok' }) }));
      expect(screen.getByTestId('server-status')).toHaveTextContent('listens only on localhost');
      act(() => term.onmessage({ data: JSON.stringify({ type: 'listening', port: '3000', listening: { 3000: 'all' }, http: 'ok' }) }));
      expect(screen.getByTestId('server-status')).toHaveTextContent('Port 3000 is answering');
      // a second terminal next to the first one: its own connection, same environment, started at once
      fireEvent.click(screen.getByRole('button', { name: 'Terminal' }));
      fireEvent.click(screen.getByRole('button', { name: 'Add terminal' }));
      const terms = sockets.filter((x) => x.url.includes('/ws/terminal'));
      expect(terms).toHaveLength(2);
      expect(terms[1].url).toMatch(/language=python/);
      act(() => terms[1].onopen());
      expect(screen.getByRole('tab', { name: 'Terminal 2' })).toHaveAttribute('aria-selected', 'true');
      act(() => globalThis.__xterm.type('pwd\r'));
      act(() => term.onclose());                                                // first one closed: the second keeps the ports
      fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
      act(() => terms[1].onmessage({ data: JSON.stringify({ type: 'ports', ports: { 3000: 49001, 5173: 49160 } }) }));
      expect(screen.getByRole('group', { name: 'Preview source' })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Terminal' }));
      fireEvent.click(screen.getByRole('button', { name: 'Remove terminal 2' }));
      await waitFor(() => expect(screen.queryByRole('tab', { name: 'Terminal 2' })).toBeNull());
    } finally { global.WebSocket = Real; }
  });
  it('terminal: the tab you click gets the keyboard, and a connection that dies says why', async () => {
    const all = [];
    const Real = global.WebSocket;
    global.WebSocket = class { constructor(url) { this.url = url; this.sent = []; all.push(this); }
      send(d) { this.sent.push(JSON.parse(d)); } close() { this.onclose?.({ code: 1000 }); } };
    const terms = () => all.filter((s) => s.url.includes('/ws/terminal'));   // the notifications socket is not ours
    try {
      renderApp('/workspace/7', 'intern');
      await screen.findByLabelText('editor');
      fireEvent.click(screen.getByRole('button', { name: 'Terminal' }));
      fireEvent.click(screen.getByRole('button', { name: '＋ New terminal' }));
      const first = globalThis.__xterms.at(-1);
      expect(first.focused).toBe(true);                       // a new terminal is ready for the keyboard at once
      act(() => terms()[0].onopen());

      fireEvent.click(screen.getByRole('button', { name: 'Add terminal' }));
      const second = globalThis.__xterms.at(-1);
      expect(second).not.toBe(first);
      act(() => terms()[1].onopen());
      expect(second.focused).toBe(true);                      // the new tab takes the keyboard, not the tab button

      first.focused = false; second.focused = false;
      fireEvent.click(screen.getByRole('tab', { name: 'Terminal 1' }));
      expect(first.focused).toBe(true);                       // switching back moves the keyboard back
      expect(second.focused).toBe(false);

      const panel = (i) => screen.getAllByTestId('terminal')[i].textContent;   // [0] = tab 1, [1] = tab 2

      fireEvent.click(screen.getByRole('tab', { name: 'Terminal 2' }));
      const socks = terms().length;
      act(() => terms()[1].onclose({ code: 1006 }));          // a dropped upgrade: retried quietly, twice
      expect(panel(1)).toContain('connection lost before the shell answered (code 1006'), 
      expect(panel(1)).toContain('retrying…');
      await waitFor(() => expect(terms().length).toBe(socks + 1));
      act(() => terms()[socks].onclose({ code: 1006 }));
      await waitFor(() => expect(terms().length).toBe(socks + 2));
      act(() => terms()[socks + 1].onclose({ code: 1006 }));  // retries used up: say it plainly
      expect(panel(1)).toContain('the terminal service did not answer (code 1006');
      expect(panel(1)).toContain('Press New terminal to try again');

      fireEvent.click(screen.getByRole('tab', { name: 'Terminal 1' }));
      act(() => terms()[0].onmessage({ data: JSON.stringify({ type: 'output', data: 'workspace:/workspace$ ' }) }));
      act(() => terms()[0].onclose({ code: 1000 }));          // the shell answered, then the connection ended
      expect(panel(0)).toContain('[connection closed (code 1000)');
      expect(panel(0)).not.toContain('did not answer');
    } finally { global.WebSocket = Real; }
  });
  it('creates a file from a language template and runs it; HTML cannot be run', async () => {
    renderApp('/workspace/7', 'intern');
    await screen.findByLabelText('editor');
    await waitFor(() => expect(state.calls.find((c) => c.url === '/languages')).toBeTruthy());
    // index.html is preview-only: Run stays pressable and the Output panel says why, instead of doing nothing
    fireEvent.click(screen.getByRole('button', { name: '▶ Run' }));
    expect(await screen.findByText(/Not started: Use the Preview tab for this file/)).toBeInTheDocument();
    expect(state.calls.find((c) => c.url === '/workspaces/9/run')).toBeFalsy();
    fireEvent.contextMenu(screen.getByRole('tree'));
    fireEvent.click(screen.getByRole('menuitem', { name: 'New File from Template…' }));
    fireEvent.change(await screen.findByLabelText('Language'), { target: { value: 'python' } });
    expect(screen.getByLabelText('File path')).toHaveValue('main.py');
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'put')?.body).toEqual({ path: 'main.py', content: 'print("Hello from WORKCODE")\n', manual: true }));
    const runBtn = await screen.findByRole('button', { name: '▶ Run' });
    await waitFor(() => expect(runBtn).toBeEnabled());
    fireEvent.click(runBtn);
    expect(await screen.findByText(/finished · 120 ms/)).toBeInTheDocument();
    expect(state.calls.find((c) => c.url === '/workspaces/9/run').body.file_id).toBe(11);
  });
  it('has a full screen toggle that covers the window and can be left again', async () => {
    const { container } = renderApp('/workspace/7', 'intern');
    await screen.findByLabelText('editor');
    expect(container.querySelector('.ide.full')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Full screen/ }));
    expect(container.querySelector('.ide.full')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Exit full screen/ }));
    expect(container.querySelector('.ide.full')).toBeNull();
  });
  it('saves to the backend and submits for review', async () => {
    renderApp('/workspace/7', 'intern');
    const editor = await screen.findByLabelText('editor');
    fireEvent.change(editor, { target: { value: '<h1>Changed</h1>' } });
    expect(await screen.findByText('1 unsaved file(s)…')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'put')).toBeTruthy());
    expect(state.calls.find((c) => c.method === 'put').body).toEqual({ path: 'index.html', content: '<h1>Changed</h1>', manual: true });
    await waitFor(() => expect(screen.queryByText('1 unsaved file(s)…')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Submission note'), { target: { value: 'First version' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(state.calls.find((c) => c.url === '/workspaces/9/submit')).toBeTruthy());
    expect(state.calls.find((c) => c.url === '/workspaces/9/submit').body).toEqual({ note: 'First version' });
    expect(await screen.findByText(/Submitted version 1.0 → On-Roll review/)).toBeInTheDocument();
  });

  it('shows the file history and books the timer on the open task', async () => {
    state.handlers['get /tasks/7/workspace'] = () => Promise.resolve({ data: { id: 9, task_id: 7, user_id: 5, task_code: 'WC-0007', task_title: 'Build page', task_status: 'in_progress',
      read_only: false, last_saved_at: null, task_requirements: 'Make a page', files: [{ id: 11, path: 'index.html', content: '<h1>Hi</h1>' }] } });
    renderApp('/workspace/7', 'intern');
    await screen.findByLabelText('editor');
    fireEvent.click(screen.getByRole('button', { name: 'File history' }));
    expect(await screen.findByText('+1 -1 lines')).toBeInTheDocument();
    expect(screen.getByText(/Kabir Singh · .* · v1 → v2/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Task details' }));
    expect(await screen.findByText('Make a page')).toBeInTheDocument();
    fireEvent(window, new Event('focus'));
    await waitFor(() => expect(state.calls.some((c) => c.url === '/sessions/heartbeat' && c.body?.task_id === 7)).toBe(true), { timeout: 4000 });
  });
});

describe('communication, recordings and reports pages', () => {
  it('chat lists conversations, opens one and sends a message', async () => {
    renderApp('/chat', 'intern');
    fireEvent.click(await screen.findByText('Divya Rao', { selector: 'b' }));
    expect(await screen.findByText('Welcome!', { selector: 'div[style*="pre-wrap"]' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New group' })).not.toBeInTheDocument();   // interns cannot create groups
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Thanks' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'post' && c.url === '/chat/conversations/4/messages')?.body).toEqual({ body: 'Thanks' }));
  });
  it('meetings: an intern sees the meeting and a join link but cannot schedule', async () => {
    renderApp('/meetings', 'intern');
    expect(await screen.findByText('Sprint planning')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Join ↗' })).toHaveAttribute('href', 'https://meet.google.com/x');
    expect(screen.queryByRole('button', { name: 'Schedule a meeting' })).not.toBeInTheDocument();
  });
  it('meeting timer: Join starts it, the top bar shows it next to the work timer, Leave stops it; no work timer call is made', async () => {
    renderApp('/meetings', 'intern');
    const join = await screen.findByRole('link', { name: 'Join ↗' });
    expect(screen.queryByRole('status', { name: 'Meeting timer' })).toBeNull();          // not in a meeting: nothing in the top bar
    const before = state.calls.filter((c) => c.url.startsWith('/sessions')).length;
    join.addEventListener('click', (e) => e.preventDefault());                           // the test browser cannot open a new tab
    fireEvent.click(join);
    const pill = await screen.findByRole('status', { name: 'Meeting timer' });
    expect(pill).toHaveTextContent('00:01:0');
    expect(pill).toHaveTextContent('in meeting · Sprint planning');
    expect(screen.getByText('00:01:05', { selector: '.timer:not(.meeting-timer) .clock' })).toBeInTheDocument();   // the work timer still shows its own time
    expect(state.calls.some((c) => c.method === 'post' && c.url === '/meetings/1/join')).toBe(true);
    fireEvent.click(within(pill).getByRole('button', { name: 'Leave meeting' }));
    await waitFor(() => expect(screen.queryByRole('status', { name: 'Meeting timer' })).toBeNull());
    expect(state.calls.some((c) => c.method === 'post' && c.url === '/meetings/1/leave')).toBe(true);
    expect(screen.getByRole('link', { name: 'Join ↗' })).toBeInTheDocument();
    expect(within(screen.getByTestId('my-meeting-time')).getByText('1m 05s')).toBeInTheDocument();
    const after = state.calls.filter((c) => c.url.startsWith('/sessions') && ['/sessions/pause', '/sessions/resume', '/sessions/stop'].includes(c.url)).length;
    expect(after).toBe(0);
    expect(before).toBeGreaterThanOrEqual(0);
  });
  it('admin dashboard: work time and meeting time are two columns, with join / leave details and the total', async () => {
    renderApp('/admin', 'admin');
    const card = await screen.findByTestId('meeting-report');
    const row = (await within(card).findByText('Kabir Singh')).closest('tr');
    const cells = within(row).getAllByRole('cell').map((c) => c.textContent);
    expect(cells[1]).toBe('2h 00m');                      // work timer
    expect(cells[2]).toBe('30m 30s');                     // meeting timer
    expect(cells[5]).toBe('12 Nov 10:00:00 am');         // start of the first stay
    expect(cells[6]).toBe('12 Nov 10:20:30 am');         // end of the last stay that has one
    expect(cells[7]).toContain('In meeting · Sprint planning');
    expect(within(card).getByTestId('meeting-counts')).toHaveTextContent('1 meetings · 2 joins');
    expect(within(card).getByText('1 in a meeting now · 30m 30s meeting time in range')).toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: 'Join / leave details' }));
    const details = within(card).getByRole('table', { name: 'Join and leave details of Kabir Singh' });
    expect(within(details).getByText('20m 30s')).toBeInTheDocument();
    expect(within(details).getByText('Meeting tab closed')).toBeInTheDocument();
    expect(within(details).getByText('Automatic (browser extension)')).toBeInTheDocument();
    expect(within(details).getByText('still in the meeting')).toBeInTheDocument();
    expect(within(details).getByText('Total meeting duration').closest('tr')).toHaveTextContent('30m 30s');
    const quiet = within(card).getByText('Meena R').closest('tr');
    expect(within(quiet).queryByRole('button')).toBeNull();
  });
  it('meetings: a developer gets the schedule button', async () => {
    renderApp('/meetings', 'developer');
    expect(await screen.findByRole('button', { name: 'Schedule a meeting' })).toBeInTheDocument();
  });
  it('recordings show the real status and never claim an interrupted one is complete', async () => {
    renderApp('/recordings', 'intern');
    expect(await screen.findByText('interrupted')).toBeInTheDocument();
    expect(screen.getByText('2.0 MB')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
  });
  it('reports show database figures and export buttons', async () => {
    renderApp('/reports', 'intern');
    expect(await screen.findByText('WC-E0005')).toBeInTheDocument();
    expect(screen.getByText('4.50h')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export Excel' })).toBeInTheDocument();
  });
  it('the reports table keeps the regular hours, the Continue hours and the total apart', async () => {
    renderApp('/reports', 'intern');
    expect(await screen.findByText('WC-E0005')).toBeInTheDocument();
    const head = screen.getByRole('columnheader', { name: 'Extra h (Continue)' });
    expect(head).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Total h' })).toBeInTheDocument();
    const row = screen.getByText('WC-E0005').closest('tr');
    expect(within(row).getByText('4.5')).toBeInTheDocument();          // regular schedule only
    expect(within(row).getByText('0.5')).toBeInTheDocument();           // Continue schedule
    expect(within(row).getByTestId('total-hours')).toHaveTextContent('5');
    expect(screen.getByText('1.00h away · 0.50h extra')).toBeInTheDocument();   // the tile counts extra too
  });
});

describe('languages admin page', () => {
  it('lists languages with the real runner state and installs an image', async () => {
    renderApp('/languages', 'admin');
    expect(await screen.findByText('python:3.12-alpine')).toBeInTheDocument();
    expect(screen.getByText('missing')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Install' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'post' && c.url === '/languages/python/pull')).toBeTruthy());
  });
  it('is not reachable for an intern', async () => {
    renderApp('/languages', 'intern');
    await waitFor(() => expect(screen.queryByText('python:3.12-alpine')).not.toBeInTheDocument());
    expect(state.calls.find((c) => c.url === '/languages/python/pull')).toBeFalsy();
  });
});

describe('automatic timer', () => {
  const withMode = (mode, extra = {}) => ({ ...SESSION, inactivity_timeout_seconds: 300, inactivity_warning_seconds: 240,
    session: { ...SESSION.session, mode, ...extra } });
  const beats = () => state.calls.filter((c) => c.url === '/sessions/heartbeat');

  it('starts by itself on entering the app and shows the state the server decided', async () => {
    state.handlers['post /sessions/start'] = () => Promise.resolve({ data: withMode('PAUSED_EXTERNAL', { pause_reason: 'unapproved_site' }) });
    renderApp('/intern', 'intern');
    expect(await screen.findByText('paused · away')).toBeInTheDocument();
    expect(state.calls.find((c) => c.url === '/sessions/start').body.auto).toBe(true);
    expect(await screen.findByText('Reason: a website that is not approved is open')).toBeInTheDocument();
    expect(screen.getByText(/Browser extension: not connected/)).toBeInTheDocument();
  });

  it('does not restart after a manual stop until Start is pressed', async () => {
    state.handlers['post /sessions/start'] = (b) => Promise.resolve({ data: b.auto ? { session: null, manual_stop: true, today: {} } : withMode('RUNNING') });
    renderApp('/intern', 'intern');
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }));
    expect(await screen.findByText('running')).toBeInTheDocument();
    expect(state.calls.filter((c) => c.url === '/sessions/start').map((c) => c.body.auto)).toEqual([true, false]);
  });

  it('warns at 4 minutes, reports idle at 5 minutes, and resumes on the next input', async () => {
    const focus = vi.spyOn(document, 'hasFocus').mockReturnValue(true);
    const real = Date.now;
    let shift = 0;
    const clock = vi.spyOn(Date, 'now').mockImplementation(() => real() + shift);
    state.handlers['post /sessions/start'] = () => Promise.resolve({ data: withMode('RUNNING') });
    state.handlers['post /sessions/heartbeat'] = (b) => Promise.resolve({ data: b.state === 'idle'
      ? withMode('PAUSED_INACTIVE', { pause_reason: 'inactivity' }) : withMode('RUNNING') });
    try {
      renderApp('/intern', 'intern');
      expect(await screen.findByText('running')).toBeInTheDocument();
      expect(screen.queryByText(/timer pauses in/)).not.toBeInTheDocument();
      shift = 250000;                                                     // 4 min 10 s without input
      expect(await screen.findByText(/No activity: timer pauses in \d+s/, {}, { timeout: 3000 })).toBeInTheDocument();
      expect(beats().some((c) => c.body.state === 'idle')).toBe(false);
      shift = 301000;                                                     // 5 minutes passed
      await waitFor(() => expect(beats().at(-1)?.body.state).toBe('idle'), { timeout: 3000 });
      expect(await screen.findByText('Timer paused automatically: no activity for 5 minutes.')).toBeInTheDocument();
      expect(screen.getByText('paused · inactive')).toBeInTheDocument();
      fireEvent.keyDown(window, { key: 'a' });                            // genuine input
      await waitFor(() => expect(beats().at(-1).body.state).toBe('active'));
      expect(await screen.findByText('Timer resumed automatically.')).toBeInTheDocument();
    } finally { clock.mockRestore(); focus.mockRestore(); }
  });

  it('admin sees the timer report with period filters, history and the approved websites', async () => {
    renderApp('/monitoring', 'admin');
    expect(await screen.findByText('Automatic timer report')).toBeInTheDocument();
    const row = (await screen.findByText('Kabir Singh')).closest('tr');
    expect(within(row).getByText('Paused · inactive')).toBeInTheDocument();
    expect(within(row).getByText('2h 00m')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Yesterday' }));
    await waitFor(() => { const c = state.calls.filter((x) => x.url === '/timer/overview').at(-1); expect(c.body.start).toBe(c.body.end); expect(c.body.start).not.toBe(new Date().toLocaleDateString('en-CA')); });
    fireEvent.click(screen.getByRole('button', { name: 'Custom' }));
    expect(screen.getByLabelText('From')).toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: 'History' }));
    await screen.findByText(/Pause and resume history · Kabir Singh/);
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'History' })).toHaveLength(2));
    fireEvent.click(screen.getAllByRole('button', { name: 'History' }).at(-1));   // the session row inside the dialog
    expect(await screen.findByText(/no activity for 5 minutes/)).toBeInTheDocument();
  });

  it('the timer report shows meeting time as a breakdown that never inflates the total', async () => {
    renderApp('/monitoring', 'admin');
    const row = (await screen.findByText('Kabir Singh')).closest('tr');
    expect(screen.getByRole('columnheader', { name: 'Meeting Time' })).toBeInTheDocument();
    const cell = within(row).getByTestId('meeting-cell');
    expect(cell).toHaveTextContent('1h 30m');                                     // 5400 s of meetings
    expect(cell).toHaveTextContent('in meeting');                                  // a stay is still open
    const t = screen.getByTestId('range-totals');
    expect(within(screen.getByTestId('total-regular')).getByText('Regular working hours')).toBeInTheDocument();
    expect(within(screen.getByTestId('total-regular')).getByText('2h 00m')).toBeInTheDocument();
    expect(within(screen.getByTestId('total-extra')).getByText('1h 30m')).toBeInTheDocument();
    expect(within(screen.getByTestId('total-meeting')).getByText('1h 30m')).toBeInTheDocument();
    expect(within(screen.getByTestId('total-grand')).getByText('5h 00m')).toBeInTheDocument();   // 2h + 1.5h + 1.5h
    expect(t).toHaveTextContent('Active: 3h 30m');
    expect(t).toHaveTextContent('Paused: 15m 00s');
    expect(t).toHaveTextContent('Inactive: 10m 00s');
    // 2 h regular + 1.5 h extra: the 1.5 h of meetings inside that day are not added a second time
    expect(within(t).getByTestId('range-total-hours')).toHaveTextContent('Total working hours: 3h 30m');
    expect(within(t).getByTestId('range-meeting-outside')).toHaveTextContent('Meeting outside work: 30m 00s');
    // changing the filter re-reads the report, and the totals come back with it
    const before = state.calls.filter((x) => x.url === '/timer/overview').length;
    fireEvent.click(screen.getByRole('button', { name: 'This month' }));
    await waitFor(() => expect(state.calls.filter((x) => x.url === '/timer/overview').length).toBeGreaterThan(before));
    const last = state.calls.filter((x) => x.url === '/timer/overview').at(-1).body;
    expect(last.start.endsWith('-01')).toBe(true);                                   // the 1st of the month
    expect(screen.getByTestId('range-totals')).toBeInTheDocument();
  });

  it('the four summary cards add meeting hours into a Grand Total, for every filter', async () => {
    renderApp('/monitoring', 'admin');
    await screen.findByTestId('total-grand');
    expect(screen.getByTestId('total-grand')).toHaveTextContent('Grand total hours');
    expect(screen.getByTestId('total-grand')).toHaveTextContent('5h 00m');            // 2h + 1h 30m + 1h 30m
    expect(screen.getByTestId('range-total-hours')).toHaveTextContent('Total working hours: 3h 30m');   // no double count
    expect(screen.getByTestId('grand-cell')).toHaveTextContent('5h 00m');             // the same figure per employee
    expect(screen.getByTestId('grand-total-note')).toHaveTextContent('adds the 1h 30m of meetings on purpose');
    const before = state.calls.filter((x) => x.url === '/timer/overview').length;
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'intern' } });  // role filter -> new totals
    await waitFor(() => expect(state.calls.filter((x) => x.url === '/timer/overview').length).toBeGreaterThan(before));
    expect(state.calls.filter((x) => x.url === '/timer/overview').at(-1).body.role).toBe('intern');
    expect(screen.getByTestId('total-grand')).toBeInTheDocument();
  });

  it('the meeting report exports the same filtered rows and adds start and end times', async () => {
    renderApp('/admin', 'admin');
    const card = await screen.findByTestId('meeting-report');
    expect(within(card).getByRole('columnheader', { name: 'Start' })).toBeInTheDocument();
    expect(within(card).getByRole('columnheader', { name: 'End' })).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => {
      const c = state.calls.filter((x) => x.url === '/meetings/timer/report').at(-1);
      expect(c.body.format).toBe('csv');
      expect(c.body.start).toBe(c.body.end);
    });
  });

  it('an employee sees their own meeting duration for today, this week and this month', async () => {
    renderApp('/meetings', 'intern');
    const card = await screen.findByTestId('my-meeting-time');
    await within(card).findByText('1h 07m');                                                   // 4025 s = this week
    expect(within(card).getByText('2h 20m')).toBeInTheDocument();                             // 8425 s = this month
    expect(within(card).getByText('0m 00s')).toBeInTheDocument();                             // today, same payload
  });

  it('admin adds an approved website; employees can only read the list', async () => {
    renderApp('/monitoring', 'admin');
    fireEvent.change(await screen.findByLabelText('Website domain'), { target: { value: 'figma.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add website' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'post' && c.url === '/timer/allowlist').body.domain).toBe('figma.com'));
    expect(screen.getByRole('button', { name: 'Remove chatgpt.com' })).toBeInTheDocument();
  });
});

const ANSWER = ['The heading is wrong. **Fix:**', '', '```html path=index.html', '<h1>Hello</h1>', '```', '', 'A helper:', '', '```js',
  'const add = (a, b) => a + b;', '```', '', 'Then run:', '', '```bash', 'npm test', 'rm -rf node_modules', '```', '', '<script>alert(1)</script>'].join('\n');
const answerStream = (text = ANSWER) => async (path, body, onEvent) => {
  state.asked = { path, body };
  onEvent({ type: 'start', message_id: 51, user_message_id: 50, conversation_id: 21, title: 'Fix the heading', model: 'gpt-test', context: [{ kind: 'file', path: 'index.html', chars: 11, truncated: false }] });
  onEvent({ type: 'delta', text: text.slice(0, 20) });
  onEvent({ type: 'delta', text: text.slice(20) });
  onEvent({ type: 'done', status: 'ok', message: { id: 51, role: 'assistant', content: text, status: 'ok', saved: false, model: 'gpt-test' } });
};
const openAI = async () => {
  renderApp('/workspace/7', 'intern');
  await screen.findByLabelText('editor');
  const toggle = screen.getByRole('button', { name: '✦ AI' });
  if (toggle.getAttribute('aria-pressed') !== 'true') fireEvent.click(toggle);      // the open/closed state is remembered
  const panel = await screen.findByRole('complementary', { name: 'AI Assistant' });
  await within(panel).findByRole('option', { name: 'gpt-test' });
  return panel;
};

describe('AI assistant', () => {
  it('opens on the right, answers with the open file as context, and puts code into the editor', async () => {
    state.stream = answerStream();
    const panel = await openAI();
    expect(within(panel).getByText('97 left')).toBeInTheDocument();
    for (const name of ['Explain selected code', 'Fix selected code', 'Review current file', 'Analyze project', 'Fix terminal error', 'Generate tests']) expect(within(panel).getByRole('button', { name })).toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText('AI model'), { target: { value: '1:gpt-mini' } });
    fireEvent.change(within(panel).getByLabelText('Message to AI'), { target: { value: 'Fix the heading' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Send ➤' }));
    expect(await within(panel).findByText('const add = (a, b) => a + b;')).toBeInTheDocument();
    expect(state.asked.path).toBe('/ai/conversations/21/messages');
    expect(state.asked.body).toMatchObject({ content: 'Fix the heading', model: '1:gpt-mini', workspace_id: 9,
      context: { active_path: 'index.html', active_content: '<h1>Hi</h1>', selection: null, project: false } });
    expect(state.calls.find((c) => c.url === '/ai/conversations' && c.method === 'post').body).toEqual({ workspace_id: 9 });
    expect(within(panel).getByText('Fix:').tagName).toBe('B');                                   // markdown
    expect(within(panel).getByText('<script>alert(1)</script>')).toBeInTheDocument();             // shown as text, never run
    expect(document.querySelector('.ai-panel script')).toBeNull();
    expect(within(panel).getByText(/📎 index.html/)).toBeInTheDocument();
    // insert the snippet at the cursor: it goes through the editor, so it becomes an unsaved change like typing
    fireEvent.click(within(panel).getAllByRole('button', { name: 'Insert at cursor' })[1]);
    expect(state.edits).toEqual([{ source: 'ai-assistant', text: 'const add = (a, b) => a + b;' }]);
    expect(screen.getByLabelText('editor').value).toBe('<h1>Hi</h1>const add = (a, b) => a + b;');
    expect(await within(panel).findByText('Code inserted')).toBeInTheDocument();
    fireEvent.click(within(panel).getAllByRole('button', { name: 'Replace selection' })[1]);      // nothing selected
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Select the code you want to replace first.');
    // shell block: a risky command needs an extra confirmation and is never run automatically
    fireEvent.click(within(panel).getByRole('button', { name: 'Send to terminal' }));
    const warn = await screen.findByRole('dialog', { name: 'This command can delete or overwrite data' });
    fireEvent.click(within(warn).getByRole('button', { name: 'Put it in the terminal anyway' }));
    await waitFor(() => expect(screen.getByLabelText('Suggested command')).toHaveTextContent('npm test'));
    expect(screen.getByRole('button', { name: 'Put in terminal' })).toBeDisabled();           // no shell yet, and never run by itself
    expect(screen.getByText(/1 more suggested/)).toBeInTheDocument();
    expect(state.calls.some((c) => c.url.includes('/run'))).toBe(false);
    fireEvent.click(within(panel).getByRole('button', { name: 'Close AI panel' }));
    expect(screen.queryByRole('complementary', { name: 'AI Assistant' })).not.toBeInTheDocument();
  });

  it('previews a diff, lets the user reject, and applies only accepted files', async () => {
    const two = `${ANSWER}\n\n\`\`\`css path=style.css\nh1 { color: red }\n\`\`\``;
    state.stream = answerStream(two);
    state.handlers['post /ai/patch/preview'] = () => Promise.resolve({ data: { can_apply: true, reason: null, files: [
      { path: 'index.html', status: 'modified', lines_added: 1, lines_removed: 1, diff: '--- current/index.html\n+++ proposed/index.html\n@@ -1 +1 @@\n-<h1>Hi</h1>\n+<h1>Hello</h1>' },
      { path: 'style.css', status: 'new', lines_added: 1, lines_removed: 0, diff: '+++ proposed/style.css\n+h1 { color: red }' }] } });
    state.handlers['post /ai/patch/apply'] = (b) => Promise.resolve({ data: { applied: b.changes.map((c, i) => ({ id: c.path === 'index.html' ? 11 : 30 + i, path: c.path, content: c.content })),
      unchanged: 0, last_saved_at: '2026-11-13T10:00:00Z', task_status: 'in_progress' } });
    const panel = await openAI();
    fireEvent.change(within(panel).getByLabelText('Message to AI'), { target: { value: 'Fix it' } });
    fireEvent.keyDown(within(panel).getByLabelText('Message to AI'), { key: 'Enter' });
    fireEvent.click(await within(panel).findByRole('button', { name: 'Preview all 2 files' }));
    let dialog = await screen.findByRole('dialog', { name: 'Preview changes' });
    expect(await within(dialog).findByText('+<h1>Hello</h1>')).toHaveClass('add');
    expect(within(dialog).getByText('-<h1>Hi</h1>')).toHaveClass('del');
    expect(state.calls.find((c) => c.url === '/ai/patch/preview').body.changes.map((c) => c.path)).toEqual(['index.html', 'style.css']);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject all' }));                  // reject: nothing is written
    expect(state.calls.some((c) => c.url === '/ai/patch/apply')).toBe(false);
    expect(screen.getByLabelText('editor').value).toBe('<h1>Hi</h1>');
    fireEvent.click(within(panel).getByRole('button', { name: 'Preview all 2 files' }));
    dialog = await screen.findByRole('dialog', { name: 'Preview changes' });
    fireEvent.click(await within(dialog).findByLabelText('Accept style.css'));                    // reject one file, accept the other
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply 1 file' }));
    await waitFor(() => expect(state.calls.find((c) => c.url === '/ai/patch/apply')).toBeTruthy());
    expect(state.calls.find((c) => c.url === '/ai/patch/apply').body).toEqual({ workspace_id: 9, changes: [{ path: 'index.html', content: '<h1>Hello</h1>\n' }] });
    await waitFor(() => expect(screen.getByLabelText('editor').value).toBe('<h1>Hello</h1>\n'));  // the real file changed in the editor
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('quick actions use the selection, and say so when there is none', async () => {
    state.stream = answerStream('It adds two numbers.');
    const panel = await openAI();
    fireEvent.click(within(panel).getByRole('button', { name: 'Explain selected code' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Select some code in the editor first.');
    fireEvent.click(within(panel).getByRole('button', { name: 'Fix terminal error' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('There is no terminal or run output yet');
    state.selection = '<h1>Hi</h1>';
    fireEvent.click(within(panel).getByRole('button', { name: 'Explain selected code' }));
    expect(await within(panel).findByText('It adds two numbers.')).toBeInTheDocument();
    expect(state.asked.body.context).toMatchObject({ selection: '<h1>Hi</h1>', active_path: 'index.html' });
    fireEvent.click(within(panel).getByRole('button', { name: 'Analyze project' }));
    await waitFor(() => expect(state.asked.body.context).toMatchObject({ project: true, tree: true }));
    // regenerate and save
    state.handlers['patch /ai/messages/51'] = (b) => Promise.resolve({ data: { saved: b.saved } });
    fireEvent.click(within(panel).getAllByRole('button', { name: '☆ Save' }).pop());
    expect((await within(panel).findAllByRole('button', { name: '★ Saved' })).length).toBeGreaterThan(0);   // both mock answers share id 51
    expect(state.calls.find((c) => c.method === 'patch' && c.url === '/ai/messages/51').body).toEqual({ saved: true });
    fireEvent.click(within(panel).getByRole('button', { name: '↻ Regenerate' }));
    await waitFor(() => expect(state.asked.path).toBe('/ai/conversations/21/regenerate'));
  });

  it('shows an honest message when AI is not set up, and provider errors from the stream', async () => {
    state.handlers['get /ai/status'] = () => Promise.resolve({ data: { can_use: false, configured: false, models: [], used_today: 0, daily_limit: 100,
      reason: 'The AI assistant is not set up yet. Ask an administrator to add an AI provider.' } });
    renderApp('/workspace/7', 'intern');
    await screen.findByLabelText('editor');
    if (screen.getByRole('button', { name: '✦ AI' }).getAttribute('aria-pressed') !== 'true') fireEvent.click(screen.getByRole('button', { name: '✦ AI' }));
    const panel = await screen.findByRole('complementary', { name: 'AI Assistant' });
    expect(await within(panel).findByText(/not set up yet/)).toBeInTheDocument();
    expect(within(panel).getByLabelText('Message to AI')).toBeDisabled();
    expect(within(panel).getByRole('button', { name: 'Review current file' })).toBeDisabled();
  });

  it('stop asks the server to stop; a failed answer shows the provider message', async () => {
    let finish;
    state.handlers['post /ai/messages/51/stop'] = () => Promise.resolve({ data: { ok: true } });
    state.stream = (path, body, onEvent) => new Promise((resolve) => {
      onEvent({ type: 'start', message_id: 51, user_message_id: 50, title: 'Long', model: 'gpt-test', context: [] });
      onEvent({ type: 'delta', text: 'Working on it' });
      finish = () => { onEvent({ type: 'done', status: 'stopped', message: { id: 51, role: 'assistant', content: 'Working on it', status: 'stopped' } }); resolve(); };
    });
    const panel = await openAI();
    fireEvent.change(within(panel).getByLabelText('Message to AI'), { target: { value: 'Long one' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Send ➤' }));
    expect(await within(panel).findByRole('status', { name: 'AI is writing' })).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: '■ Stop' }));
    await waitFor(() => expect(state.calls.some((c) => c.url === '/ai/messages/51/stop')).toBe(true));
    finish();
    expect(await within(panel).findByText('Stopped.')).toBeInTheDocument();
    state.stream = async (path, body, onEvent) => {
      onEvent({ type: 'start', message_id: 61, user_message_id: 60, title: 'Long', model: 'gpt-test', context: [] });
      onEvent({ type: 'error', message: 'The AI provider is busy (rate limit). Wait a little and try again.', message_obj: { id: 61, role: 'assistant', content: '', status: 'error' } });
    };
    fireEvent.change(within(panel).getByLabelText('Message to AI'), { target: { value: 'again' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Send ➤' }));
    expect(await within(panel).findByText(/busy \(rate limit\)/)).toBeInTheDocument();
  });

  it('history: search, open, rename and delete a conversation', async () => {
    state.handlers['get /ai/conversations/21'] = () => Promise.resolve({ data: { id: 21, title: 'Closures', messages: [
      { id: 1, role: 'user', content: 'How do closures work?', status: 'ok' }, { id: 2, role: 'assistant', content: 'A closure remembers its scope.', status: 'ok' }] } });
    state.handlers['get /ai/conversations'] = (params) => Promise.resolve({ data: params?.q === 'zzz' ? [] : [{ id: 21, title: 'Closures', task_code: 'WC-0007', updated_at: '2026-11-12T10:00:00Z' }] });
    state.handlers['patch /ai/conversations/21'] = (b) => Promise.resolve({ data: { id: 21, title: b.title } });
    state.handlers['delete /ai/conversations/21'] = () => Promise.resolve({ data: { ok: true } });
    const panel = await openAI();
    fireEvent.click(within(panel).getByRole('button', { name: 'Chat history' }));
    expect(await within(panel).findByText('Closures')).toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText('Search conversations'), { target: { value: 'zzz' } });
    expect(await within(panel).findByText('No conversation matches.')).toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText('Search conversations'), { target: { value: '' } });
    fireEvent.click(await within(panel).findByRole('button', { name: 'Rename Closures' }));
    const dialog = await screen.findByRole('dialog', { name: 'Rename conversation' });
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'JS notes' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'OK' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'patch' && c.url === '/ai/conversations/21').body).toEqual({ title: 'JS notes' }));
    fireEvent.click(within(panel).getByText('Closures'));
    expect(await within(panel).findByText('A closure remembers its scope.')).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: 'Chat history' }));
    fireEvent.click(await within(panel).findByRole('button', { name: 'Delete Closures' }));
    fireEvent.click(within(await screen.findByRole('dialog', { name: 'Delete conversation' })).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(state.calls.some((c) => c.method === 'delete' && c.url === '/ai/conversations/21')).toBe(true));
  });

  it('copy protection: nothing is copied out, paste from outside works, shortcuts are not blocked', async () => {
    const panel = await openAI();
    const clip = (text = '') => { const d = { 'text/plain': text }; return { d, setData: (k, v) => { d[k] = v; }, getData: (k) => d[k] || '' }; };
    const fire = (target, type, data) => { const ev = new Event(type, { bubbles: true, cancelable: true }); ev.clipboardData = data; target.dispatchEvent(ev); return ev; };
    const input = within(panel).getByLabelText('Message to AI');
    fireEvent.change(input, { target: { value: 'const secret = 42;' } });
    input.setSelectionRange(0, 18);
    const out = clip();
    const ev = fire(input, 'copy', out);
    expect(ev.defaultPrevented).toBe(true);
    expect(out.d['text/plain']).toBe('Copying out of WORKCODE is not allowed.');                   // the real code never reaches the clipboard
    expect(JSON.stringify(out.d)).not.toContain('secret');
    expect(await screen.findByText(/Copied inside WORKCODE only/)).toBeInTheDocument();
    expect(fire(input, 'cut', clip()).defaultPrevented).toBe(true);
    expect(fire(input, 'paste', clip('text from another program')).defaultPrevented).toBe(false);   // paste from outside: untouched
    document.execCommand = vi.fn();
    expect(fire(input, 'paste', out).defaultPrevented).toBe(true);                                  // our own copy: pasted from memory
    expect(document.execCommand).toHaveBeenCalledWith('insertText', false, 'const secret = 42;');
    for (const target of [window, screen.getByLabelText('editor'), input]) {
      for (const key of ['c', 'v', 'x', 'a', 'z', 'y']) {
        const k = new KeyboardEvent('keydown', { key, ctrlKey: true, bubbles: true, cancelable: true });
        target.dispatchEvent(k);
        expect(k.defaultPrevented).toBe(false);
      }
    }
    // the Copy button on an AI answer also stays inside WORKCODE
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    state.stream = answerStream();
    fireEvent.change(input, { target: { value: 'Fix the heading' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Send ➤' }));
    await within(panel).findByText('const add = (a, b) => a + b;');
    fireEvent.click(within(panel).getAllByRole('button', { name: 'Copy code' })[0]);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Copying out of WORKCODE is not allowed.'));
    expect(writeText.mock.calls.flat().join(' ')).not.toContain('<h1>');
  });

  it('copy protection is off for Admin', async () => {
    renderApp('/ai-settings', 'admin');
    await screen.findByText('Providers');
    const ev = new Event('copy', { bubbles: true, cancelable: true });
    document.body.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
  });

  it('admin configures a provider: the key is sent once and never shown again', async () => {
    let providers = [{ id: 1, name: 'OpenAI', base_url: 'https://api.openai.com/v1', models: ['gpt-test'], default_model: 'gpt-test', is_enabled: true, key_set: true }];
    state.handlers['get /ai/providers'] = () => Promise.resolve({ data: providers });
    state.handlers['get /ai/settings'] = () => Promise.resolve({ data: { enabled: true, role_enabled: { admin: true, onroll: true, offroll: true, intern: true },
      daily_limits: { admin: 0, onroll: 200, offroll: 150, intern: 100 }, max_context_chars: 60000, max_output_tokens: 4000, extra_instructions: '' } });
    state.handlers['put /ai/settings'] = (b) => Promise.resolve({ data: b });
    state.handlers['get /ai/usage'] = () => Promise.resolve({ data: { days: 30, totals: { messages: 12, users: 1, prompt_tokens: 3000, completion_tokens: 900 }, by_model: [{ model: 'gpt-test', answers: 12 }],
      rows: [{ user_id: 5, full_name: 'Kabir Singh', role: 'intern', messages: 12, today: 3, prompt_tokens: 3000, completion_tokens: 900, errors: 1, last_used_at: '2026-11-12T10:00:00Z' }] } });
    state.handlers['post /ai/providers/2/test'] = () => Promise.resolve({ data: { ok: true, message: 'Connected. The provider offers 2 models.', models: ['llama-a', 'llama-b'] } });
    state.handlers['post /ai/providers'] = (b) => { providers = [...providers, { id: 2, ...b, api_key: undefined, key_set: !!b.api_key }]; return Promise.resolve({ data: providers[1] }); };
    state.handlers['patch /ai/providers/2'] = (b) => { providers[1] = { ...providers[1], ...b, api_key: undefined }; return Promise.resolve({ data: providers[1] }); };
    renderApp('/ai-settings', 'admin');
    expect(await screen.findByText('stored (hidden)')).toBeInTheDocument();
    expect(await screen.findByText('Kabir Singh')).toBeInTheDocument();
    expect(screen.getByText(/nobody, including administrators, can read/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Intern daily limit'), { target: { value: '50' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'put' && c.url === '/ai/settings').body.daily_limits.intern).toBe(50));
    fireEvent.click(screen.getByRole('button', { name: 'Add AI provider' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Service preset'), { target: { value: 'https://api.groq.com/openai/v1' } });
    fireEvent.change(within(dialog).getByLabelText('API key'), { target: { value: 'gsk-secret' } });
    expect(within(dialog).getByLabelText('API key')).toHaveAttribute('type', 'password');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save and test connection' }));
    expect(await within(dialog).findByText('Connected. The provider offers 2 models.')).toBeInTheDocument();
    expect(state.calls.find((c) => c.method === 'post' && c.url === '/ai/providers').body).toMatchObject({ name: 'Groq', base_url: 'https://api.groq.com/openai/v1', api_key: 'gsk-secret' });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'llama-b' }));
    expect(within(dialog).getByLabelText('API key').value).toBe('');                               // not echoed back after saving
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(state.calls.find((c) => c.method === 'patch' && c.url === '/ai/providers/2')).toBeTruthy());
    const sent = state.calls.find((c) => c.method === 'patch' && c.url === '/ai/providers/2').body;
    expect(sent.models).toEqual(['llama-b']);
    expect(sent).not.toHaveProperty('api_key');                                                    // empty = keep the stored key
  });

  it('an intern cannot open the AI settings page', async () => {
    renderApp('/ai-settings', 'intern');
    expect(await screen.findByText('Hi Kabir 👋')).toBeInTheDocument();
    expect(state.calls.some((c) => c.url.startsWith('/ai/providers'))).toBe(false);
  });
});

describe('workday schedule and the separate Continue schedule (build 29)', () => {
  it('8 h complete: the top bar offers Continue Working, and it starts the extra schedule', async () => {
    sessionStorage.setItem('wc-daydone:4', new Date().toLocaleDateString('en-CA'));   // the build 30 popup is answered; test the bar here
    state.handlers['post /sessions/start'] = () => Promise.resolve({ data: { ...SESSION, session: null, manual_stop: false,
      regular_completed: true, regular_remaining_seconds: 0, extra_seconds_today: 3600 } });
    renderApp('/', 'offroll');
    const card = await screen.findByTestId('day-complete');
    fireEvent.click(within(card).getByRole('button', { name: 'Continue Working' }));
    await waitFor(() => expect(state.calls.some((c) => c.method === 'post' && c.url === '/sessions/continue')).toBe(true));
  });
  it('a running regular session shows its progress toward the 8 h target', async () => {
    renderApp('/', 'offroll');
    const cell = await screen.findByTestId('regular-progress');
    expect(cell.textContent).toContain('08:00:00');
    expect(cell.textContent).toContain('07:58:55 to go');
  });
  it('the extra schedule is labelled apart from the regular one', async () => {
    state.handlers['post /sessions/start'] = () => Promise.resolve({ data: { ...SESSION, session: { ...SESSION.session, schedule: 'extra' } } });
    renderApp('/', 'offroll');
    expect(await screen.findByTestId('continue-schedule')).toBeInTheDocument();
  });
  it('the timer report shows schedule progress, continue time and the live recording dot', async () => {
    renderApp('/monitoring', 'admin');
    const cell = await screen.findByTestId('schedule-cell');
    expect(cell.textContent).toContain('1h 00m');
    expect(cell.textContent).toContain('8h 00m');
    expect(screen.getByText('● live')).toBeInTheDocument();
    expect(screen.getByText('30m 00s')).toBeInTheDocument();
  });
});

describe('8 h completion popup and admin extra work (build 30)', () => {
  const completed = () => Promise.resolve({ data: { ...SESSION, session: null, manual_stop: false, regular_completed: true,
    regular_remaining_seconds: 0, extra_seconds_today: 0 } });

  it('the popup appears at completion; Not Now closes it and starts nothing', async () => {
    state.handlers['post /sessions/start'] = completed;
    renderApp('/', 'onroll');
    const box = await screen.findByTestId('day-complete-modal');
    expect(box.textContent).toContain('Would you like to continue working?');
    fireEvent.click(within(box).getByRole('button', { name: 'Not Now' }));
    await waitFor(() => expect(screen.queryByTestId('day-complete-modal')).not.toBeInTheDocument());
    expect(state.calls.some((c) => c.url === '/sessions/continue')).toBe(false);
  });
  it('Continue Working from the popup starts the extra schedule', async () => {
    state.handlers['post /sessions/start'] = completed;
    renderApp('/', 'developer');
    const box = await screen.findByTestId('day-complete-modal');
    fireEvent.click(within(box).getByRole('button', { name: 'Continue Working' }));
    await waitFor(() => expect(state.calls.some((c) => c.method === 'post' && c.url === '/sessions/continue')).toBe(true));
  });
  it('the timer report shows the Schedule column and range totals', async () => {
    renderApp('/monitoring', 'admin');
    expect(await screen.findByTestId('schedule-col')).toHaveTextContent('Regular');
    const totals = screen.getByTestId('range-totals');
    expect(within(screen.getByTestId('total-regular')).getByText('2h 00m')).toBeInTheDocument();
    expect(within(screen.getByTestId('total-extra')).getByText('1h 30m')).toBeInTheDocument();
    expect(within(totals).getByTestId('range-total-hours')).toHaveTextContent('Total working hours: 3h 30m');
  });
  it('the admin dashboard lists regular vs extra work with the extra session times', async () => {
    renderApp('/', 'admin');
    const card = await screen.findByTestId('extra-work');
    expect(within(card).getByText('Kabir Singh')).toBeInTheDocument();
    expect(within(card).getByText('In progress')).toBeInTheDocument();
    expect(within(card).getByText('01:00:00')).toBeInTheDocument();
    expect(within(card).getByText('00:30:00')).toBeInTheDocument();
  });
  it('the employee dashboard shows the running continue timer apart from the 8 h', async () => {
    state.handlers['post /sessions/start'] = () => Promise.resolve({ data: { ...SESSION, extra_seconds_today: 3600,
      session: { ...SESSION.session, schedule: 'extra' } } });
    renderApp('/', 'offroll');
    expect(await screen.findByTestId('extra-timer')).toHaveTextContent('Continue schedule is running');
  });
});

describe('the workspace recording follows the tab (build 31)', () => {
  // A stand-in for the browser: getDisplayMedia hands back a stream, MediaRecorder does what it is told.
  let rec, share, hasFocus;
  function fakeBrowser() {
    const track = { stop: vi.fn(), addEventListener: (ev, fn) => { if (ev === 'ended') track.onended = fn; } };
    const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
    share = vi.fn(async () => stream);
    rec = { state: 'inactive', started: 0, pauses: 0, resumes: 0, stops: 0, listeners: {},
      start() { this.started += 1; this.state = 'recording'; },
      pause() { if (this.state === 'recording') { this.pauses += 1; this.state = 'paused'; } },
      resume() { if (this.state === 'paused') { this.resumes += 1; this.state = 'recording'; } },
      stop() { this.stops += 1; this.state = 'inactive';          // a browser hands over the last piece of video
               if (this.ondataavailable) this.ondataavailable({ data: { size: 4096, type: 'video/webm' } });
               (this.listeners.stop || []).forEach((f) => f()); },
      addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); } };
    class FakeRecorder {
      constructor() { return rec; }
      static isTypeSupported() { return true; }
    }
    Object.defineProperty(window.navigator, 'mediaDevices', { value: { getDisplayMedia: share }, configurable: true });
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    hasFocus = vi.spyOn(document, 'hasFocus').mockReturnValue(true);
    return { track, stream };
  }
  const flush = async (n = 8) => { for (let i = 0; i < n; i += 1) await act(async () => { await Promise.resolve(); }); };

  beforeEach(() => {
    fakeBrowser();
    localStorage.setItem('workcode_recording_consent:5', new Date().toISOString());   // this person agreed once already
    vi.useFakeTimers();
    state.handlers['get /recordings/policy'] = () => Promise.resolve({ data: { retention_days: 30, max_bytes: 2e9, away_grace_seconds: 60, storage: 'server' } });
    state.handlers['post /recordings/start'] = () => Promise.resolve({ data: { id: 8, status: 'recording' } });
    state.handlers['post /recordings/8/stop'] = () => Promise.resolve({ data: { id: 8, status: 'completed' } });
    state.handlers['post /recordings/8/chunk'] = () => Promise.resolve({ data: { seq: 1, bytes: 4096 } });
  });
  afterEach(() => {
    vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks();
    Object.defineProperty(window.navigator, 'mediaDevices', { value: undefined, configurable: true });
    localStorage.removeItem('workcode_recording_consent:5');
  });
  const leave = () => { hasFocus.mockReturnValue(false); act(() => { window.dispatchEvent(new Event('blur')); }); };
  const returnTo = () => { hasFocus.mockReturnValue(true); act(() => { window.dispatchEvent(new Event('focus')); }); };

  it('opens the recording by itself when the workspace is opened, and links it to the task', async () => {
    renderApp('/workspace/7', 'intern');
    await flush();
    expect(share).toHaveBeenCalledTimes(1);
    const start = state.calls.find((c) => c.url === '/recordings/start');
    expect(start.body).toEqual({ consent: true, task_id: 7, mime_type: 'video/webm' });
    expect(screen.getByTestId('workspace-recording')).toHaveTextContent('Recording Active');
    expect(rec.state).toBe('recording');
  });

  it('records nothing while the tab is not the window you are looking at, and resumes when you come back', async () => {
    renderApp('/workspace/7', 'intern');
    await flush();
    act(() => { vi.advanceTimersByTime(5000); });            // past the share dialog, which blurs the page itself
    leave();
    expect(rec.state).toBe('paused');
    expect(screen.getByTestId('workspace-recording')).toHaveTextContent('Paused — you left the tab');
    returnTo();
    expect(rec.state).toBe('recording');
    expect(screen.getByTestId('workspace-recording')).toHaveTextContent('Recording Active');
    expect(rec.stops).toBe(0);                                // a quick alt-tab costs no recording at all
  });

  it('the last piece of video is uploaded before the server is told the recording ended', async () => {
    renderApp('/workspace/7', 'intern');
    await flush();
    act(() => { vi.advanceTimersByTime(5000); });
    leave();
    act(() => { vi.advanceTimersByTime(60000); });            // the grace ran out: the recording is closed
    await flush(16);
    const tail = state.calls.findIndex((c) => c.url === '/recordings/8/chunk');
    const stop = state.calls.findIndex((c) => c.url === '/recordings/8/stop');
    expect(tail).toBeGreaterThanOrEqual(0);                    // nothing the person did is thrown away
    expect(stop).toBeGreaterThan(tail);                        // and it is on the server before the stop call
  });

  it('closes and saves the recording when the person stays away longer than the grace', async () => {
    renderApp('/workspace/7', 'intern');
    await flush();
    act(() => { vi.advanceTimersByTime(5000); });
    leave();
    act(() => { vi.advanceTimersByTime(60000); });
    await flush();
    expect(rec.state).toBe('inactive');
    expect(rec.stops).toBe(1);
    expect(state.calls.some((c) => c.url === '/recordings/8/stop')).toBe(true);
    expect(screen.getByTestId('workspace-recording')).toHaveTextContent('Record screen again');
  });

  it('a recording started with the Record button keeps running when the tab loses focus', async () => {
    renderApp('/tasks', 'intern');
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Record' }));   // the top-bar button: manual recording
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'I agree, start recording' }));
    await flush();
    expect(share).toHaveBeenCalledTimes(1);
    expect(state.calls.find((c) => c.url === '/recordings/start').body.task_id).toBeNull();   // not tied to a workspace
    act(() => { vi.advanceTimersByTime(5000); });
    leave();
    expect(rec.state).toBe('recording');
    expect(rec.pauses).toBe(0);
  });

  it('away_grace_seconds = 0 on the server means leaving the tab closes the recording at once', async () => {
    state.handlers['get /recordings/policy'] = () => Promise.resolve({ data: { retention_days: 30, away_grace_seconds: 0, storage: 'server' } });
    renderApp('/workspace/7', 'intern');
    await flush();
    act(() => { vi.advanceTimersByTime(5000); });
    leave();
    await flush();
    expect(rec.state).toBe('inactive');
    expect(state.calls.some((c) => c.url === '/recordings/8/stop')).toBe(true);
    expect(screen.getByTestId('workspace-recording')).toHaveTextContent('Record screen again');
  });

  it('does not restart a recording of its own accord: the browser needs a click for screen sharing', async () => {
    renderApp('/workspace/7', 'intern');
    await flush();
    act(() => { vi.advanceTimersByTime(5000); });
    leave();
    act(() => { vi.advanceTimersByTime(60000); });
    await flush();
    returnTo();
    await flush();
    expect(share).toHaveBeenCalledTimes(1);                      // only the one the person confirmed by opening the workspace
    expect(screen.getByTestId('workspace-recording')).toHaveTextContent('Record screen again');
  });
});

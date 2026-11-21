import { HOME } from '../utils/format';

/** One navigation menu per role, grouped like the sidebar: [section title, items].
 *  A page is listed only if it exists and that role may use it (the backend enforces the
 *  same rules again on every request). */
const dash = (role, label = 'My dashboard') => ({ to: HOME[role], label, ico: '◆' });
const TASKS = (label) => ({ to: '/tasks', label, ico: '☑' });
const CODE = { to: '/workspace', label: 'Coding workspace', ico: '⌨' };
const PROFILE = ['Account', [{ to: '/profile', label: 'Profile', ico: '◎' }]];
const MEET = { to: '/meetings', label: 'Meetings', ico: '◷' };
const CHAT = { to: '/chat', label: 'Chat', ico: '✉', chat: true };
const REC = (label) => ({ to: '/recordings', label, ico: '●' });
const REP = (label) => ({ to: '/reports', label, ico: '▤' });
const employee = (role, tasks) => [
  [null, [dash(role)]],
  ['Workspace', [TASKS(tasks), CODE, { to: '/reviews', label: role === 'onroll' ? 'Reviews' : 'My submissions', ico: '⌥', queue: role === 'onroll' },
    ...(role === 'onroll' ? [{ to: '/team', label: 'My team', ico: '👥' }] : []),
    MEET, REC(role === 'onroll' ? 'Recordings' : 'My recordings'), REP(role === 'onroll' ? 'Reports' : 'My reports'), CHAT]],
  PROFILE,
];

export const NAV = {
  admin: [
    ['Administration', [dash('admin', 'Overview'), { to: '/people', label: 'People', ico: '👥' }, { to: '/teams', label: 'Teams & projects', ico: '▦' },
      TASKS('Tasks'), { to: '/reviews', label: 'Code reviews', ico: '⌥', queue: true }, { to: '/monitoring', label: 'Monitoring', ico: '◉' },
      REC('Recordings'), REP('Reports'), { to: '/languages', label: 'Languages', ico: '⌨' }, { to: '/ai-settings', label: 'AI assistant', ico: '✦' }, MEET, CHAT, { to: '/audit', label: 'Audit log', ico: '▣' }]],
    PROFILE,
  ],
  onroll: employee('onroll', 'Tasks'),
  offroll: employee('offroll', 'My tasks'),
  intern: employee('intern', 'My tasks'),
};
NAV.developer = NAV.onroll; // retired role: old accounts get the On-Roll panel until the migration converts them

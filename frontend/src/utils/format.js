export const ROLE_LABEL = { admin: 'Administrator', onroll: 'On-Roll', offroll: 'Off-Roll', intern: 'Intern' };
export const HOME = { admin: '/admin', developer: '/onroll', onroll: '/onroll', offroll: '/offroll', intern: '/intern' };

export const STATUS_LABEL = {
  created: 'Created', assigned: 'Assigned', accepted: 'Accepted', in_progress: 'In progress', submitted: 'Submitted',
  under_onroll_review: 'Under On-Roll review', onroll_approved: 'On-Roll approved', onroll_rejected: 'On-Roll rejected',
  under_admin_review: 'Under Admin review', admin_approved: 'Admin approved', admin_rejected: 'Admin rejected',
  rework_required: 'Rework required', resubmitted: 'Resubmitted', completed: 'Completed', cancelled: 'Cancelled', archived: 'Archived',
  changes_requested: 'Rework requested', approved: 'Approved', rejected: 'Rejected',
  pending_onroll_review: 'Waiting for On-Roll', pending_admin_review: 'Waiting for Admin', none: '—',
};
/** The task statuses, in life-cycle order (same list as the backend). */
export const TASK_STATUSES = ['assigned', 'accepted', 'in_progress', 'under_onroll_review', 'under_admin_review', 'rework_required',
  'onroll_rejected', 'admin_rejected', 'completed', 'cancelled', 'archived'];
export const TASK_GROUPS = {
  open: ['assigned', 'accepted'], in_progress: ['in_progress'],
  submitted: ['submitted', 'resubmitted', 'under_onroll_review', 'onroll_approved', 'under_admin_review', 'admin_approved'],
  rework: ['rework_required', 'onroll_rejected', 'admin_rejected'], completed: ['completed'],
  pending_approval: ['under_admin_review'], onroll_review: ['under_onroll_review'], closed: ['cancelled', 'archived'],
};
const TONE = {
  completed: 'green', approved: 'green', admin_approved: 'green', onroll_approved: 'green', accepted: 'blue',
  rejected: 'red', onroll_rejected: 'red', admin_rejected: 'red', cancelled: 'red',
  changes_requested: 'amber', rework_required: 'amber', submitted: 'blue', resubmitted: 'blue',
  under_onroll_review: 'blue', under_admin_review: 'blue', pending_onroll_review: 'blue', pending_admin_review: 'blue',
  working: 'green', idle: 'amber', paused: '', active: 'green', inactive: 'red', left: 'red', urgent: 'red', high: 'amber',
};
export const tone = (s) => TONE[s] || '';
export const label = (s) => STATUS_LABEL[s] || (s ? s.replace(/_/g, ' ') : '—');

export function hms(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds || 0));
  const p = (n) => String(n).padStart(2, '0');
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}
export function dur(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(s % 60).padStart(2, '0')}s`;
}
export const fmtDate = (d) => (d ? new Date(d.length === 10 ? `${d}T00:00:00` : d).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—');
export const fmtDateTime = (d) => (d ? new Date(d).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');
/** 2026-11-12 20:27:13 in the viewer's local time. */
export function stamp(d) {
  if (!d) return '—';
  const t = new Date(d), p = (n) => String(n).padStart(2, '0');
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())} ${p(t.getHours())}:${p(t.getMinutes())}:${p(t.getSeconds())}`;
}

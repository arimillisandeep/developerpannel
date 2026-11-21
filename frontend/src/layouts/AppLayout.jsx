import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { installCopyGuard, onGuard } from '../services/copyGuard';
import { useNotifications } from '../context/NotificationContext';
import { REASON_TEXT, useTimer } from '../context/TimerContext';
import { useRecording } from '../context/RecordingContext';
import { ConfirmModal, Modal } from '../components/ui';
import { MeetingTimerPill } from '../components/MeetingTimer';
import { NAV } from '../routes/nav';
import { ROLE_LABEL, fmtDateTime, hms } from '../utils/format';

const TOP = { admin: ['Administrator', 'admin'], developer: ['Developer', 'developer'], onroll: ['Developer · On-Roll', 'onroll'],
  offroll: ['Developer · Off-Roll', 'offroll'], intern: ['Intern', 'intern'] };
export const initials = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');

const MODE_TEXT = { working: 'running', paused: 'paused by you', away: 'paused · away', idle: 'paused · inactive' };

function TimerWidget() {
  const t = useTimer();
  if (t.status === 'stopped') {
    if (t.regularCompleted) {
      return <div className="timer" data-testid="day-complete" title="The regular 8 hours are done. Extra time runs on its own Continue schedule.">
        <span className="dot" style={{ background: '#2fbf71' }} />
        <div><div className="clock">{hms(t.extraTodaySeconds)}</div><small>extra today · 8 h complete</small></div>
        <button className="btn small primary" onClick={t.continueSchedule}>Continue Working</button></div>;
    }
    return <div className="timer" title={t.manualStop ? 'You stopped the timer. It starts again only when you press Start.' : ''}>
      <span className="dot" /><div><div className="clock">00:00:00</div><small>stopped</small></div>
      <button className="btn small primary" onClick={t.start}>Start</button></div>;
  }
  const progress = t.schedule === 'extra'
    ? <small data-testid="continue-schedule">continue schedule · {hms(t.extraTodaySeconds)} extra today</small>
    : <small data-testid="regular-progress" title={`${hms(t.todayActiveSeconds)} of the regular 8 h counted today`}>
        {hms(t.todayActiveSeconds)} / {hms(t.targetSeconds)}{t.regularRemainingSeconds > 0 ? ` · ${hms(t.regularRemainingSeconds)} to go` : ''}</small>;
  return (
    <>
      {t.warningSeconds > 0 && <span className="timer-note warn" role="alert">No activity: timer pauses in {t.warningSeconds}s</span>}
      {t.warningSeconds === 0 && t.notice && <span className={`timer-note ${t.notice.tone}`} role="status" onClick={t.dismissNotice}>{t.notice.text}</span>}
      <div className="timer" title={t.pauseReason ? `Paused: ${REASON_TEXT[t.pauseReason] || t.pauseReason}` : 'Time is counted by the server'}>
        <span className={`dot ${t.status}`} /><div><div className="clock">{hms(t.activeSeconds)}</div>
          <small>{MODE_TEXT[t.status]}</small>{progress}</div>
        {t.status === 'paused'
          ? <button className="btn small" onClick={t.resume}>Resume</button>
          : <button className="btn small" onClick={t.pause}>Pause</button>}
        <button className="btn small danger" onClick={t.stop}>Stop</button>
      </div>
    </>
  );
}

function RecordButton() {
  const rec = useRecording();
  const [ask, setAsk] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => { if (rec.status !== 'recording') return undefined; const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t); }, [rec.status]);
  if (!rec.supported) return null;
  return (
    <>
      {rec.message && <span className="muted" style={{ maxWidth: 260, fontSize: 12.5 }} role="status">{rec.message}</span>}
      {rec.status === 'recording' || rec.status === 'paused'
        ? <span className="row inline" style={{ gap: 6 }}>
            <button className={`btn ${rec.status === 'recording' ? 'danger' : ''}`} onClick={rec.stop} title="Stop screen recording">
              <span className="dot" style={{ background: rec.status === 'paused' ? '#f0b429' : '#f04f5f', marginRight: 8 }} />
              {rec.status === 'paused' ? 'Recording Paused · Stop' : `REC ${hms((Date.now() - rec.startedAt) / 1000)} · Stop`}</button>
            <button className="btn" onClick={rec.status === 'paused' ? rec.resume : rec.pause}>{rec.status === 'paused' ? 'Resume' : 'Pause'}</button>
          </span>
        : <button className="btn" disabled={rec.status === 'starting'} onClick={() => setAsk(true)}>
            <span className="dot" style={{ background: '#e7ebf3', marginRight: 8 }} />{rec.status === 'starting' ? 'Waiting for permission…' : 'Record'}</button>}
      {ask && <ConfirmModal title="Record your screen" confirmLabel="I agree, start recording" onClose={() => setAsk(false)}
        onConfirm={() => { setAsk(false); rec.acceptConsent(); rec.start(); }}
        text={`Your screen will be recorded and stored privately on the company server. You, your team's On-Roll lead and Admins can watch it; recordings are deleted automatically after ${rec.retentionDays} days. The browser will now ask which screen to share; recording runs only while sharing is on, and you can pause or stop at any time.`}
      />}
    </>
  );
}

/** Build 30: when the server closes the regular 8-hour schedule, the employee is asked — Continue Working or Not Now. */
function DayCompleteModal() {
  const t = useTimer();
  const { user } = useAuth();
  const today = new Date().toLocaleDateString('en-CA');
  const key = `wc-daydone:${user.id}`;
  const [off, setOff] = useState(() => sessionStorage.getItem(key) === today);
  useEffect(() => { if (t.session || !t.regularCompleted) setOff(false); }, [t.session, t.regularCompleted]);
  if (!(t.regularCompleted && !t.session && !off)) return null;
  const notNow = () => { sessionStorage.setItem(key, today); setOff(true); };
  return (
    <Modal title="Your 8-Hour Work Schedule Is Completed!" onClose={notNow}>
      <div data-testid="day-complete-modal">
        <p>Your regular working hours are complete for today.</p>
        <p>Would you like to continue working? Extra time runs on its own schedule and never adds to the regular 8 hours.</p>
        <div className="modal-foot">
          <button className="btn" onClick={notNow}>Not Now</button>
          <button className="btn primary" onClick={t.continueSchedule}>Continue Working</button>
        </div>
      </div>
    </Modal>);
}

function Bell() {
  const { items, unread, live, markRead, markAll } = useNotifications();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const openItem = async (n) => {
    if (!n.is_read) await markRead(n.id);
    setOpen(false);
    if (n.link) navigate(n.link);
  };
  return (
    <div className="bell">
      <button className="btn" onClick={() => setOpen(!open)} aria-label="Notifications">🔔{unread > 0 && <span className="n">{unread}</span>}</button>
      {open && (
        <div className="dropdown">
          <div className="row spread" style={{ padding: '11px 14px', borderBottom: '1px solid var(--line)' }}>
            <b>Notifications</b>
            <span className="row"><small className="muted">{live ? 'live' : 'reconnecting…'}</small>
              <button className="btn small" disabled={!unread} onClick={markAll}>Mark all as read</button></span>
          </div>
          {items.length === 0 && <div className="empty">No notifications yet.</div>}
          {items.map((n) => (
            <div key={n.id} className={`item ${n.is_read ? '' : 'unread'}`} onClick={() => openItem(n)}>
              <div><b>{n.title}</b></div>{n.body && <div>{n.body}</div>}<small>{fmtDateTime(n.created_at)}</small>
            </div>))}
        </div>)}
    </div>
  );
}

export default function AppLayout() {
  const { user, logout } = useAuth();
  const { version, chatEvent } = useNotifications();
  const [queue, setQueue] = useState(0);
  const [chatUnread, setChatUnread] = useState(0);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const canReview = user.role === 'admin' || user.role === 'onroll';
  // Copy protection for everyone except Admin: nothing is copied out of WORKCODE; paste into it still works.
  const [guardHint, setGuardHint] = useState('');
  useEffect(() => {
    const remove = installCopyGuard(user.role !== 'admin');
    let t;
    const off = onGuard((what) => {
      setGuardHint(what === 'drag' ? 'Dragging text out of WORKCODE is not allowed.' : 'Copied inside WORKCODE only. You can paste it here, not in other programs.');
      clearTimeout(t); t = setTimeout(() => setGuardHint(''), 3500);
    });
    return () => { remove(); off(); clearTimeout(t); };
  }, [user.role]);

  useEffect(() => {
    if (!canReview) return;
    api.get('/submissions', { params: { view: 'queue' } }).then((r) => setQueue(r.data.length)).catch(() => {});
  }, [canReview, version]);

  useEffect(() => {
    api.get('/chat/conversations').then((r) => setChatUnread(r.data.reduce((a, c) => a + c.unread, 0))).catch(() => {});
  }, [chatEvent, pathname]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo">WC</div><div><b>WORKCODE</b><small>DEV PLATFORM</small></div></div>
        <nav className="nav">
          {NAV[user.role].map(([section, items]) => (
            <div key={section || 'top'}>
              {section && <div className="section">{section}</div>}
              {items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.to === '/workspace' ? false : undefined}>
                  <span className="ico" aria-hidden="true">{item.ico}</span><span>{item.label}</span>
                  {item.queue && queue > 0 && <span className="count">{queue}</span>}
                  {item.chat && chatUnread > 0 && <span className="count">{chatUnread}</span>}</NavLink>))}
            </div>))}
        </nav>
        <div className="me">
          <div className="who"><div className="avatar">{initials(user.full_name)}</div>
            <div><b>{user.full_name}</b><div className="role">{ROLE_LABEL[user.role]}{user.employee_code ? ` · ${user.employee_code}` : ''}</div></div></div>
          <button className="btn small" onClick={async () => { await logout(); navigate('/login'); }}>Sign out</button>
        </div>
      </aside>
      <div style={{ minWidth: 0 }}>
        <header className="topbar">
          <div className="title"><span className="eyebrow">{TOP[user.role][0]}</span><b>{TOP[user.role][1]}</b></div>
          <TimerWidget /><MeetingTimerPill /><RecordButton /><Bell /><DayCompleteModal />
        </header>
        <Outlet />
      </div>
      {guardHint && <div role="status" style={{ position: 'fixed', left: '50%', bottom: 28, transform: 'translateX(-50%)', zIndex: 9999, background: '#1f2a44', color: '#fff',
        border: '1px solid #3b4a72', borderRadius: 8, padding: '8px 14px', fontSize: 13, boxShadow: '0 6px 24px rgba(0,0,0,.4)' }}>🔒 {guardHint}</div>}
    </div>
  );
}

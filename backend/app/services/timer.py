"""Server-authoritative automatic work timer.

The server decides the timer state ("mode") from three inputs and measures all time itself:
  1. the WORKCODE tab's heartbeat: active (focused, input in the last 5 min) / idle / away
  2. the browser extension's report: which kind of site is in front (workcode / approved / unapproved / unfocused)
  3. the manual Pause button

Modes:  RUNNING · PAUSED_INACTIVE · PAUSED_EXTERNAL · PAUSED_MANUAL   (ended sessions: STOPPED · SESSION_EXPIRED)
Only RUNNING is working time. Clock values from the browser are never used. A silent gap longer than
HEARTBEAT_MAX_GAP_SECONDS is not credited (a sleeping laptop cannot produce hours).
Without a fresh extension report the safe policy applies: leaving the WORKCODE tab pauses the timer.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import Attendance, TaskTime, TimerEvent, User, WorkSession, utcnow
from app.services.common import local_day

CLIENT_STATES = {"active", "away", "idle"}
RUNNING, P_INACTIVE, P_EXTERNAL, P_MANUAL = "RUNNING", "PAUSED_INACTIVE", "PAUSED_EXTERNAL", "PAUSED_MANUAL"
STOPPED, EXPIRED = "STOPPED", "SESSION_EXPIRED"
DAY_COMPLETE = "day_complete"
BUCKET = {RUNNING: "active_seconds", P_INACTIVE: "idle_seconds", P_EXTERNAL: "away_seconds", P_MANUAL: "paused_seconds"}
EXT_CATEGORIES = {"workcode", "approved", "unapproved", "unfocused"}
REGULAR, EXTRA = "regular", "extra"          # work_sessions.schedule (build 29)
SCHEDULES = {REGULAR, EXTRA}
TARGET_ROLES = {"developer", "onroll", "offroll"}   # the 8 h schedule applies to these roles


def target_seconds() -> int:
    return int(round(settings.WORKDAY_TARGET_HOURS * 3600))


def _attendance_of(db: Session, user_id: int, now: datetime) -> Attendance | None:
    return db.query(Attendance).filter_by(user_id=user_id, day=local_day(now)).first()


def regular_done(db: Session, user_id: int, now: datetime | None = None) -> bool:
    """The day's regular schedule counts as complete once it was marked or the active time reached the target."""
    now = now or utcnow()
    att = _attendance_of(db, user_id, now)
    if att is None:
        return False
    if att.regular_completed_at is not None:
        return True
    u = db.get(User, user_id)
    return u is not None and u.role in TARGET_ROLES and att.active_seconds >= target_seconds()


def _attendance(db: Session, user_id: int, now: datetime) -> Attendance:
    day = local_day(now)
    row = db.query(Attendance).filter_by(user_id=user_id, day=day).first()
    if not row:
        row = Attendance(user_id=user_id, day=day, first_login_at=now, active_seconds=0, away_seconds=0,
                         idle_seconds=0, paused_seconds=0, status="present")
        db.add(row)
        db.flush()
    return row


def ext_fresh(s: WorkSession, now: datetime) -> bool:
    return s.ext_at is not None and (now - s.ext_at).total_seconds() <= settings.EXTENSION_FRESH_SECONDS


def compute_mode(s: WorkSession, now: datetime) -> tuple[str, str, str | None]:
    """-> (mode, reason, category)"""
    if s.state == "paused":
        return P_MANUAL, "manual_pause", None
    if s.client_state == "active":      # the WORKCODE tab itself is in front and has recent genuine input
        return RUNNING, "activity", "workcode"
    if ext_fresh(s, now):
        c = s.ext_category
        if c == "approved":
            return (P_INACTIVE, "inactivity", None) if s.ext_idle else (RUNNING, "approved_site", "approved_external")
        if c == "workcode":
            if s.client_state == "idle" or s.ext_idle:
                return P_INACTIVE, "inactivity", None
            return RUNNING, "activity", "workcode"
        return P_EXTERNAL, ("left_browser" if c == "unfocused" else "unapproved_site"), None
    if s.client_state == "idle":
        return P_INACTIVE, "inactivity", None
    return P_EXTERNAL, "left_workcode", None


def category_of(s: WorkSession, now: datetime) -> str | None:
    return compute_mode(s, now)[2] if s.state != "ended" else None


def _event(db: Session, s: WorkSession, at: datetime, to_state: str, reason: str, category: str | None = None):
    db.add(TimerEvent(user_id=s.user_id, session_id=s.id, at=at, from_state=s.mode if s.id and to_state != s.mode else None,
                      to_state=to_state, reason=reason, category=category))


def _credit(db: Session, s: WorkSession, now: datetime):
    """Credit the interval since the last report to the mode that was in effect."""
    elapsed = (now - s.last_heartbeat_at).total_seconds()
    seconds = int(max(0, min(elapsed, settings.HEARTBEAT_MAX_GAP_SECONDS)))
    s.last_heartbeat_at = now
    if seconds == 0 or s.state == "ended":
        return
    mode = s.mode
    # the mode was RUNNING only because of the extension, and the extension went silent: do not count it
    if mode == RUNNING and s.client_state != "active" and not ext_fresh(s, now):
        mode = P_EXTERNAL
    bucket = BUCKET[mode]
    setattr(s, bucket, getattr(s, bucket) + seconds)
    att = _attendance(db, s.user_id, now)
    if s.schedule == EXTRA:
        # the Continue schedule: its own column; the regular day totals never move
        att.extra_seconds += seconds
    else:
        setattr(att, bucket, getattr(att, bucket) + seconds)
    att.last_seen_at = now
    if s.task_id:                       # the same seconds, also booked on the task that is open
        row = db.query(TaskTime).filter_by(task_id=s.task_id, user_id=s.user_id).first()
        if row is None:
            row = TaskTime(task_id=s.task_id, user_id=s.user_id, active_seconds=0, paused_seconds=0, first_at=now)
            db.add(row)
            db.flush()
        if mode == RUNNING:
            row.active_seconds += seconds
        else:
            row.paused_seconds += seconds
        row.last_at = now


def _refresh(db: Session, s: WorkSession, now: datetime):
    """Recompute the mode after new input; record the transition when it changes."""
    mode, reason, category = compute_mode(s, now)
    if mode == RUNNING:
        s.last_activity_at = now
    if mode != s.mode:
        if mode != RUNNING and reason == "left_workcode" and s.ext_at is not None:
            reason = "extension_lost"
        _event(db, s, now, mode, reason, category)
        if mode == RUNNING:
            s.last_return_at = now
        s.mode = mode


def current(db: Session, user_id: int) -> WorkSession | None:
    return (db.query(WorkSession).filter(WorkSession.user_id == user_id, WorkSession.state != "ended")
            .order_by(WorkSession.id.desc()).first())


def last_ended(db: Session, user_id: int) -> WorkSession | None:
    return (db.query(WorkSession).filter(WorkSession.user_id == user_id, WorkSession.state == "ended")
            .order_by(WorkSession.id.desc()).first())


def end(db: Session, s: WorkSession, reason: str, now: datetime | None = None):
    now = now or utcnow()
    _credit(db, s, now)
    _event(db, s, now, STOPPED, reason)
    s.state, s.ended_at, s.end_reason, s.mode = "ended", s.last_heartbeat_at, reason, STOPPED


def sweep_regular(db: Session, s: WorkSession | None, now: datetime | None = None) -> bool:
    """Build 29: when a regular session has reached the 8 h target, mark the day complete and close the
    session. The employee then either leaves it stopped or starts the separate Continue schedule."""
    if s is None or s.state == "ended" or s.schedule != REGULAR:
        return False
    user = db.get(User, s.user_id)
    if user is None or user.role not in TARGET_ROLES:
        return False
    now = now or utcnow()
    att = _attendance_of(db, s.user_id, now)
    if att is None or att.active_seconds < target_seconds():
        return False
    if att.regular_completed_at is None:
        att.regular_completed_at = now
    end(db, s, DAY_COMPLETE, now)
    return True


def _expire(db: Session, s: WorkSession):
    """Nobody reported for a long time: close at the last report, credit nothing more."""
    _event(db, s, s.last_heartbeat_at, EXPIRED, "no_heartbeat")
    s.state, s.ended_at, s.end_reason, s.mode = "ended", s.last_heartbeat_at, "stale", EXPIRED


def expire_stale(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    n = 0
    for s in db.query(WorkSession).filter(WorkSession.state != "ended"):
        if (now - s.last_heartbeat_at).total_seconds() > settings.SESSION_STALE_SECONDS:
            _expire(db, s)
            n += 1
    return n


def manually_stopped_today(db: Session, user_id: int, now: datetime) -> bool:
    last = last_ended(db, user_id)
    return bool(last and last.end_reason == "stopped" and last.ended_at and local_day(last.ended_at) == local_day(now))


def start(db: Session, user_id: int, client_id: str, now: datetime | None = None, auto: bool = False,
          schedule: str = REGULAR) -> WorkSession | None:
    """auto=True is the automatic start when the app opens. It never overrides a manual Stop made today:
    then only the Start button (auto=False) starts a new session.
    schedule=EXTRA starts the separate Continue schedule; that needs the regular day to be complete,
    and an automatic start never opens one on its own."""
    now = now or utcnow()
    s = current(db, user_id)
    if s and (now - s.last_heartbeat_at).total_seconds() > settings.SESSION_STALE_SECONDS:
        _expire(db, s)
        s = None
    if s:  # one session per user, shared by all tabs and devices
        return s
    if schedule == EXTRA:
        if not regular_done(db, user_id, now):
            return None
    elif auto:
        if manually_stopped_today(db, user_id, now) or regular_done(db, user_id, now):
            return None
    s = WorkSession(user_id=user_id, started_at=now, last_heartbeat_at=now, state="running", mode=RUNNING,
                    client_state="active", client_id=client_id, active_seconds=0, away_seconds=0,
                    idle_seconds=0, paused_seconds=0, last_activity_at=now, ext_idle=False, schedule=schedule)
    db.add(s)
    _attendance(db, user_id, now)
    db.flush()
    db.add(TimerEvent(user_id=user_id, session_id=s.id, at=now, from_state=None, to_state=RUNNING,
                      reason="auto_start" if auto else "start", category="workcode"))
    return s


def heartbeat(db: Session, s: WorkSession, client_id: str, client_state: str,
              now: datetime | None = None, task_id: int | None = None) -> bool:
    """Returns True if this tab is the reporting tab. Only one tab reports: the holder.
    A different tab takes over only when it is the focused, visible one ("active")."""
    now = now or utcnow()
    if s.client_id != client_id:
        holder_silent = (now - s.last_heartbeat_at).total_seconds() > settings.HEARTBEAT_MAX_GAP_SECONDS
        if client_state != "active" and not holder_silent:
            return False
        _credit(db, s, now)
        s.client_id = client_id
    else:
        _credit(db, s, now)
    s.client_state = client_state
    s.task_id = task_id                 # credited from the next interval on
    _refresh(db, s, now)
    return True


def extension_report(db: Session, s: WorkSession, category: str, domain: str | None, idle: bool,
                     now: datetime | None = None):
    """Report from the browser extension. `category` and `domain` were already validated by the API."""
    now = now or utcnow()
    _credit(db, s, now)
    s.ext_category, s.ext_domain, s.ext_idle, s.ext_at = category, domain, idle, now
    _refresh(db, s, now)


def set_paused(db: Session, s: WorkSession, paused: bool, now: datetime | None = None):
    now = now or utcnow()
    _credit(db, s, now)
    s.state = "paused" if paused else "running"
    _refresh(db, s, now)


def pause_reason(db: Session, s: WorkSession) -> str | None:
    if s.mode == RUNNING:
        return None
    e = db.query(TimerEvent).filter_by(session_id=s.id, to_state=s.mode).order_by(TimerEvent.id.desc()).first()
    return e.reason if e else None


def session_dict(s: WorkSession | None, db: Session | None = None) -> dict | None:
    if not s:
        return None
    now = utcnow()
    return {"id": s.id, "state": s.state, "mode": s.mode, "schedule": s.schedule, "client_state": s.client_state, "client_id": s.client_id,
            "pause_reason": pause_reason(db, s) if db is not None and s.state != "ended" else None,
            "category": category_of(s, now), "extension_connected": ext_fresh(s, now),
            "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "last_heartbeat_at": s.last_heartbeat_at.isoformat(),
            "last_return_at": s.last_return_at.isoformat() if s.last_return_at else None,
            "last_activity_at": s.last_activity_at.isoformat() if s.last_activity_at else None,
            "active_seconds": s.active_seconds, "away_seconds": s.away_seconds,
            "idle_seconds": s.idle_seconds, "paused_seconds": s.paused_seconds,
            "server_time": now.isoformat()}

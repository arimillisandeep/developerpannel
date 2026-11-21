from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.models import Task
from app.services.workflow import EDITABLE

from app.core import permissions as P
from app.core.config import settings
from app.database.connection import get_db
from app.database.models import Attendance, User, WorkSession, utcnow
from app.dependencies.auth import get_current_user, require_roles
from app.schemas import ClientIn, HeartbeatIn
from app.services import timer
from app.services.common import commit, local_day

router = APIRouter(prefix="/api", tags=["time tracking"])


def _payload(db: Session, user_id: int, s, holder: bool = True) -> dict:
    now = utcnow()
    today = db.query(Attendance).filter_by(user_id=user_id, day=local_day(now)).first()
    last = (db.query(WorkSession).filter(WorkSession.user_id == user_id, WorkSession.state == "ended")
            .order_by(WorkSession.id.desc()).first())
    target = timer.target_seconds()
    active = today.active_seconds if today else 0
    return {"session": timer.session_dict(s, db), "is_reporting_tab": holder,
            "manual_stop": s is None and timer.manually_stopped_today(db, user_id, now),
            "inactivity_timeout_seconds": settings.INACTIVITY_TIMEOUT_SECONDS,
            "inactivity_warning_seconds": settings.INACTIVITY_WARNING_SECONDS,
            "last_logout_at": last.ended_at.isoformat() if last and last.ended_at else None,
            "heartbeat_seconds": 15,
            # build 29: the regular 8 h schedule and the separate Continue schedule
            "schedule_target_seconds": target, "regular_completed": timer.regular_done(db, user_id, now),
            "regular_completed_at": today.regular_completed_at.isoformat() if today and today.regular_completed_at else None,
            "regular_remaining_seconds": max(0, target - active),
            "extra_seconds_today": today.extra_seconds if today else 0,
            "today": {"active_seconds": active,
                      "away_seconds": (today.away_seconds + today.idle_seconds) if today else 0,
                      "paused_seconds": today.paused_seconds if today else 0,
                      "extra_seconds": today.extra_seconds if today else 0}}


@router.post("/sessions/start")
def start(body: ClientIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if timer.regular_done(db, user.id):
        # the day's 8 hours are done: an explicit Start presses on with the Continue schedule,
        # an automatic start (page open) stays off — the employee decides
        s = None if body.auto else timer.start(db, user.id, body.client_id, auto=False, schedule=timer.EXTRA)
    else:
        s = timer.start(db, user.id, body.client_id, auto=body.auto)
        timer.sweep_regular(db, s)
    commit(db)
    cur = timer.current(db, user.id)
    return _payload(db, user.id, cur, cur is None or cur.client_id == body.client_id)


@router.post("/sessions/continue")
def continue_schedule(body: ClientIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Start the separate Continue schedule after the regular 8 hours are complete (build 29).
    Its time never adds to the regular totals."""
    s = timer.current(db, user.id)
    if s is not None and s.schedule == timer.EXTRA:
        return _payload(db, user.id, s, s.client_id == body.client_id)      # already continuing
    if timer.sweep_regular(db, s):                                            # may close the regular one right at the target
        s = None
    if not timer.regular_done(db, user.id):
        raise HTTPException(409, "The regular 8 hours are not complete yet — keep working on the regular schedule.")
    s = timer.start(db, user.id, body.client_id, auto=False, schedule=timer.EXTRA)
    commit(db)
    return _payload(db, user.id, s, s is None or s.client_id == body.client_id)


@router.get("/sessions/current")
def get_current(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = timer.current(db, user.id)
    if timer.sweep_regular(db, s):          # a refresh must not re-open a day that finished while the tab was closed
        commit(db)
    return _payload(db, user.id, timer.current(db, user.id))


@router.post("/sessions/heartbeat")
def heartbeat(body: HeartbeatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = timer.current(db, user.id)
    if not s:
        raise HTTPException(409, "No running session. Start one first.")
    task_id = None
    if body.task_id:                    # only the user's own task that is being worked on
        t = db.get(Task, body.task_id)
        if t and t.assigned_to == user.id and t.deleted_at is None and t.status in EDITABLE:
            task_id = t.id
    holder = timer.heartbeat(db, s, body.client_id, body.state, task_id=task_id)
    completed = timer.sweep_regular(db, s)   # reaching the 8 h target closes the regular schedule on the spot
    commit(db)
    return _payload(db, user.id, None if completed else s, holder and not completed)


def _mine(db, user):
    s = timer.current(db, user.id)
    if not s:
        raise HTTPException(409, "No running session")
    return s


@router.post("/sessions/pause")
def pause(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _mine(db, user)
    timer.set_paused(db, s, True)
    commit(db)
    return _payload(db, user.id, s)


@router.post("/sessions/resume")
def resume(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _mine(db, user)
    timer.set_paused(db, s, False)
    commit(db)
    return _payload(db, user.id, s)


@router.post("/sessions/stop")
def stop(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _mine(db, user)
    timer.end(db, s, "stopped")
    commit(db)
    return _payload(db, user.id, None)


@router.get("/attendance")
def attendance(user_id: int | None = None, days: int = Query(30, ge=1, le=366),
               actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = user_id or actor.id
    if not P.can_view_user(db, actor, target):
        raise HTTPException(403, "You cannot view this attendance")
    today = local_day(utcnow())          # the server's own "today", in the configured working timezone
    since = today - timedelta(days=days - 1)
    rows = (db.query(Attendance).filter(Attendance.user_id == target, Attendance.day >= since)
            .order_by(Attendance.day.desc()).all())
    # build 34: the meeting timer next to the work timer, per day (the day a stay started owns its time)
    from app.api.timer_admin import meeting_breakdown_by_day      # local import, like the report does
    meets = meeting_breakdown_by_day(db, target, utcnow(), since, today)
    out = []
    for r in rows:
        m = meets.get(r.day, {})
        meeting = int(m.get("meeting_seconds") or 0)
        active, extra = int(r.active_seconds or 0), int(r.extra_seconds or 0)
        out.append({"day": r.day, "is_today": r.day == today,      # so the page does not have to guess the day
                    "active_seconds": r.active_seconds, "away_seconds": r.away_seconds + r.idle_seconds,
                    "paused_seconds": r.paused_seconds, "extra_seconds": r.extra_seconds,
                    "meeting_seconds": meeting, "meetings": m.get("meetings") or 0, "meeting_joins": m.get("meeting_joins") or 0,
                    "actual_seconds": active + extra, "total_seconds": active + extra + meeting,
                    "regular_completed_at": r.regular_completed_at,
                    "first_login_at": r.first_login_at,
                    "last_seen_at": r.last_seen_at, "status": r.status})
    return out


def live_state(s: WorkSession, now) -> str:
    """working | idle | paused | offline — judged by the server from heartbeat freshness."""
    if (now - s.last_heartbeat_at).total_seconds() > settings.HEARTBEAT_MAX_GAP_SECONDS * 2:
        return "offline"
    if s.mode == timer.P_MANUAL:
        return "paused"
    return "working" if s.mode == timer.RUNNING else "idle"


@router.get("/sessions/live")
def live(actor: User = Depends(require_roles(P.ADMIN, P.DEVELOPER, P.ONROLL)), db: Session = Depends(get_db)):
    now = utcnow()
    q = (db.query(WorkSession, User).join(User, User.id == WorkSession.user_id)
         .filter(WorkSession.state != "ended"))
    if actor.role in P.LEADS:
        q = q.filter(User.id.in_(P.team_member_ids(db, actor.id) or {-1}))
    out = []
    for s, u in q.order_by(User.full_name):
        st = live_state(s, now)
        if st != "offline":
            out.append({"user_id": u.id, "full_name": u.full_name, "role": u.role, "state": st,
                        "started_at": s.started_at, "active_seconds": s.active_seconds,
                        "away_seconds": s.away_seconds + s.idle_seconds, "last_heartbeat_at": s.last_heartbeat_at})
    return out

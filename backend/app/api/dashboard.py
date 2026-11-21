from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.database.connection import get_db
from app.database.models import (Attendance, Project, ScreenRecording, Submission, Task, Team, User,
                                 WorkSession, utcnow)
from app.dependencies.auth import get_current_user, require_roles
from app.api.sessions import live_state
from app.api.tasks import task_dict
from app.api.users import get_profile, intern_headcount
from app.services.common import local_day

router = APIRouter(prefix="/api/dashboard", tags=["dashboards"])

from app.services.workflow import IN_REVIEW, OPEN  # noqa: E402


def _task_counts(q) -> dict:
    by = dict(q.with_entities(Task.status, func.count(Task.id)).group_by(Task.status).all())
    return {"total": sum(by.values()), "by_status": by,
            "pending": sum(by.get(s, 0) for s in OPEN),
            "under_review": sum(by.get(s, 0) for s in IN_REVIEW),
            "completed": by.get("completed", 0) + by.get("archived", 0),
            "rejected": by.get("onroll_rejected", 0) + by.get("admin_rejected", 0),
            "rework": by.get("rework_required", 0)}


def _hours(db: Session, user_ids, start: date, end: date) -> float:
    q = db.query(func.coalesce(func.sum(Attendance.active_seconds), 0)).filter(
        Attendance.day >= start, Attendance.day <= end)
    if user_ids is not None:
        q = q.filter(Attendance.user_id.in_(user_ids or {-1}))
    return round(q.scalar() / 3600, 2)


def _daily(db: Session, user_ids, start: date, end: date) -> list:
    q = db.query(Attendance.day, func.sum(Attendance.active_seconds)).filter(
        Attendance.day >= start, Attendance.day <= end)
    if user_ids is not None:
        q = q.filter(Attendance.user_id.in_(user_ids or {-1}))
    got = dict(q.group_by(Attendance.day).all())
    out, d = [], start
    while d <= end:
        out.append({"day": d, "hours": round((got.get(d) or 0) / 3600, 2)})
        d += timedelta(days=1)
    return out


def _live(db: Session, user_ids=None) -> dict:
    now = utcnow()
    q = db.query(WorkSession).filter(WorkSession.state != "ended")
    if user_ids is not None:
        q = q.filter(WorkSession.user_id.in_(user_ids or {-1}))
    states = [live_state(s, now) for s in q]
    return {"working": states.count("working"), "idle": states.count("idle") + states.count("paused")}


def _range(start: date | None, end: date | None):
    today = local_day(utcnow())
    end = end or today
    start = start or end - timedelta(days=13)
    if start > end:
        start = end
    if (end - start).days > 366:
        start = end - timedelta(days=366)
    return start, end, today


@router.get("/admin")
def admin_dashboard(start: date | None = Query(None), end: date | None = Query(None),
                    actor: User = Depends(require_roles(P.ADMIN)), db: Session = Depends(get_db)):
    start, end, today = _range(start, end)
    users = db.query(User).filter(User.deleted_at.is_(None))
    by_role = dict(users.with_entities(User.role, func.count(User.id)).group_by(User.role).all())
    staff = users.filter(User.role != P.ADMIN)
    active = staff.filter(User.is_active.is_(True)).count()
    tasks = _task_counts(db.query(Task).filter(Task.deleted_at.is_(None)))
    return {
        "range": {"start": start, "end": end},
        "people": {"total_employees": sum(by_role.get(r, 0) for r in P.EMPLOYEE_ROLES),
                   "developers": by_role.get(P.DEVELOPER, 0), "onroll": by_role.get(P.ONROLL, 0),
                   "offroll": by_role.get(P.OFFROLL, 0), "interns": by_role.get(P.INTERN, 0),
                   "admins": by_role.get(P.ADMIN, 0), "active": active, "inactive": staff.count() - active},
        "live": _live(db),
        "tasks": tasks,
        "hours": {"range_total": _hours(db, None, start, end), "today": _hours(db, None, today, today),
                  "daily": _daily(db, None, start, end)},
        "active_recordings": db.query(ScreenRecording).filter_by(status="recording").count(),
        "projects": db.query(Project).count(),
        "teams": db.query(Team).count(),
        "review_queue": {"onroll": db.query(Submission).filter_by(stage="onroll_review").count(),
                         "admin": db.query(Submission).filter_by(stage="admin_review").count()},
        "intern_headcount": intern_headcount(db),
    }


@router.get("/developer")
def developer_dashboard(start: date | None = Query(None), end: date | None = Query(None),
                        actor: User = Depends(require_roles(P.DEVELOPER, P.ONROLL)), db: Session = Depends(get_db)):
    start, end, today = _range(start, end)
    ids = P.team_member_ids(db, actor.id)
    members = db.query(User).filter(User.id.in_(ids or {-1}), User.deleted_at.is_(None)).all()
    roles = [m.role for m in members]
    team_tasks = _task_counts(db.query(Task).filter(Task.deleted_at.is_(None), Task.assigned_to.in_(ids or {-1})))
    pending = [s for s in db.query(Submission).filter_by(stage="onroll_review") if P.can_review(db, actor, s)]
    progress = round(100 * team_tasks["completed"] / team_tasks["total"]) if team_tasks["total"] else 0
    return {
        "range": {"start": start, "end": end},
        "team": {"total": len(members), "onroll": roles.count(P.ONROLL), "offroll": roles.count(P.OFFROLL),
                 "interns": roles.count(P.INTERN), "progress_percent": progress},
        "live": _live(db, ids),
        "tasks": team_tasks,
        "pending_reviews": len(pending),
        "hours": {"range_total": _hours(db, ids, start, end), "today": _hours(db, ids, today, today),
                  "daily": _daily(db, ids, start, end)},
        "my_tasks": _task_counts(db.query(Task).filter(Task.deleted_at.is_(None), Task.assigned_to == actor.id)),
    }


@router.get("/me")
def my_dashboard(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Personal dashboard for On-Roll, Off-Roll, Intern (and a Developer's own work)."""
    today = local_day(utcnow())
    mine = db.query(Task).filter(Task.deleted_at.is_(None), Task.assigned_to == actor.id)
    counts = _task_counts(mine)
    p = get_profile(db, actor)
    period = None
    start_d, end_d = getattr(p, "contract_start", None), getattr(p, "contract_end", None)
    if start_d and end_d and end_d > start_d:
        done = min(max((today - start_d).days, 0), (end_d - start_d).days)
        period = {"start": start_d, "end": end_d, "days_left": max((end_d - today).days, 0),
                  "progress_percent": round(100 * done / (end_d - start_d).days)}
    recent = (db.query(Submission).filter_by(submitted_by=actor.id).order_by(Submission.id.desc()).limit(5).all())
    overdue = mine.filter(Task.status.in_(OPEN), Task.deadline < today).count()
    return {
        "tasks": counts, "overdue": overdue,
        "active_projects": mine.filter(Task.status.in_(OPEN + IN_REVIEW), Task.project_id.isnot(None))
                               .with_entities(Task.project_id).distinct().count(),
        "hours": {"today": _hours(db, {actor.id}, today, today),
                  "week": _hours(db, {actor.id}, today - timedelta(days=6), today),
                  "month": _hours(db, {actor.id}, today - timedelta(days=29), today),
                  "daily": _daily(db, {actor.id}, today - timedelta(days=13), today)},
        "training_period": period,
        "recent_tasks": [task_dict(db, t) for t in mine.order_by(Task.updated_at.desc()).limit(6)],
        "recent_submissions": [{"id": s.id, "task_id": s.task_id, "version_no": s.version_no,
                                "status": s.status, "submitted_at": s.submitted_at} for s in recent],
        "assigned_by_me": db.query(Task).filter(Task.deleted_at.is_(None), Task.assigned_by == actor.id).count(),
    }

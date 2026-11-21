import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.database.connection import get_db
from app.database.models import Attendance, ScreenRecording, Submission, Task, User, utcnow
from app.dependencies.auth import get_current_user
from app.services.common import local_day

router = APIRouter(prefix="/api/reports", tags=["reports"])

COLUMNS = [("employee_code", "ID"), ("full_name", "Name"), ("role", "Role"), ("days_present", "Days present"),
           ("active_hours", "Active hours"), ("extra_hours", "Continue hours"), ("total_hours", "Total hours"),
           ("full_days", "Days with full 8 h"),
           ("away_hours", "Away hours"), ("tasks_assigned", "Tasks assigned"),
           ("tasks_completed", "Tasks completed"), ("tasks_open", "Tasks open"), ("tasks_rejected", "Tasks rejected"),
           ("completion_percent", "Completion %"), ("submissions", "Submissions"), ("recordings", "Recordings"),
           ("avg_hours_per_day", "Avg hours / present day")]


def build(db: Session, actor: User, start: date, end: date) -> list[dict]:
    """Admin: everyone. Developer: own team and self. Others: only themselves."""
    q = db.query(User).filter(User.deleted_at.is_(None), User.role != P.ADMIN)
    if actor.role in P.LEADS:
        q = q.filter(User.id.in_(P.team_member_ids(db, actor.id) | {actor.id}))
    elif actor.role != P.ADMIN:
        q = q.filter(User.id == actor.id)
    users = q.order_by(User.full_name).all()
    ids = [u.id for u in users] or [-1]
    att = {r[0]: r for r in db.query(Attendance.user_id, func.count(Attendance.id),
                                     func.sum(Attendance.active_seconds),
                                     func.sum(Attendance.away_seconds + Attendance.idle_seconds))
           .filter(Attendance.user_id.in_(ids), Attendance.day >= start, Attendance.day <= end,
                   Attendance.active_seconds + Attendance.away_seconds + Attendance.idle_seconds > 0)
           .group_by(Attendance.user_id)}
    # Continue hours are counted on their own: an extra-only day must not get lost
    extra_hours = {r[0]: int(r[1] or 0) for r in db.query(Attendance.user_id, func.sum(Attendance.extra_seconds))
                   .filter(Attendance.user_id.in_(ids), Attendance.day >= start, Attendance.day <= end)
                   .group_by(Attendance.user_id).all()}
    full_days = dict(db.query(Attendance.user_id, func.count(Attendance.id))
                     .filter(Attendance.user_id.in_(ids), Attendance.day >= start, Attendance.day <= end,
                             Attendance.regular_completed_at.isnot(None))
                     .group_by(Attendance.user_id).all())
    tasks = {}
    for uid, status, n in (db.query(Task.assigned_to, Task.status, func.count(Task.id))
                           .filter(Task.assigned_to.in_(ids), Task.deleted_at.is_(None))
                           .group_by(Task.assigned_to, Task.status)):
        tasks.setdefault(uid, {})[status] = n
    subs = [(uid, local_day(at)) for uid, at in db.query(Submission.submitted_by, Submission.submitted_at)
            .filter(Submission.submitted_by.in_(ids))]
    recs = [(uid, local_day(at)) for uid, at in db.query(ScreenRecording.user_id, ScreenRecording.started_at)
            .filter(ScreenRecording.user_id.in_(ids))]
    in_range = lambda rows, uid: sum(1 for u, d in rows if u == uid and start <= d <= end)
    from app.api.users import get_profile
    out = []
    for u in users:
        a = att.get(u.id)
        t = tasks.get(u.id, {})
        total = sum(t.values())
        done = t.get("completed", 0) + t.get("archived", 0)
        hours = round((a[2] or 0) / 3600, 2) if a else 0.0
        days = a[1] if a else 0
        out.append({"user_id": u.id, "employee_code": getattr(get_profile(db, u), "employee_code", None),
                    "full_name": u.full_name, "role": u.role, "days_present": days, "active_hours": hours,
                    "extra_hours": round(extra_hours.get(u.id, 0) / 3600, 2),
                    "total_hours": round(hours + extra_hours.get(u.id, 0) / 3600, 2), "full_days": full_days.get(u.id, 0),
                    "away_hours": round((a[3] or 0) / 3600, 2) if a else 0.0,
                    "tasks_assigned": total, "tasks_completed": done, "tasks_rejected": (t.get("onroll_rejected", 0) + t.get("admin_rejected", 0)),
                    "tasks_open": total - done - (t.get("onroll_rejected", 0) + t.get("admin_rejected", 0)),
                    "completion_percent": round(100 * done / total) if total else 0,
                    "submissions": in_range(subs, u.id), "recordings": in_range(recs, u.id),
                    "avg_hours_per_day": round(hours / days, 2) if days else 0.0})
    return out


@router.get("/summary")
def summary(start: date | None = None, end: date | None = None,
            format: str = Query("json", pattern="^(json|csv|xlsx)$"),
            actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Performance, attendance and task completion per person for a date range."""
    end = end or local_day(utcnow())
    start = start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(422, "The end date cannot be before the start date")
    rows = build(db, actor, start, end)
    name = f"workcode-report-{start}-to-{end}"
    if format == "json":
        return {"start": start, "end": end, "rows": rows}
    table = [[label for _, label in COLUMNS]] + [[r[key] for key, _ in COLUMNS] for r in rows]
    if format == "csv":
        buf = io.StringIO()
        csv.writer(buf).writerows(table)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    for row in table:
        ws.append(row)
    for i, (_, label) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(12, len(label) + 2)
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})

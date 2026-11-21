"""Meeting timer (build 27): time spent in scheduled external meetings (Google Meet, Zoom, Teams ...).

Completely separate from the work timer: this module does not import app.services.timer and never touches
work_sessions / attendance / timer_events. Both timers simply run next to each other.

How a stay starts and ends
  automatic  the browser extension sees the page of a scheduled meeting open in a tab -> join; tab closed -> leave
  fallback   "Join" in WORKCODE starts it, "Leave meeting" ends it (used when the extension is not installed, or the
             meeting runs in a desktop program the browser cannot see)
A stay that stops reporting is closed at its last report, so a crashed browser never counts for hours.
"""
import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.timer_admin import extension_user
from app.core import permissions as P
from app.database.connection import get_db
from app.database.models import Attendance, Meeting, MeetingAttendance, MeetingParticipant, User, utcnow
from app.dependencies.auth import get_current_user
from app.schemas import ExtensionMeetings
from app.services.common import commit, local_day

router = APIRouter(prefix="/api", tags=["meeting timer"])

OPEN_BEFORE = timedelta(minutes=15)      # a meeting can be joined from 15 minutes before its start ...
OPEN_AFTER = timedelta(hours=3)          # ... until 3 hours after its planned end (meetings run over)
SILENCE = timedelta(seconds=150)         # no report for this long = the stay ended at the last report
MANUAL_LIMIT = timedelta(hours=1)        # a stay started with the Join button ends at the latest 1 hour after the planned end


def planned_end(m: Meeting):
    return m.starts_at + timedelta(minutes=m.duration_minutes)


def is_open(m: Meeting, now) -> bool:
    return m.cancelled_at is None and m.starts_at - OPEN_BEFORE <= now <= planned_end(m) + OPEN_AFTER


def invited(db: Session, m: Meeting, user_id: int) -> bool:
    return m.created_by == user_id or db.query(MeetingParticipant.id).filter_by(meeting_id=m.id, user_id=user_id).first() is not None


def close(row: MeetingAttendance, at, reason: str):
    row.left_at = max(at, row.joined_at)
    row.end_reason = reason


def sweep(db: Session, now, user_id: int | None = None) -> bool:
    """Close stays that stopped reporting, were started by hand and ran past the limit, or whose meeting was cancelled."""
    q = db.query(MeetingAttendance).filter(MeetingAttendance.left_at.is_(None))
    if user_id is not None:
        q = q.filter(MeetingAttendance.user_id == user_id)
    changed = False
    for row in q.all():
        m = db.get(Meeting, row.meeting_id)
        if m.cancelled_at is not None:
            close(row, min(now, max(m.cancelled_at, row.joined_at)), "cancelled")
        elif now - row.last_seen_at > SILENCE:
            close(row, row.last_seen_at, "no_signal")
        elif row.source == "manual" and now > planned_end(m) + MANUAL_LIMIT:
            close(row, max(planned_end(m) + MANUAL_LIMIT, row.joined_at), "limit")
        else:
            continue
        changed = True
    if changed:
        db.flush()            # this session does not flush by itself: later queries must see the closed rows
    return changed


def current_row(db: Session, user_id: int) -> MeetingAttendance | None:
    return db.query(MeetingAttendance).filter(MeetingAttendance.user_id == user_id, MeetingAttendance.left_at.is_(None)) \
        .order_by(MeetingAttendance.id.desc()).first()


def enter(db: Session, user_id: int, m: Meeting, source: str, now) -> MeetingAttendance:
    """Start a stay (or keep the running one). A person is in one meeting at a time."""
    row = current_row(db, user_id)
    if row and row.meeting_id == m.id:
        row.last_seen_at = now
        if source == "extension":
            row.source = "extension"      # from now on the browser extension ends it when the tab closes
        return row
    if row:
        close(row, now, "switched")
    row = MeetingAttendance(meeting_id=m.id, user_id=user_id, joined_at=now, last_seen_at=now, source=source)
    db.add(row)
    db.flush()
    return row


def seconds_of(row: MeetingAttendance, now) -> int:
    """Length of a stay. An open stay is still running, so it counts up to `now` — but only while the
    extension keeps reporting it. A tab that was killed, slept or refreshed stops reporting without ever
    saying "left": counting that one up to now would grow with every hour the person is away and would be
    trimmed later by sweep() anyway, so it is capped at the last signal here, in one place, and every
    reader (the report, the employee's own attendance row, the meeting list) shows the same honest number."""
    end = row.left_at
    if end is None:
        last = row.last_seen_at or row.joined_at
        end = last if now - last > SILENCE else now
    return max(0, int((end - row.joined_at).total_seconds()))


def stay_dict(db: Session, row: MeetingAttendance, now, titles: dict | None = None) -> dict:
    title = (titles or {}).get(row.meeting_id) or db.get(Meeting, row.meeting_id).title
    return {"id": row.id, "meeting_id": row.meeting_id, "title": title, "joined_at": row.joined_at, "left_at": row.left_at,
            "seconds": seconds_of(row, now), "source": row.source, "end_reason": row.end_reason}


def seconds_between(db: Session, user_id: int, now, start: date, end: date) -> int:
    """Meeting time of one person between two local days, inclusive. An open stay counts up to `now`:
    the meeting is still happening, so the clock is legitimately running."""
    rows = db.query(MeetingAttendance).filter(MeetingAttendance.user_id == user_id,
                                              MeetingAttendance.joined_at >= now - timedelta(days=40)).all()
    return sum(seconds_of(r, now) for r in rows if start <= local_day(r.joined_at) <= end)


def today_seconds(db: Session, user_id: int, now) -> int:
    day = local_day(now)
    return seconds_between(db, user_id, now, day, day)


def durations(db: Session, user_id: int, now) -> dict:
    """Daily, weekly (Monday to Sunday) and monthly meeting duration of one person."""
    today = local_day(now)
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {"today_seconds": seconds_between(db, user_id, now, today, today),
            "week_seconds": seconds_between(db, user_id, now, monday, monday + timedelta(days=6)),
            "month_seconds": seconds_between(db, user_id, now, month_start,
                                              (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1))}


def state(db: Session, user_id: int, now) -> dict:
    row = current_row(db, user_id)
    return {"current": stay_dict(db, row, now) if row else None, "server_time": now, **durations(db, user_id, now)}


# ---- the person's own controls -------------------------------------------------------------
@router.post("/meetings/{meeting_id}/join")
def join(meeting_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = utcnow()
    m = db.get(Meeting, meeting_id)
    if not m or not invited(db, m, user.id):
        raise HTTPException(404, "Meeting not found")
    if m.cancelled_at is not None:
        raise HTTPException(409, "This meeting was cancelled")
    if not is_open(m, now):
        raise HTTPException(409, "The meeting timer can start from 15 minutes before the meeting until 3 hours after its planned end")
    sweep(db, now, user.id)
    enter(db, user.id, m, "manual", now)
    commit(db)
    return state(db, user.id, now)


@router.post("/meetings/{meeting_id}/leave")
def leave(meeting_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = utcnow()
    sweep(db, now, user.id)
    row = current_row(db, user.id)
    if row and row.meeting_id == meeting_id:
        close(row, now, "left")
    commit(db)
    return state(db, user.id, now)


@router.post("/meetings/timer/ping")
def ping(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sent by the open WORKCODE page every 30 seconds: keeps a stay started with the Join button alive and returns
    the meeting timer. A stay tracked by the extension is kept alive only by the extension."""
    now = utcnow()
    changed = sweep(db, now, user.id)
    row = current_row(db, user.id)
    if row and row.source == "manual":
        row.last_seen_at = now
        changed = True
    if changed:
        commit(db)
    return state(db, user.id, now)


# ---- browser extension ---------------------------------------------------------------------
def watch_list(db: Session, user_id: int, now) -> list[Meeting]:
    mine = db.query(MeetingParticipant.meeting_id).filter_by(user_id=user_id)
    rows = db.query(Meeting).filter(Meeting.cancelled_at.is_(None), Meeting.link.isnot(None),
                                    (Meeting.created_by == user_id) | (Meeting.id.in_(mine)),
                                    Meeting.starts_at <= now + OPEN_BEFORE, Meeting.starts_at >= now - timedelta(hours=14)).all()
    return [m for m in rows if m.link and is_open(m, now)]


@router.get("/extension/meetings")
def extension_meetings(user: User = Depends(extension_user), db: Session = Depends(get_db)):
    """Scheduled meetings of this person that are open now. The extension compares their links with the open tabs
    inside the browser and reports back only the ids: no address of any tab is sent to the server."""
    now = utcnow()
    return {"meetings": [{"id": m.id, "link": m.link} for m in watch_list(db, user.id, now)], "refresh_seconds": 60}


@router.post("/extension/meetings")
def extension_meetings_report(body: ExtensionMeetings, user: User = Depends(extension_user), db: Session = Depends(get_db)):
    now = utcnow()
    sweep(db, now, user.id)
    allowed = {m.id: m for m in watch_list(db, user.id, now)}
    seen = [i for i in body.open_ids if i in allowed]          # the server checks every id: only own, open meetings count
    row = current_row(db, user.id)
    if row and row.meeting_id in seen:
        enter(db, user.id, allowed[row.meeting_id], "extension", now)
    elif seen:
        soonest = min(seen, key=lambda i: abs((allowed[i].starts_at - now).total_seconds()))
        enter(db, user.id, allowed[soonest], "extension", now)
    elif row and row.source == "extension":
        close(row, now, "tab_closed")
    commit(db)
    row = current_row(db, user.id)
    return {"in_meeting": row.meeting_id if row else None}


# ---- report --------------------------------------------------------------------------------
@router.get("/meetings/timer/report")
def report(start: date | None = None, end: date | None = None, user_id: int | None = None,
           format: str = Query("json", pattern="^(json|csv)$"),
           actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Work timer and meeting timer next to each other, per person, with every join / leave.
    Admin: everyone. On-Roll team lead: own team. Others: themselves."""
    now = utcnow()
    today = local_day(now)
    end = end or today
    start = min(start or end, end)
    if sweep(db, now):
        db.commit()
    q = db.query(User).filter(User.deleted_at.is_(None))
    if actor.role != P.ADMIN:
        ids = {actor.id}
        if actor.role in (P.DEVELOPER, P.ONROLL):
            ids |= set(P.team_member_ids(db, actor.id) or [])
        q = q.filter(User.id.in_(ids))
    if user_id is not None:
        q = q.filter(User.id == user_id)
    users = q.order_by(User.full_name).all()
    ids = [u.id for u in users] or [-1]
    work = dict(db.query(Attendance.user_id, func.sum(Attendance.active_seconds))
                .filter(Attendance.user_id.in_(ids), Attendance.day >= start, Attendance.day <= end).group_by(Attendance.user_id).all())
    stays = db.query(MeetingAttendance).filter(MeetingAttendance.user_id.in_(ids)).order_by(MeetingAttendance.joined_at).all()
    stays = [s for s in stays if start <= local_day(s.joined_at) <= end]
    titles = dict(db.query(Meeting.id, Meeting.title).filter(Meeting.id.in_({s.meeting_id for s in stays} or {-1})).all())
    rows = []
    for u in users:
        mine = [s for s in stays if s.user_id == u.id]
        live = next((s for s in mine if s.left_at is None), None) or current_row(db, u.id)
        rows.append({"user_id": u.id, "full_name": u.full_name, "role": u.role,
                     "work_seconds": int(work.get(u.id) or 0),
                     "meeting_seconds": sum(seconds_of(s, now) for s in mine),
                     "meetings": len({s.meeting_id for s in mine}), "joins": len(mine),
                     "in_meeting": stay_dict(db, live, now) if live else None,
                     "stays": [stay_dict(db, s, now, titles) for s in mine]})
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["User", "Role", "Meeting", "Joined", "Left", "Status", "Duration (s)",
                    "Meeting time in range (s)", "Meetings", "Joins", "Detected by", "Ended because"])
        for r in rows:
            if not r["stays"]:
                w.writerow([r["full_name"], r["role"], "", "", "", "no meeting in this range",
                            "", r["meeting_seconds"], 0, 0, "", ""])
                continue
            for i, s_ in enumerate(r["stays"]):
                status = "in the meeting" if s_["left_at"] is None else "left"
                w.writerow([r["full_name"], r["role"], s_["title"],
                            s_["joined_at"].isoformat(timespec="seconds"),
                            s_["left_at"].isoformat(timespec="seconds") if s_["left_at"] else "",
                            status, s_["seconds"], r["meeting_seconds"] if i == 0 else "",
                            r["meetings"] if i == 0 else "", r["joins"] if i == 0 else "",
                            s_["source"], s_["end_reason"] or ""])
        w.writerow(["TOTAL", "", "", "", "", f"{len(rows)} people",
                    sum(r["meeting_seconds"] for r in rows), sum(r["meeting_seconds"] for r in rows),
                    sum(r["meetings"] for r in rows), sum(r["joins"] for r in rows), "", ""])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="workcode-meetings-{start}-to-{end}.csv"'})
    return {"start": start, "end": end, "server_time": now, "rows": rows}

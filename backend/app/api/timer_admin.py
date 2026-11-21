"""Automatic timer: website allowlist, browser-extension endpoints, timer reports and history."""
import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.config import settings
from app.core.security import create_access_token
from app.database.connection import get_db
from app.database.models import (AllowedSite, Attendance, MeetingAttendance, ScreenRecording, TimerEvent, User,
                                WorkSession, utcnow)
from app.dependencies.auth import client_ip, get_current_user, user_from_token
from app.schemas import AllowedSiteIn, ExtensionReport
from app.services import timer
from app.services.common import TZ, audit, commit, local_day

router = APIRouter(prefix="/api", tags=["automatic timer"])
HOST_RE = re.compile(r"^(?=.{3,120}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def normalise_domain(value: str) -> str:
    """Accepts "https://Meet.Google.com/abc" or "meet.google.com" -> "meet.google.com"."""
    v = value.strip().lower()
    host = urlparse(v if "://" in v else f"//{v}").hostname or ""
    if not HOST_RE.match(host):
        raise HTTPException(422, "Enter a website domain such as meet.google.com")
    return host


def matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def workcode_hosts() -> list[str]:
    return sorted({urlparse(o).hostname for o in settings.cors_list if urlparse(o).hostname})


def site_dict(a: AllowedSite) -> dict:
    return {"id": a.id, "domain": a.domain, "label": a.label, "ignore_inactivity": a.ignore_inactivity}


# ---- allowlist ---------------------------------------------------------------------------
@router.get("/timer/allowlist")
def list_sites(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [site_dict(a) for a in db.query(AllowedSite).order_by(AllowedSite.domain)]


@router.post("/timer/allowlist", status_code=201)
def add_site(body: AllowedSiteIn, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != P.ADMIN:
        raise HTTPException(403, "Only admins can change the approved websites")
    domain = normalise_domain(body.domain)
    if db.query(AllowedSite).filter_by(domain=domain).first():
        raise HTTPException(409, "This website is already approved")
    a = AllowedSite(domain=domain, label=(body.label or "").strip() or None, ignore_inactivity=body.ignore_inactivity,
                    created_by=actor.id)
    db.add(a)
    db.flush()
    audit(db, actor, "timer.allowlist.add", "website_allowlist", a.id, new=site_dict(a), ip=client_ip(request))
    commit(db)
    return site_dict(a)


@router.delete("/timer/allowlist/{site_id}")
def remove_site(site_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role != P.ADMIN:
        raise HTTPException(403, "Only admins can change the approved websites")
    a = db.get(AllowedSite, site_id)
    if not a:
        raise HTTPException(404, "Not found")
    audit(db, actor, "timer.allowlist.remove", "website_allowlist", a.id, previous=site_dict(a), ip=client_ip(request))
    db.delete(a)      # configuration row, not an employee record; the removal is kept in the audit log
    commit(db)
    return {"ok": True}


# ---- browser extension -------------------------------------------------------------------
def extension_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    user = user_from_token(db, token, scope="extension")
    if not user:
        raise HTTPException(401, "Extension is not signed in")
    return user


@router.post("/extension/token")
def extension_token(actor: User = Depends(get_current_user)):
    """A token that only works on /api/extension/*. The WORKCODE page hands it to the extension."""
    return {"token": create_access_token(actor.id, actor.role, scope="extension", minutes=settings.EXTENSION_TOKEN_MINUTES),
            "expires_in_minutes": settings.EXTENSION_TOKEN_MINUTES}


@router.get("/extension/config")
def extension_config(user: User = Depends(extension_user), db: Session = Depends(get_db)):
    return {"workcode_hosts": workcode_hosts(), "report_seconds": 30,
            "inactivity_seconds": settings.INACTIVITY_TIMEOUT_SECONDS,
            "approved": [{"domain": a.domain, "ignore_inactivity": a.ignore_inactivity} for a in db.query(AllowedSite)]}


@router.post("/extension/report")
def extension_report(body: ExtensionReport, user: User = Depends(extension_user), db: Session = Depends(get_db)):
    """The extension says what kind of site is in front. The server re-checks an "approved" claim against the
    allowlist and never stores the address of any other site."""
    s = timer.current(db, user.id)
    if not s:
        return {"session": None, "mode": timer.STOPPED}
    category, domain, idle = body.category, None, body.idle != "active"
    if category == "approved":
        host = (body.domain or "").strip().lower()
        site = next((a for a in db.query(AllowedSite) if matches(host, a.domain)), None)
        if site is None:
            category = "unapproved"            # not on the list (any more): treated as unapproved
        else:
            domain = site.domain
            if site.ignore_inactivity and body.idle == "idle":
                idle = False                   # e.g. listening in a meeting; a locked screen still pauses
    timer.extension_report(db, s, category, domain, idle)
    commit(db)
    return {"session": s.id, "mode": s.mode}


# ---- reports and history -----------------------------------------------------------------
# ---- build 32: interval maths so overlapping timers are never counted twice -----------------
def _span(a: datetime, b: datetime) -> int:
    """Whole seconds between two moments, never negative."""
    return max(0, int((b - a).total_seconds()))


def _merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Sort (start, end) pairs and join the ones that touch or overlap."""
    out: list[list] = []
    for a, b in sorted((s, e) for s, e in spans if e > s):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _union_seconds(spans) -> int:
    """Time counted once, however many rows cover it."""
    return sum(_span(a, b) for a, b in _merge(spans))


def _overlap_seconds(a_spans, b_spans) -> int:
    """Seconds the two interval lists have in common."""
    A, B = _merge(a_spans), _merge(b_spans)
    i = j = total = 0
    while i < len(A) and j < len(B):
        lo, hi = max(A[i][0], B[j][0]), min(A[i][1], B[j][1])
        if hi > lo:
            total += _span(lo, hi)
        if A[i][1] <= B[j][1]:
            i += 1
        else:
            j += 1
    return total


def _day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """The range as UTC datetimes, using the same local-day rule as the attendance rows.
    Aware like every other datetime in the app (UTCDateTime always carries tzinfo=UTC)."""
    lo = datetime.combine(start, time.min, tzinfo=TZ).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=TZ).astimezone(timezone.utc)
    return lo, hi


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    today = local_day(utcnow())
    end = end or today
    start = start or end
    return (min(start, end), end)


def _scope(db: Session, actor: User):
    q = db.query(User).filter(User.deleted_at.is_(None))
    if actor.role == P.ADMIN:
        return q
    if actor.role in P.LEADS:
        return q.filter(User.id.in_(P.team_member_ids(db, actor.id) | {actor.id}))
    return q.filter(User.id == actor.id)


COLUMNS = [("full_name", "Name"), ("role", "Role"), ("state", "Current state"), ("today_active_seconds", "Today working (s)"),
           ("active_seconds", "Active (s)"), ("paused_seconds", "Paused total (s)"), ("inactive_seconds", "Inactive (s)"),
           ("external_seconds", "Unapproved / away (s)"), ("manual_seconds", "Manual pause (s)"), ("days_present", "Days"),
           ("category", "Activity category"), ("last_activity_at", "Last activity"), ("session_start", "Session start"),
           ("session_end", "Last session end"), ("recording", "Recording now"), ("extra_seconds_today", "Continue today (s)"),
           ("extra_seconds", "Extra total (s)"), ("extra_start", "Extra start"), ("extra_end", "Extra end"),
           ("meeting_seconds", "Meeting total (s)"), ("meetings", "Meetings"), ("meeting_joins", "Meeting joins"),
           ("in_meeting", "In meeting now"), ("meeting_start", "Meeting start"), ("meeting_end", "Meeting end"),
           ("meeting_work_seconds", "Meeting inside work (s)"), ("meeting_outside_seconds", "Meeting outside work (s)"),
           ("total_seconds", "Total working (s)"), ("grand_total_seconds", "Grand total (s)"),
           ("work_overlap_seconds", "Overlapping work timers (s)"),
           ("schedule_label", "Schedule"), ("regular_completed", "8 h done")]


def meeting_breakdown_by_day(db: Session, user_id: int, now, start: date, end: date) -> dict:
    """Meeting time, meetings and joins per local day for one person, straight from meeting_attendance.

    Build 34: the employee's own daily attendance table needs the same numbers the admin report shows.
    Counting rule is identical to /timer/overview (both use seconds_of): an open stay runs up to `now` while
    the extension still reports it, or up to its last signal when the reporting stopped; a stay belongs to
    the day it started. Nothing is written and nothing is created here."""
    from app.api import meeting_timer as mt            # local import: meeting_timer imports this module
    lo, hi = _day_bounds(start, end)
    rows = (db.query(MeetingAttendance).filter(MeetingAttendance.user_id == user_id,
            MeetingAttendance.joined_at >= lo, MeetingAttendance.joined_at < hi).all())
    out: dict = {}
    for r in rows:
        slot = out.setdefault(local_day(r.joined_at), {"seconds": 0, "ids": set(), "joins": 0})
        slot["seconds"] += mt.seconds_of(r, now)
        slot["ids"].add(r.meeting_id)
        slot["joins"] += 1
    return {d: {"meeting_seconds": v["seconds"], "meetings": len(v["ids"]), "meeting_joins": v["joins"]}
            for d, v in out.items()}


@router.get("/timer/overview")
def overview(start: date | None = None, end: date | None = None, role: str | None = None,
             format: str = Query("json", pattern="^(json|csv)$"),
             actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Timer state and totals per person. Admin: everyone. Developer: own team. Others: themselves."""
    start, end = _range(start, end)
    now = utcnow()
    if timer.expire_stale(db, now):
        db.commit()
    q = _scope(db, actor)
    if role:
        q = q.filter(User.role == role)
    users = q.order_by(User.full_name).all()
    ids = [u.id for u in users] or [-1]
    today = local_day(now)
    sums = {r[0]: r for r in db.query(Attendance.user_id, func.sum(Attendance.active_seconds), func.sum(Attendance.idle_seconds),
                                      func.sum(Attendance.away_seconds), func.sum(Attendance.paused_seconds), func.count(Attendance.id),
                                      func.sum(Attendance.extra_seconds))
            .filter(Attendance.user_id.in_(ids), Attendance.day >= start, Attendance.day <= end).group_by(Attendance.user_id)}
    todays = {r[0]: r for r in db.query(Attendance.user_id, Attendance.active_seconds, Attendance.extra_seconds,
                                        Attendance.regular_completed_at)
              .filter(Attendance.user_id.in_(ids), Attendance.day == today).all()}
    live = {s.user_id: s for s in db.query(WorkSession).filter(WorkSession.user_id.in_(ids), WorkSession.state != "ended")}
    # A recording row only proves the browser is still sending chunks. A tab that was killed, refreshed or
    # lost by a crash keeps its "recording" status until the owner opens their own recordings list (that is
    # the only place stale rows are repaired), so the report must not read the status alone — otherwise the
    # red dot would claim somebody is being recorded while nothing is being recorded. The window is the same
    # STALE_SECONDS the recordings module uses, so the two screens can never disagree.
    from app.api.recordings import STALE_SECONDS      # inside the function: no import cycle at module load
    rec_users = {r.user_id for r in db.query(ScreenRecording).filter(
        ScreenRecording.status == "recording", ScreenRecording.user_id.in_(ids),
        ScreenRecording.updated_at >= now - timedelta(seconds=STALE_SECONDS))}
    open_extra = {s.user_id for s in live.values() if s.schedule == timer.EXTRA}
    # most recent extra-schedule session of the last day per person (for the start / end columns)
    extra_last = {}
    for xs in (db.query(WorkSession).filter(WorkSession.user_id.in_(ids), WorkSession.schedule == timer.EXTRA,
                                            WorkSession.started_at >= now - timedelta(days=1))
               .order_by(WorkSession.id.desc()).all()):
        extra_last.setdefault(xs.user_id, xs)

    # ---- build 32: meeting time, read from the meeting timer's own tables (no second meeting timer) ----
    from app.api import meeting_timer as mt            # inside the function: meeting_timer imports this module
    if mt.sweep(db, now):
        db.commit()                                    # stays that stopped reporting are closed at their last report
    lo, hi = _day_bounds(start, end)
    meets = {}
    for r in (db.query(MeetingAttendance).filter(MeetingAttendance.user_id.in_(ids),
                                                 MeetingAttendance.joined_at >= lo, MeetingAttendance.joined_at < hi)
              .order_by(MeetingAttendance.joined_at).all()):
        m = meets.setdefault(r.user_id, {"secs": 0, "spans": [], "meetings": set(), "joins": 0,
                                         "start": None, "end": None, "open": None})
        m["secs"] += mt.seconds_of(r, now)
        m["spans"].append((r.joined_at, max(r.left_at or now, r.joined_at)))
        m["meetings"].add(r.meeting_id)
        m["joins"] += 1
        if m["start"] is None:
            m["start"] = r.joined_at
        if r.left_at is None:
            m["open"] = r
        elif m["end"] is None or r.left_at > m["end"]:
            m["end"] = r.left_at
    # the work sessions that touch the range, clipped to it: this is what "inside working time" means
    work_spans = {}
    for ws in (db.query(WorkSession).filter(WorkSession.user_id.in_(ids), WorkSession.started_at < hi,
                                            or_(WorkSession.ended_at.is_(None), WorkSession.ended_at >= lo)).all()):
        a, b = max(ws.started_at, lo), min(ws.ended_at or now, hi)
        if b > a:
            work_spans.setdefault(ws.user_id, []).append((a, b))
    rows = []
    for u in users:
        s, a = live.get(u.id), sums.get(u.id)
        last = timer.last_ended(db, u.id)
        if s:
            silent = (now - s.last_heartbeat_at).total_seconds() > settings.HEARTBEAT_MAX_GAP_SECONDS * 2
            state = "NO_SIGNAL" if silent else s.mode
        else:
            state = timer.EXPIRED if last and last.end_reason == "stale" else timer.STOPPED
        idle, ext, manual = (int(a[2] or 0), int(a[3] or 0), int(a[4] or 0)) if a else (0, 0, 0)
        t = todays.get(u.id)
        done = bool(t and t[3]) or timer.regular_done(db, u.id, now)
        xl = extra_last.get(u.id)
        rows.append({"user_id": u.id, "full_name": u.full_name, "role": u.role, "state": state,
                     "pause_reason": timer.pause_reason(db, s) if s else None,
                     "category": timer.category_of(s, now) if s and state != "NO_SIGNAL" else None,
                     "extension_connected": bool(s and timer.ext_fresh(s, now)),
                     "today_active_seconds": int(t[1]) if t else 0,
                     "schedule": "continue" if u.id in open_extra else ("regular" if s else None),
                     "schedule_label": "Extra" if u.id in open_extra else ("Completed" if done else "Regular"),
                     "recording": "recording" if u.id in rec_users else None,
                     "extra_seconds_today": int(t[2]) if t else 0,
                     "extra_seconds": int(a[6] or 0) if a else 0,
                     "extra_start": xl.started_at if xl else None,
                     "extra_end": None if u.id in open_extra else (xl.ended_at if xl else None),
                     "extra_running": u.id in open_extra,
                     "regular_completed": done,
                     "regular_completed_at": t[3] if t else None,
                     "schedule_target_seconds": timer.target_seconds(),
                     "session_schedule": s.schedule if s else None,
                     "active_seconds": int(a[1] or 0) if a else 0, "inactive_seconds": idle, "external_seconds": ext,
                     "manual_seconds": manual, "paused_seconds": idle + ext + manual, "days_present": int(a[5]) if a else 0,
                     "inactive_for_seconds": int((now - s.last_activity_at).total_seconds()) if s and s.last_activity_at and s.mode != timer.RUNNING else 0,
                     "last_activity_at": s.last_activity_at if s else (last.last_activity_at if last else None),
                     "session_start": s.started_at if s else None, "session_end": last.ended_at if last else None})
        row = rows[-1]
        m = meets.get(u.id)
        spans = work_spans.get(u.id, [])
        # meeting time is a breakdown of the working day, never an addition to it: the total is the two work
        # schedules only, because every credited second lands in exactly one of their two buckets
        inside = _overlap_seconds(m["spans"], spans) if m else 0
        row["meeting_seconds"] = m["secs"] if m else 0
        row["meetings"] = len(m["meetings"]) if m else 0
        row["meeting_joins"] = m["joins"] if m else 0
        row["meeting_start"] = m["start"] if m else None
        row["meeting_end"] = m["end"] if m else None
        row["in_meeting"] = bool(m and m["open"])
        row["meeting_work_seconds"] = inside
        row["meeting_outside_seconds"] = (m["secs"] if m else 0) - inside
        row["total_seconds"] = row["active_seconds"] + row["extra_seconds"]
        # Build 33: the Grand Total deliberately counts meeting time again, also when it ran inside a work
        # session. total_seconds above stays the non-duplicated figure used for attendance analysis.
        row["grand_total_seconds"] = row["total_seconds"] + row["meeting_seconds"]
        # more than zero means two work sessions of this person covered the same minute (they should not)
        row["work_overlap_seconds"] = sum(_span(a, b) for a, b in spans) - _union_seconds(spans)

    def _sum(key):
        return sum(int(r[key] or 0) for r in rows)

    totals = {"people": len(rows), "regular_seconds": _sum("active_seconds"), "extra_seconds": _sum("extra_seconds"),
              "meeting_seconds": _sum("meeting_seconds"), "meeting_work_seconds": _sum("meeting_work_seconds"),
              "meeting_outside_seconds": _sum("meeting_outside_seconds"),
              "active_seconds": _sum("active_seconds") + _sum("extra_seconds"), "paused_seconds": _sum("paused_seconds"),
              "inactive_seconds": _sum("inactive_seconds"), "total_seconds": _sum("total_seconds"),
              "grand_total_seconds": _sum("grand_total_seconds"), "work_overlap_seconds": _sum("work_overlap_seconds"),
              "meetings": _sum("meetings"), "meeting_joins": _sum("meeting_joins")}
    if format == "json":
        return {"start": start, "end": end, "rows": rows, "totals": totals}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in COLUMNS])

    def _line(d):
        return [d[k].isoformat() if hasattr((d.get(k) or ""), "isoformat") else ("" if d.get(k) is None else d.get(k))
                for k, _ in COLUMNS]

    for r in rows:
        w.writerow(_line(r))
    # the same totals the screen shows, with the date range it was calculated for
    w.writerow(_line({"full_name": "RANGE TOTALS", "role": f"{totals['people']} people",
                      "active_seconds": totals["regular_seconds"], "paused_seconds": totals["paused_seconds"],
                      "inactive_seconds": totals["inactive_seconds"], "extra_seconds": totals["extra_seconds"],
                      "extra_seconds_today": "", "meeting_seconds": totals["meeting_seconds"],
                      "meetings": "", "meeting_joins": "", "in_meeting": "",
                      "meeting_start": start.isoformat(), "meeting_end": end.isoformat(),
                      "meeting_work_seconds": totals["meeting_work_seconds"],
                      "meeting_outside_seconds": totals["meeting_outside_seconds"],
                      "total_seconds": totals["total_seconds"], "grand_total_seconds": totals["grand_total_seconds"],
                      "schedule_label": f"{start} to {end}"}))
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="workcode-timer-{start}-to-{end}.csv"'})


@router.get("/timer/sessions")
def sessions(user_id: int | None = None, start: date | None = None, end: date | None = None,
             actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sessions with their full pause / resume history. Own sessions, or someone you are allowed to view."""
    target = user_id or actor.id
    if not P.can_view_user(db, actor, target):
        raise HTTPException(403, "You cannot view this person's timer")
    start, end = _range(start, end)
    rows = (db.query(WorkSession).filter(WorkSession.user_id == target).order_by(WorkSession.id.desc()).limit(400).all())
    rows = [s for s in rows if start <= local_day(s.started_at) <= end]
    events = {}
    for e in db.query(TimerEvent).filter(TimerEvent.session_id.in_([s.id for s in rows] or [-1])).order_by(TimerEvent.id):
        events.setdefault(e.session_id, []).append({"at": e.at, "from": e.from_state, "to": e.to_state, "reason": e.reason,
                                                    "category": e.category})
    return [{"id": s.id, "started_at": s.started_at, "ended_at": s.ended_at, "state": s.mode, "end_reason": s.end_reason,
             "active_seconds": s.active_seconds, "inactive_seconds": s.idle_seconds, "external_seconds": s.away_seconds,
             "manual_seconds": s.paused_seconds, "paused_seconds": s.idle_seconds + s.away_seconds + s.paused_seconds,
             "events": events.get(s.id, [])} for s in rows]

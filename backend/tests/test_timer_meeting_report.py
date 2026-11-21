"""Build 32: the meeting timer inside the automatic timer report.

The numbers are planted directly in the database (work sessions, attendance, meeting stays) and the clock is
frozen at 18:00 local, so a whole working day always fits inside "today" and every duration is exact.
"""
from datetime import date, datetime, time, timedelta, timezone

from app.api import meeting_timer as mt
from app.api import sessions as sa
from app.api import timer_admin as ta
from app.database.connection import SessionLocal
from app.database.models import Meeting, MeetingAttendance
from tests.conftest import org  # noqa: F401

A = "tab-aaaaaaaa"


def _db():
    return SessionLocal()


def _now():
    """18:00 Asia/Kolkata (= 12:30 UTC), so the whole local day is behind it."""
    day = date.today()
    return datetime.combine(day, time(12, 30), tzinfo=timezone.utc)


def _at(day, hh, mm=0):
    """A moment on that local day, expressed in the UTC the columns store."""
    return datetime.combine(day, time(hh, mm), tzinfo=timezone.utc) - timedelta(hours=5, minutes=30)


def _freeze(monkeypatch):
    """Stop the clock for every module that reads it: the report, the meeting timer and the employee's own
    attendance endpoint — otherwise the open stays in a test are measured against the real wall clock."""
    now = _now()
    monkeypatch.setattr(ta, "utcnow", lambda: now)
    monkeypatch.setattr(mt, "utcnow", lambda: now)
    monkeypatch.setattr(sa, "utcnow", lambda: now)
    return now


def _plant(user_id, *, active=0, extra=0, done_at=None, away=0, idle=0, paused=0, day=None):
    """One attendance row for the day, exactly the way the timer would have left it."""
    db = _db()
    from app.database.models import Attendance
    from app.services.common import local_day
    day = day or local_day(_now())
    row = db.query(Attendance).filter_by(user_id=user_id, day=day).first()
    if row is None:
        row = Attendance(user_id=user_id, day=day, active_seconds=0, away_seconds=0, idle_seconds=0,
                         paused_seconds=0, extra_seconds=0, status="present")
        db.add(row)
    row.active_seconds = active
    row.extra_seconds = extra
    row.away_seconds = away
    row.idle_seconds = idle
    row.paused_seconds = paused
    row.regular_completed_at = done_at
    db.commit()
    db.close()


def _work_session(user_id, day, start_h, end_h=None, schedule="regular", active=0, mode="RUNNING"):
    """A work session spanning the given local hours; end_h=None keeps it open."""
    db = _db()
    from app.database.models import WorkSession
    now = _now()
    s = WorkSession(user_id=user_id, started_at=_at(day, *start_h), last_heartbeat_at=now,
                    state="running" if end_h is None else "ended", client_state="active", client_id=f"seed-{user_id}",
                    active_seconds=active, mode=mode if end_h is None else "STOPPED", schedule=schedule,
                    last_activity_at=now, end_reason=None if end_h is None else "manual",
                    ended_at=None if end_h is None else _at(day, *end_h))
    db.add(s)
    db.commit()
    sid = s.id
    db.close()
    return sid


def _meeting(day, start_h, minutes=60, title="Sprint planning"):
    db = _db()
    m = Meeting(title=title, starts_at=_at(day, *start_h), duration_minutes=minutes, link="https://meet.google.com/x",
                created_by=1)
    db.add(m)
    db.commit()
    mid = m.id
    db.close()
    return mid


def _stay(user_id, meeting_id, day, start_h, end_h=None, source="manual"):
    """One meeting stay. An open stay must look freshly reported, or the sweep closes it first."""
    db = _db()
    row = MeetingAttendance(meeting_id=meeting_id, user_id=user_id, joined_at=_at(day, *start_h),
                            left_at=None if end_h is None else _at(day, *end_h),
                            last_seen_at=end_h and _at(day, *end_h) or _now(), source=source,
                            end_reason=None if end_h is None else "left")
    db.add(row)
    db.commit()
    rid = row.id
    db.close()
    return rid


def _row(actor, user_id, **params):
    rows = actor.get("/api/timer/overview", params=params).json()["rows"]
    return next(x for x in rows if x["user_id"] == user_id)


def _resp(actor, **params):
    return actor.get("/api/timer/overview", params=params).json()


def test_report_reports_meeting_time_without_adding_it_to_the_total(org, monkeypatch):
    """The example in the spec: 8 h of work that contains a 2 h Google Meet stays an 8 h day."""
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=28800)
    _work_session(u.id, day, (9, 0), (17, 0), "regular", active=28800)
    m = _meeting(day, (10, 0), minutes=120)
    _stay(u.id, m, day, (10, 0), (12, 0))

    r = _row(org.admin, u.id)
    assert r["meeting_seconds"] == 7200
    assert r["meetings"] == 1 and r["meeting_joins"] == 1
    assert r["active_seconds"] == 28800 and r["extra_seconds"] == 0
    assert r["total_seconds"] == 28800                       # never 28800 + 7200
    assert r["meeting_work_seconds"] == 7200                 # it happened inside the work session
    assert r["meeting_outside_seconds"] == 0
    assert r["in_meeting"] is False and r["meeting_start"] and r["meeting_end"]

    t = _resp(org.admin)["totals"]
    assert t["regular_seconds"] == 28800 and t["meeting_seconds"] == 7200 and t["total_seconds"] == 28800


def test_meeting_outside_a_work_session_is_not_counted_as_work(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=3600)
    _work_session(u.id, day, (9, 0), (10, 0), "regular", active=3600)
    m = _meeting(day, (11, 0), minutes=30)
    _stay(u.id, m, day, (11, 0), (11, 30))                   # the work timer was not running here

    r = _row(org.admin, u.id)
    assert r["meeting_seconds"] == 1800 and r["meeting_work_seconds"] == 0
    assert r["meeting_outside_seconds"] == 1800
    assert r["total_seconds"] == 3600                         # and not 3600 + 1800


def test_regular_extra_and_meeting_together(org, monkeypatch):
    """8 regular hours + 2 extra hours, with a meeting inside the extra time."""
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.onroll
    done = _at(day, 17, 0)
    _plant(u.id, active=28800, extra=7200, done_at=done, idle=600, away=900, paused=300)
    _work_session(u.id, day, (9, 0), (17, 0), "regular", active=28800)
    _work_session(u.id, day, (17, 0), (19, 0), "extra", active=7200)
    m = _meeting(day, (17, 30), minutes=30)
    _stay(u.id, m, day, (17, 30), (18, 0))

    r = _row(org.admin, u.id)
    assert r["active_seconds"] == 28800 and r["extra_seconds"] == 7200
    assert r["meeting_seconds"] == 1800 and r["meeting_work_seconds"] == 1800
    assert r["total_seconds"] == 36000                        # regular + extra, meeting only reported
    assert r["paused_seconds"] == 600 + 900 + 300
    # the day was completed and the extra session has ended, so the existing schedule label still reads Completed
    assert r["schedule_label"] == "Completed"

    t = _resp(org.admin)["totals"]
    assert t["regular_seconds"] == 28800 and t["extra_seconds"] == 7200 and t["total_seconds"] == 36000
    assert t["active_seconds"] == 36000 and t["meeting_seconds"] == 1800
    assert t["inactive_seconds"] == 600 and t["paused_seconds"] == 1800


def test_several_meetings_and_a_meeting_still_running(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.onroll
    _plant(u.id, active=25200)
    _work_session(u.id, day, (9, 0), None, "regular", active=25200)        # still open at 18:00
    m1 = _meeting(day, (9, 30))
    m2 = _meeting(day, (17, 30), minutes=30)
    _stay(u.id, m1, day, (9, 30), (10, 0))
    _stay(u.id, m1, day, (10, 30), (11, 0))                                 # same meeting, two stays
    _stay(u.id, m2, day, (17, 30), None, source="extension")               # left_at empty: inside it now

    r = _row(org.admin, u.id)
    assert r["meetings"] == 2 and r["meeting_joins"] == 3
    assert r["in_meeting"] is True
    assert r["meeting_seconds"] == 1800 + 1800 + 1800                       # the running one counts to now
    assert r["meeting_work_seconds"] == 5400                                 # all of it inside the open session
    # the report must not close the running stay, and must not write a row of its own
    db = _db()
    assert db.query(MeetingAttendance).filter_by(user_id=u.id, left_at=None).count() == 1
    db.close()
    assert _row(org.admin, u.id)["meeting_joins"] == 3


def test_the_report_never_writes_meeting_rows(org, monkeypatch):
    _freeze(monkeypatch)
    _plant(org.offroll.id, active=28800)
    db = _db()
    before = db.query(MeetingAttendance).count()
    db.close()
    for _ in range(3):
        org.admin.get("/api/timer/overview")
    db = _db()
    assert db.query(MeetingAttendance).count() == before
    db.close()


def test_double_open_work_sessions_are_detected_and_not_added_twice(org, monkeypatch):
    """Pathological data (two open sessions of one person): the overlap is reported, the total stays the sum
    of the two buckets, which already cannot double count."""
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=28800, extra=3600)
    _work_session(u.id, day, (9, 0), (17, 0), "regular", active=28800)
    _work_session(u.id, day, (16, 0), (17, 0), "extra", active=3600)      # overlaps the last hour

    r = _row(org.admin, u.id)
    assert r["work_overlap_seconds"] == 3600
    assert r["total_seconds"] == 32400


def test_filters_and_access_are_respected(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    for u, active in ((org.onroll, 28800), (org.offroll, 3600), (org.outsider, 7200)):
        _plant(u.id, active=active)
    m = _meeting(day, (9, 0), minutes=60)
    _stay(org.onroll.id, m, day, (9, 0), (10, 0))
    _stay(org.outsider.id, m, day, (9, 0), (10, 30))
    # and one yesterday, which must not show up in a today-only report
    y = day - timedelta(days=1)
    my = _meeting(y, (9, 0), minutes=60)
    _stay(org.onroll.id, my, y, (9, 0), (11, 0))

    today = _resp(org.admin, start=day.isoformat(), end=day.isoformat())
    r = next(x for x in today["rows"] if x["user_id"] == org.onroll.id)
    assert r["meeting_seconds"] == 3600 and today["totals"]["meeting_seconds"] == 3600 + 5400

    both = _resp(org.admin, start=y.isoformat(), end=day.isoformat())
    assert both["totals"]["meeting_seconds"] == 3600 + 5400 + 7200

    # the on-roll lead sees their own team, not the other team's intern
    seen = {x["user_id"] for x in _resp(org.dev)["rows"]}
    assert org.onroll.id in seen and org.offroll.id in seen and org.outsider.id not in seen
    lead = _resp(org.onroll)
    assert {x["user_id"] for x in lead["rows"]} == {org.onroll.id}
    assert "totals" in lead
    # an intern gets nothing extra: only themselves, and no admin-only data
    only_self = _resp(org.intern)
    assert {x["user_id"] for x in only_self["rows"]} == {org.intern.id}


def test_csv_export_carries_the_same_numbers_as_the_screen(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=28800, extra=1800, idle=600)
    _work_session(u.id, day, (9, 0), (17, 0), "regular", active=28800)
    m = _meeting(day, (13, 0), minutes=60)
    _stay(u.id, m, day, (13, 0), (14, 0))

    js = _resp(org.admin)
    csv_text = org.admin.get("/api/timer/overview", params={"format": "csv"}).text
    lines = [l for l in csv_text.splitlines() if l.strip()]
    head = lines[0].split(",")
    for label in ("Meeting total (s)", "Meetings", "Meeting inside work (s)", "Meeting outside work (s)",
                  "Total working (s)", "Overlapping work timers (s)", "Schedule"):
        assert label in head, head
    row_line = next(l for l in lines if l.startswith("Offroll One"))
    totals_line = lines[-1]
    cells = dict(zip(head, row_line.split(",")))
    tcells = dict(zip(head, totals_line.split(",")))
    row = next(x for x in js["rows"] if x["user_id"] == u.id)
    assert cells["Meeting total (s)"] == str(row["meeting_seconds"]) == "3600"
    assert cells["Total working (s)"] == str(row["total_seconds"]) == "30600"
    assert tcells["Name"] == "RANGE TOTALS"
    assert tcells["Meeting total (s)"] == str(js["totals"]["meeting_seconds"])
    assert tcells["Total working (s)"] == str(js["totals"]["total_seconds"])
    assert tcells["Schedule"] == f"{js['start']} to {js['end']}"          # the range the numbers belong to


def test_a_person_sees_their_meeting_duration_by_day_week_and_month(org, monkeypatch):
    """Wednesday 18 November 2026, so the week runs Mon 16th to Sun 22nd and the month is November."""
    fixed = datetime(2026, 11, 18, 12, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(mt, "utcnow", lambda: fixed)
    u = org.onroll
    _stay(u.id, _meeting(date(2026, 11, 18), (10, 0)), date(2026, 11, 18), (10, 0), (11, 0))      # today
    _stay(u.id, _meeting(date(2026, 11, 16), (9, 0)), date(2026, 11, 16), (9, 0), (9, 30))        # Monday
    _stay(u.id, _meeting(date(2026, 11, 1), (9, 0)), date(2026, 11, 1), (9, 0), (9, 10))           # earlier in the month
    _stay(u.id, _meeting(date(2026, 10, 31), (9, 0)), date(2026, 10, 31), (9, 0), (10, 0))         # last month
    j = u.post("/api/meetings/timer/ping").json()
    assert j["today_seconds"] == 3600
    assert j["week_seconds"] == 3600 + 1800
    assert j["month_seconds"] == 3600 + 1800 + 600
    assert "current" in j and j["server_time"]


def test_meeting_report_csv_is_the_same_rows_as_the_screen(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.onroll
    m = _meeting(day, (9, 0), minutes=60)
    _stay(u.id, m, day, (9, 0), (10, 0))
    _stay(u.id, m, day, (10, 30), None, source="extension")                       # still in it
    js = org.admin.get("/api/meetings/timer/report").json()
    row = next(r for r in js["rows"] if r["user_id"] == u.id)
    text = org.admin.get("/api/meetings/timer/report", params={"format": "csv"}).text
    lines = [l for l in text.splitlines() if l.strip()]
    head = lines[0].split(",")
    assert head == ["User", "Role", "Meeting", "Joined", "Left", "Status", "Duration (s)",
                    "Meeting time in range (s)", "Meetings", "Joins", "Detected by", "Ended because"]
    body = [l.split(",") for l in lines[1:-1]]
    # one line per stay for people who have any, one summary line for people who have none
    expected = sum(len(r["stays"]) if r["stays"] else 1 for r in js["rows"])
    assert len(body) == expected and len(lines) == expected + 2
    mine = [d for d in body if d[0] == "Onroll One"]
    assert len(mine) == 2                                        # both stays of that person, name on each line
    assert sum(int(d[6]) for d in mine) == row["meeting_seconds"]
    assert mine[-1][5] == "in the meeting" and mine[-1][10] == "extension"
    assert mine[0][7] == str(row["meeting_seconds"]) and mine[0][8] == str(row["meetings"]) == "1"
    assert mine[1][7] == ""                                      # a person total once, never twice
    assert all(d[5] == "no meeting in this range" for d in body if d[0] == "Offroll One")
    total = lines[-1].split(",")
    assert total[0] == "TOTAL" and int(total[6]) == sum(r["meeting_seconds"] for r in js["rows"])
    assert int(total[8]) == sum(r["meetings"] for r in js["rows"]) and int(total[9]) == sum(r["joins"] for r in js["rows"])
    assert org.admin.get("/api/meetings/timer/report", params={"format": "pdf"}).status_code == 422


def test_an_interrupted_meeting_ends_at_the_last_report_not_at_midnight(org, monkeypatch):
    """The browser was closed mid-meeting: no Leave, no heartbeat. The report must not keep counting."""
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=28800)
    _work_session(u.id, day, (9, 0), (17, 0), "regular", active=28800)
    m = _meeting(day, (14, 0), minutes=120)                                 # planned until 16:00
    db = _db()
    stale = MeetingAttendance(meeting_id=m, user_id=u.id, joined_at=_at(day, 14, 0), left_at=None,
                              last_seen_at=_at(day, 14, 25), source="extension")     # silent since 14:25
    db.add(stale); db.commit(); sid = stale.id; db.close()

    r = _row(org.admin, u.id)
    assert r["meeting_seconds"] == 1500                                      # 14:00 -> 14:25, not 14:00 -> 18:00
    assert r["meeting_outside_seconds"] == 0 and r["total_seconds"] == 28800
    assert r["in_meeting"] is False
    db = _db()
    row = db.get(MeetingAttendance, sid)
    assert row.end_reason == "no_signal" and row.left_at == _at(day, 14, 25)     # ended at the last report
    db.close()
    # reading the report a second time changes nothing: the number is stable
    assert _row(org.admin, u.id)["meeting_seconds"] == 1500


# ---- build 33: the Grand Total (regular + extra + meeting, meeting added on purpose) --------

def test_grand_total_is_regular_plus_extra_plus_meeting_hours(org, monkeypatch):
    """The example in the request: 8 h regular + 2 h extra + 1 h 30 m meeting = 11 h 30 m grand total."""
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=28800, extra=7200)
    _work_session(u.id, day, (9, 0), (19, 0), "regular", active=28800)
    m = _meeting(day, (13, 0), minutes=90)
    _stay(u.id, m, day, (13, 0), (14, 30))                              # fully inside the work session

    r = _row(org.admin, u.id)
    assert r["active_seconds"] == 28800 and r["extra_seconds"] == 7200
    assert r["meeting_seconds"] == 5400
    assert r["grand_total_seconds"] == 28800 + 7200 + 5400              # 41400 = 11 h 30 m
    assert r["total_seconds"] == 36000                                   # the non-duplicated figure stays
    assert r["meeting_work_seconds"] == 5400 and r["meeting_outside_seconds"] == 0
    t = _resp(org.admin)["totals"]
    assert t["grand_total_seconds"] == 41400 and t["total_seconds"] == 36000


def test_grand_total_counts_meetings_that_overlap_work_as_well(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.onroll
    _plant(u.id, active=28800)
    _work_session(u.id, day, (9, 0), (17, 0), "regular", active=28800)
    m = _meeting(day, (10, 0), minutes=120)
    _stay(u.id, m, day, (10, 0), (12, 0))                                # 2 h, 100 % inside the 8 h

    r = _row(org.admin, u.id)
    assert r["total_seconds"] == 28800                                   # attendance figure: still 8 h
    assert r["grand_total_seconds"] == 28800 + 7200                      # grand total: 10 h, meeting added


def test_grand_total_follows_the_role_and_date_filters(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    y = day - timedelta(days=1)
    _plant(org.onroll.id, active=28800, extra=7200, day=day)
    _plant(org.outsider.id, active=3600, day=day)
    m_today = _meeting(day, (13, 0), minutes=90)
    m_yest = _meeting(y, (13, 0), minutes=60)
    _stay(org.onroll.id, m_today, day, (13, 0), (14, 30))
    _stay(org.outsider.id, m_today, day, (13, 0), (14, 0))
    _stay(org.onroll.id, m_yest, y, (9, 0), (10, 0))

    today = _resp(org.admin, start=day.isoformat(), end=day.isoformat())
    assert today["totals"]["grand_total_seconds"] == 28800 + 7200 + 5400 + 3600 + 3600
    both = _resp(org.admin, start=y.isoformat(), end=day.isoformat())
    assert both["totals"]["grand_total_seconds"] == today["totals"]["grand_total_seconds"] + 3600

    onrolls = _resp(org.admin, start=day.isoformat(), end=day.isoformat(), role="onroll")
    assert {x["role"] for x in onrolls["rows"]} == {"onroll"}                       # the role filter applied
    assert org.onroll.id in {x["user_id"] for x in onrolls["rows"]}
    assert org.outsider.id not in {x["user_id"] for x in onrolls["rows"]}
    assert onrolls["totals"]["grand_total_seconds"] == 28800 + 7200 + 5400
    assert onrolls["totals"]["total_seconds"] == 28800 + 7200
    interns = _resp(org.admin, start=day.isoformat(), end=day.isoformat(), role="intern")
    assert interns["totals"]["grand_total_seconds"] == 3600 + 3600

    # the on-roll lead sees their own team's grand total, nothing of the other team
    lead = _resp(org.onroll, start=day.isoformat(), end=day.isoformat())
    assert lead["totals"]["grand_total_seconds"] == 28800 + 7200 + 5400


def test_grand_total_is_a_column_and_a_range_total_in_the_csv(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=28800, extra=7200)
    _work_session(u.id, day, (9, 0), (19, 0), "regular", active=28800)
    m = _meeting(day, (13, 0), minutes=90)
    _stay(u.id, m, day, (13, 0), (14, 30))
    js = _resp(org.admin)
    row = next(x for x in js["rows"] if x["user_id"] == u.id)
    lines = [l for l in org.admin.get("/api/timer/overview", params={"format": "csv"}).text.splitlines() if l.strip()]
    head = lines[0].split(",")
    assert "Grand total (s)" in head
    cells = dict(zip(head, next(l for l in lines if l.startswith("Offroll One")).split(",")))
    totals = dict(zip(head, lines[-1].split(",")))
    assert cells["Grand total (s)"] == str(row["grand_total_seconds"]) == "41400"
    assert cells["Total working (s)"] == str(row["total_seconds"]) == "36000"
    assert totals["Name"] == "RANGE TOTALS"
    assert totals["Grand total (s)"] == str(js["totals"]["grand_total_seconds"]) == "41400"
    assert totals["Meeting total (s)"] == "5400" and totals["Extra total (s)"] == "7200"
    # every column in the RANGE TOTALS line is the sum of that column, so the grand total is the sum of the
    # three it is built from (Active (s) in the file is the regular column, as in each employee row above it)
    assert int(totals["Grand total (s)"]) == (int(totals["Active (s)"]) + int(totals["Extra total (s)"])
                                              + int(totals["Meeting total (s)"]))
    assert int(totals["Total working (s)"]) == int(totals["Active (s)"]) + int(totals["Extra total (s)"])


def test_grand_total_never_moves_the_attendance_numbers(org, monkeypatch):
    """Reading the report must not change what the timer itself recorded."""
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=28800, extra=7200)
    _work_session(u.id, day, (9, 0), (19, 0), "regular", active=28800)
    m = _meeting(day, (13, 0), minutes=90)
    _stay(u.id, m, day, (13, 0), (14, 30))
    db = _db()
    from app.database.models import Attendance, WorkSession
    att_before = [(a.day, a.active_seconds, a.extra_seconds) for a in db.query(Attendance).filter_by(user_id=u.id)]
    ws_before = [(w.active_seconds, w.schedule, w.ended_at) for w in db.query(WorkSession).filter_by(user_id=u.id)]
    db.close()
    for _ in range(3):
        org.admin.get("/api/timer/overview")
    db = _db()
    assert [(a.day, a.active_seconds, a.extra_seconds) for a in db.query(Attendance).filter_by(user_id=u.id)] == att_before
    assert [(w.active_seconds, w.schedule, w.ended_at) for w in db.query(WorkSession).filter_by(user_id=u.id)] == ws_before
    db.close()


# ---- build 34: the employee's own daily attendance rows carry the meeting timer ----------------

def test_the_employee_daily_rows_carry_meeting_time_and_totals(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.intern
    _plant(u.id, active=7200, extra=1800, idle=600)
    m = _meeting(day, (10, 0), minutes=90, title="Daily check")
    _stay(u.id, m, day, (10, 0), (11, 30))
    _stay(u.id, m, day, (14, 0), (14, 30))                       # same meeting, a second stay

    rows = u.get("/api/attendance", params={"days": 7}).json()
    r = next(x for x in rows if x["day"] == day.isoformat())
    assert r["active_seconds"] == 7200 and r["extra_seconds"] == 1800
    assert r["meeting_seconds"] == 5400 + 1800
    assert r["meetings"] == 1 and r["meeting_joins"] == 2
    assert r["is_today"] is True and all(x["is_today"] is False for x in rows if x["day"] != day.isoformat())
    assert r["actual_seconds"] == 7200 + 1800                     # attendance figure, nothing counted twice
    assert r["total_seconds"] == 7200 + 1800 + 5400 + 1800        # grand total: meetings added again on purpose
    # a day without meetings keeps its own numbers, untouched
    y = next((x for x in rows if x["day"] != day.isoformat()), None)
    assert y is None or y["meeting_seconds"] == 0


def test_a_meeting_belongs_to_the_day_it_started(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    prev = day - timedelta(days=1)
    u = org.intern
    _plant(u.id, active=3600, day=prev)
    _plant(u.id, active=600, day=day)
    m = _meeting(prev, (23, 0), minutes=100, title="Late night")
    db = _db()                                                    # the stay crosses midnight, so place it by hand
    db.add(MeetingAttendance(meeting_id=m, user_id=u.id, joined_at=_at(prev, 23, 0), left_at=_at(day, 0, 40),
                             last_seen_at=_at(day, 0, 40), source="manual", end_reason="left"))
    db.commit(); db.close()

    rows = {x["day"]: x for x in u.get("/api/attendance", params={"days": 7}).json()}
    assert rows[prev.isoformat()]["meeting_seconds"] == 6000      # all of it stays on the day it started
    assert rows[prev.isoformat()]["total_seconds"] == 3600 + 6000
    assert rows[day.isoformat()]["meeting_seconds"] == 0
    assert rows[day.isoformat()]["total_seconds"] == 600


def test_the_daily_breakdown_reads_and_never_writes(org, monkeypatch):
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.offroll
    _plant(u.id, active=3600)
    m = _meeting(day, (10, 0))
    _stay(u.id, m, day, (10, 0), (10, 30))
    db = _db()
    from app.database.models import Attendance, MeetingAttendance, WorkSession
    before = (db.query(Attendance).count(), db.query(MeetingAttendance).count(), db.query(WorkSession).count())
    db.close()
    for _ in range(3):
        assert u.get("/api/attendance", params={"days": 7}).status_code == 200
    db = _db()
    assert (db.query(Attendance).count(), db.query(MeetingAttendance).count(), db.query(WorkSession).count()) == before
    db.close()


def test_the_daily_rows_follow_the_same_permission_rules(org, monkeypatch):
    _freeze(monkeypatch)
    # an intern may not read someone else's days, and the new fields change nothing about that
    r = org.intern.get("/api/attendance", params={"user_id": org.onroll.id, "days": 7})
    assert r.status_code == 403
    # the team lead reads their team member's days, with the meeting numbers in them
    now = _now()
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    _plant(org.offroll.id, active=1800)
    m = _meeting(day, (11, 0))
    _stay(org.offroll.id, m, day, (11, 0), (11, 20))
    rows = org.dev.get("/api/attendance", params={"user_id": org.offroll.id, "days": 7}).json()
    r = next(x for x in rows if x["day"] == day.isoformat())
    assert r["meeting_seconds"] == 1200 and r["total_seconds"] == 1800 + 1200 and r["actual_seconds"] == 1800


def test_a_silent_open_stay_stops_at_its_last_signal_and_a_live_one_keeps_running(org, monkeypatch):
    """A Meet tab that was killed, slept or refreshed never says "left". Counting that stay up to now would
    add hours nobody worked and grow while the person watches their dashboard; the number has to be the one
    the sweep will settle on. A stay that is still being reported keeps running, of course."""
    now = _freeze(monkeypatch)
    day = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    u = org.intern
    _plant(u.id, active=3600)
    dead = _meeting(day, (10, 0), minutes=60, title="Stand-up that was never closed")
    live = _meeting(day, (17, 40), minutes=60, title="Still in it")
    db = _db()
    db.add(MeetingAttendance(meeting_id=dead, user_id=u.id, joined_at=_at(day, 10, 0), left_at=None,
                             last_seen_at=_at(day, 10, 30), source="extension"))      # the signal stopped at 10:30
    db.add(MeetingAttendance(meeting_id=live, user_id=u.id, joined_at=_at(day, 17, 40), left_at=None,
                             last_seen_at=_at(day, 18, 0), source="extension"))       # reported this very minute
    db.commit(); db.close()

    r = next(x for x in u.get("/api/attendance", params={"days": 7}).json() if x["day"] == day.isoformat())
    assert r["meeting_seconds"] == 1800 + 1200            # the dead one stops at 10:30, the live one runs to now
    assert r["total_seconds"] == 3600 + 1800 + 1200
    assert r["meetings"] == 2 and r["meeting_joins"] == 2
    admin = _row(org.admin, u.id)                          # the admin report shows the same before it sweeps
    assert admin["meeting_seconds"] == 1800 + 1200 and admin["grand_total_seconds"] == r["total_seconds"]

    db = _db()                                             # the sweep then closes the silent stay at 10:30
    closed = [x for x in db.query(MeetingAttendance).filter_by(user_id=u.id, left_at=None).all()]
    assert len(closed) == 1 and closed[0].meeting_id == live
    db.close()
    r2 = next(x for x in u.get("/api/attendance", params={"days": 7}).json() if x["day"] == day.isoformat())
    assert r2["meeting_seconds"] == 1800 + 1200             # and nothing about the day changed afterwards

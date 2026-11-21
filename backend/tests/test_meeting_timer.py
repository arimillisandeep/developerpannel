"""Meeting timer (build 27): separate from the work timer, automatic through the extension, Join / Leave as fallback."""
from datetime import timedelta

import pytest

from app.api import meeting_timer as mt
from app.database import models
from app.database.connection import SessionLocal
from app.database.models import utcnow
from tests.conftest import org  # noqa: F401

TAB = "tab-aaaaaaaa"


class Clock:
    def __init__(self):
        self.t = utcnow()

    def __call__(self):
        return self.t

    def add(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(mt, "utcnow", c)
    return c


def schedule(org, clock, link="https://meet.google.com/abc-defg-hij", minutes=30, starts_in=0, title="Daily sync"):
    r = org.dev.post("/api/meetings", {"title": title, "starts_at": (clock.t + timedelta(minutes=starts_in)).isoformat(),
                                       "duration_minutes": minutes, "link": link, "participant_ids": [org.intern.id, org.offroll.id]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ext(actor):
    token = actor.post("/api/extension/token").json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    class E:
        def watch(self):
            return actor.client.get("/api/extension/meetings", headers=h).json()["meetings"]

        def tabs(self, *ids):
            r = actor.client.post("/api/extension/meetings", headers=h, json={"open_ids": list(ids)})
            assert r.status_code == 200, r.text
            return r.json()["in_meeting"]
    return E()


def stays(user_id):
    db = SessionLocal()
    rows = [(r.joined_at, r.left_at, r.source, r.end_reason) for r in
            db.query(models.MeetingAttendance).filter_by(user_id=user_id).order_by(models.MeetingAttendance.id)]
    db.close()
    return rows


def work_state(user_id):
    db = SessionLocal()
    s = db.query(models.WorkSession).filter_by(user_id=user_id).order_by(models.WorkSession.id.desc()).first()
    events = db.query(models.TimerEvent).filter_by(user_id=user_id).count()
    att = [(a.day, a.active_seconds, a.idle_seconds, a.away_seconds, a.paused_seconds) for a in db.query(models.Attendance).filter_by(user_id=user_id)]
    out = (s.id, s.state, s.mode, s.active_seconds, s.away_seconds, s.idle_seconds, s.started_at, s.ended_at, events, att)
    db.close()
    return out


def test_extension_starts_on_join_and_stops_on_leave_with_exact_times(client, org, clock):
    mid = schedule(org, clock)
    e = ext(org.intern)
    assert [m["id"] for m in e.watch()] == [mid] and e.watch()[0]["link"].startswith("https://meet.google.com/")
    assert e.tabs() is None and stays(org.intern.id) == []          # no meeting tab: nothing starts
    clock.add(minutes=1)
    joined = clock.t
    assert e.tabs(mid) == mid                                        # the meeting page is open: joined
    for _ in range(20):                                              # 10 minutes, a report every 30 s
        clock.add(seconds=30)
        assert e.tabs(mid) == mid
    left = clock.t + timedelta(seconds=10)
    clock.add(seconds=10)
    assert e.tabs() is None                                          # tab closed: left
    assert stays(org.intern.id) == [(joined, left, "extension", "tab_closed")]
    # joins again later: a second row, the total is the sum
    clock.add(minutes=3)
    e.tabs(mid)
    clock.add(minutes=2)
    e.tabs()
    r = org.admin.get("/api/meetings/timer/report").json()
    row = next(x for x in r["rows"] if x["user_id"] == org.intern.id)
    assert row["meeting_seconds"] == 610 + 120 and row["joins"] == 2 and row["meetings"] == 1 and row["in_meeting"] is None
    assert [s["seconds"] for s in row["stays"]] == [610, 120] and row["stays"][0]["title"] == "Daily sync"
    assert row["stays"][0]["joined_at"] and row["stays"][0]["left_at"]


def test_the_work_timer_is_not_touched_by_the_meeting_timer(client, org, clock):
    mid = schedule(org, clock)
    u = org.intern
    assert u.post("/api/sessions/start", {"client_id": TAB}).status_code == 200
    assert u.post("/api/sessions/heartbeat", {"client_id": TAB, "state": "active"}).status_code == 200
    before = work_state(u.id)
    e = ext(u)
    e.tabs(mid)
    clock.add(minutes=20)
    assert u.post(f"/api/meetings/{mid}/leave").status_code == 200
    assert u.post(f"/api/meetings/{mid}/join").status_code == 200
    clock.add(minutes=5)
    u.post("/api/meetings/timer/ping")
    u.post(f"/api/meetings/{mid}/leave")
    org.admin.get("/api/meetings/timer/report")
    assert work_state(u.id) == before                                # same session, same seconds, no timer event added
    # and the other way round: the work timer's own calls do not move the meeting timer
    e.tabs(mid)
    rows = stays(u.id)
    u.post("/api/sessions/heartbeat", {"client_id": TAB, "state": "away"})
    u.post("/api/sessions/pause")
    u.post("/api/sessions/resume")
    u.post("/api/sessions/stop")
    assert stays(u.id) == rows and rows[-1][1] is None               # still in the meeting after Stop of the work timer


def test_join_and_leave_buttons_work_without_the_extension(client, org, clock):
    mid = schedule(org, clock)
    u = org.offroll
    r = u.post(f"/api/meetings/{mid}/join").json()
    assert r["current"]["meeting_id"] == mid and r["current"]["source"] == "manual" and r["current"]["left_at"] is None
    for _ in range(8):
        clock.add(seconds=60)                                        # a hidden WORKCODE tab still pings about once a minute
        assert u.post("/api/meetings/timer/ping").json()["current"]["meeting_id"] == mid
    r = u.post(f"/api/meetings/{mid}/leave").json()
    assert r["current"] is None and r["today_seconds"] == 480
    assert stays(u.id)[0][2:] == ("manual", "left")


def test_a_stay_that_stops_reporting_ends_at_its_last_report(client, org, clock):
    mid = schedule(org, clock)
    e = ext(org.intern)
    e.tabs(mid)
    clock.add(seconds=30)
    e.tabs(mid)
    last = clock.t
    clock.add(hours=2)                                               # laptop lid closed
    r = org.admin.get("/api/meetings/timer/report").json()
    row = next(x for x in r["rows"] if x["user_id"] == org.intern.id)
    assert row["meeting_seconds"] == 30 and row["in_meeting"] is None
    assert stays(org.intern.id)[0][1] == last and stays(org.intern.id)[0][3] == "no_signal"


def test_join_button_stay_ends_one_hour_after_the_planned_end_if_never_left(client, org, clock):
    mid = schedule(org, clock, minutes=30)
    u = org.offroll
    start = clock.t
    u.post(f"/api/meetings/{mid}/join")
    for _ in range(100):
        clock.add(seconds=60)
        u.post("/api/meetings/timer/ping")
    row = stays(u.id)[0]
    assert row[3] == "limit" and row[1] == start + timedelta(minutes=90)


def test_extension_takes_over_a_stay_started_with_the_button(client, org, clock):
    mid = schedule(org, clock)
    u = org.intern
    u.post(f"/api/meetings/{mid}/join")
    e = ext(u)
    clock.add(seconds=20)
    assert e.tabs() == mid                 # tab not seen (yet, or a desktop program): the button's stay goes on
    clock.add(seconds=20)
    assert e.tabs(mid) == mid              # now the tab is seen: the extension owns it
    clock.add(seconds=30)
    assert e.tabs() is None                # and ends it when the tab closes
    assert len(stays(u.id)) == 1 and stays(u.id)[0][2:] == ("extension", "tab_closed")


def test_only_own_open_meetings_count(client, org, clock):
    mid = schedule(org, clock)
    later = schedule(org, clock, starts_in=600, title="Tomorrow", link="https://zoom.us/j/1234567890")
    out = org.outsider
    assert out.post(f"/api/meetings/{mid}/join").status_code == 404                  # not invited
    assert ext(out).watch() == [] and ext(out).tabs(mid) is None and stays(out.id) == []
    assert org.intern.post(f"/api/meetings/{later}/join").status_code == 409         # not open yet
    assert [m["id"] for m in ext(org.intern).watch()] == [mid]
    assert ext(org.intern).tabs(later) is None
    assert org.dev.delete(f"/api/meetings/{mid}").status_code == 200
    assert org.intern.post(f"/api/meetings/{mid}/join").status_code == 409           # cancelled
    assert client.post(f"/api/meetings/{mid}/join").status_code == 401
    assert client.post("/api/extension/meetings", json={"open_ids": [mid]}, headers=org.intern.h).status_code == 401   # login token is not an extension token


def test_one_meeting_at_a_time_and_cancel_ends_the_stay(client, org, clock):
    a = schedule(org, clock, title="Meeting A")
    b = schedule(org, clock, title="Meeting B", link="https://teams.microsoft.com/l/meetup-join/xyz")
    u = org.intern
    u.post(f"/api/meetings/{a}/join")
    for _ in range(4):
        clock.add(minutes=1)
        u.post("/api/meetings/timer/ping")
    u.post(f"/api/meetings/{b}/join")
    rows = stays(u.id)
    assert rows[0][3] == "switched" and rows[0][1] == clock.t and rows[1][1] is None
    clock.add(minutes=1)
    org.dev.delete(f"/api/meetings/{b}")
    clock.add(seconds=5)
    assert u.post("/api/meetings/timer/ping").json()["current"] is None
    assert stays(u.id)[1][3] == "cancelled"


def test_report_shows_both_timers_separately_and_respects_roles(client, org, clock):
    mid = schedule(org, clock)
    db = SessionLocal()
    db.add(models.Attendance(user_id=org.intern.id, day=mt.local_day(clock.t), active_seconds=3600))
    db.commit()
    db.close()
    org.intern.post(f"/api/meetings/{mid}/join")
    for _ in range(10):
        clock.add(minutes=1)
        org.intern.post("/api/meetings/timer/ping")
    r = org.admin.get("/api/meetings/timer/report").json()
    row = next(x for x in r["rows"] if x["user_id"] == org.intern.id)
    assert (row["work_seconds"], row["meeting_seconds"]) == (3600, 600)          # two numbers, neither changes the other
    assert row["in_meeting"]["title"] == "Daily sync" and row["stays"][0]["left_at"] is None
    assert {x["user_id"] for x in r["rows"]} >= {org.intern.id, org.offroll.id, org.outsider.id, org.dev.id}
    lead = {x["user_id"] for x in org.dev.get("/api/meetings/timer/report").json()["rows"]}
    assert lead == {org.dev.id, org.onroll.id, org.offroll.id, org.intern.id}     # own team only
    assert [x["user_id"] for x in org.offroll.get("/api/meetings/timer/report").json()["rows"]] == [org.offroll.id]
    yesterday = (mt.local_day(clock.t) - timedelta(days=1)).isoformat()
    old = org.admin.get(f"/api/meetings/timer/report?start={yesterday}&end={yesterday}").json()
    assert next(x for x in old["rows"] if x["user_id"] == org.intern.id)["meeting_seconds"] == 0
    assert client.get("/api/meetings/timer/report").status_code == 401


def test_silent_stay_is_closed_before_a_new_join_and_never_revived(client, org, clock):
    a = schedule(org, clock, title="Meeting A")
    u = org.intern
    u.post(f"/api/meetings/{a}/join")
    first = clock.t
    clock.add(minutes=10)                                             # WORKCODE closed for 10 minutes, no ping
    assert u.post("/api/meetings/timer/ping").json()["current"] is None
    assert stays(u.id) == [(first, first, "manual", "no_signal")]
    u.post(f"/api/meetings/{a}/join")
    assert len(stays(u.id)) == 2 and stays(u.id)[0][3] == "no_signal" and stays(u.id)[1][1] is None

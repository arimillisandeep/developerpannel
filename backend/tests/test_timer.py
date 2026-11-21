from tests.conftest import Actor
from datetime import timedelta

from app.database.connection import SessionLocal
from app.database.models import Attendance, WorkSession, utcnow
from app.services import timer

A, B = "tab-aaaaaaaa", "tab-bbbbbbbb"


def _session(user_id, t0):
    db = SessionLocal()
    s = timer.start(db, user_id, A, now=t0)
    db.commit()
    return db, s


def test_server_measures_time_and_caps_gaps(admin):
    t0 = utcnow() - timedelta(hours=5)
    db, s = _session(admin.id, t0)
    for i in range(1, 5):                      # 4 heartbeats, 15 s apart, tab focused
        assert timer.heartbeat(db, s, A, "active", now=t0 + timedelta(seconds=15 * i))
    assert s.active_seconds == 60
    timer.heartbeat(db, s, A, "away", now=t0 + timedelta(seconds=75))     # tab hidden from here
    timer.heartbeat(db, s, A, "away", now=t0 + timedelta(seconds=90))
    assert (s.active_seconds, s.away_seconds) == (75, 15)
    # laptop sleeps for 3 hours: only the 45 s cap is credited, never 3 hours
    timer.heartbeat(db, s, A, "active", now=t0 + timedelta(hours=3))
    assert s.away_seconds == 15 + 45 and s.active_seconds == 75
    assert s.last_return_at == t0 + timedelta(hours=3)      # came back from away
    db.commit()
    att = db.query(Attendance).filter_by(user_id=admin.id).all()
    assert sum(a.active_seconds for a in att) == 75 and sum(a.away_seconds for a in att) == 60
    db.close()


def test_only_one_tab_reports(admin):
    t0 = utcnow() - timedelta(hours=1)
    db, s = _session(admin.id, t0)
    timer.heartbeat(db, s, A, "active", now=t0 + timedelta(seconds=15))
    # a second, hidden tab is ignored and adds nothing
    assert timer.heartbeat(db, s, B, "away", now=t0 + timedelta(seconds=20)) is False
    assert s.client_id == A and s.active_seconds == 15
    # when the second tab becomes the focused one it takes over; time is not double counted
    assert timer.heartbeat(db, s, B, "active", now=t0 + timedelta(seconds=30)) is True
    assert timer.heartbeat(db, s, A, "away", now=t0 + timedelta(seconds=35)) is False
    timer.heartbeat(db, s, B, "active", now=t0 + timedelta(seconds=45))
    assert s.active_seconds == 45 and s.away_seconds == 0
    db.close()


def test_pause_resume_and_stop(admin):
    t0 = utcnow() - timedelta(hours=1)
    db, s = _session(admin.id, t0)
    timer.heartbeat(db, s, A, "active", now=t0 + timedelta(seconds=30))
    timer.set_paused(db, s, True, now=t0 + timedelta(seconds=40))
    timer.heartbeat(db, s, A, "active", now=t0 + timedelta(seconds=70))
    timer.set_paused(db, s, False, now=t0 + timedelta(seconds=80))
    timer.end(db, s, "stopped", now=t0 + timedelta(seconds=100))
    assert (s.active_seconds, s.paused_seconds, s.state) == (60, 40, "ended")
    db.close()


def test_stale_session_is_closed_and_new_one_started(admin):
    t0 = utcnow() - timedelta(days=2)
    db, s = _session(admin.id, t0)
    timer.heartbeat(db, s, A, "active", now=t0 + timedelta(seconds=30))
    db.commit()
    s2 = timer.start(db, admin.id, A, now=t0 + timedelta(days=1))
    db.commit()
    assert s2.id != s.id and s.state == "ended" and s.end_reason == "stale"
    assert s.ended_at == t0 + timedelta(seconds=30) and s.active_seconds == 30
    db.close()


def test_session_api_single_session_across_navigation_and_tabs(client, admin, make_user):
    r1 = admin.post("/api/sessions/start", {"client_id": A}).json()
    r2 = admin.post("/api/sessions/start", {"client_id": B}).json()   # second tab / page reload
    assert r1["session"]["id"] == r2["session"]["id"] and r2["is_reporting_tab"] is False
    assert admin.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).status_code == 200
    assert admin.post("/api/sessions/pause").json()["session"]["state"] == "paused"
    assert admin.post("/api/sessions/resume").json()["session"]["state"] == "running"
    assert admin.get("/api/sessions/live").json()[0]["state"] == "working"
    assert admin.post("/api/sessions/stop").json()["session"] is None
    assert admin.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).status_code == 409
    # logout closes a session; attendance is private
    u = make_user("intern", "Timer Intern")
    u.post("/api/sessions/start", {"client_id": A})
    u.post("/api/auth/logout")
    db = SessionLocal()
    assert db.query(WorkSession).filter_by(user_id=u.id).one().end_reason == "logout"
    db.close()
    assert u.get("/api/auth/me").status_code == 401     # the token is dead after logout (API audit, build 19)
    u = Actor(client, u.user["email"])                   # so the person signs in again
    assert u.get(f"/api/attendance?user_id={admin.id}").status_code == 403
    assert admin.get(f"/api/attendance?user_id={u.id}").status_code == 200

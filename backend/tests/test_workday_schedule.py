"""Build 29: the regular 8 h schedule, the separate Continue schedule and recording retention.
The elapsed time is planted directly in the attendance rows, so nothing sleeps and the arithmetic is exact."""
from datetime import timedelta

from app.core.config import settings
from app.database import models
from app.database.connection import SessionLocal
from app.database.models import Attendance, ScreenRecording, WorkSession, utcnow
from app.services.common import local_day
from tests.conftest import org  # noqa: F401

A = "tab-aaaaaaaa"


def _db():
    return SessionLocal()


def _rewind(db, session_id, seconds):
    """Time travel for the test: the next heartbeat finds the session silent for `seconds`,
    which is exactly what the server then credits (API calls run in milliseconds of real time)."""
    s = db.get(WorkSession, session_id)
    s.last_heartbeat_at = utcnow() - timedelta(seconds=seconds)
    db.commit()


def _push_active(db, user_id, seconds):
    day = local_day(utcnow())
    row = db.query(Attendance).filter_by(user_id=user_id, day=day).first()
    if row is None:
        row = Attendance(user_id=user_id, day=day, active_seconds=0, away_seconds=0, idle_seconds=0,
                         paused_seconds=0, extra_seconds=0, status="present")
        db.add(row)
    row.active_seconds += seconds
    db.commit()
    return row


def _attendance(user_id):
    db = _db()
    try:
        return db.query(Attendance).filter_by(user_id=user_id, day=local_day(utcnow())).first()
    finally:
        db.close()


def _session(user_id, session_id):
    db = _db()
    try:
        return db.get(WorkSession, session_id)
    finally:
        db.close()


def test_regular_schedule_completes_at_the_target(org, monkeypatch):
    monkeypatch.setattr(settings, "WORKDAY_TARGET_HOURS", 0.01)          # 36 seconds for the test
    o = org.offroll
    r = o.post("/api/sessions/start", {"client_id": A, "auto": True})
    assert r.status_code == 200
    j = r.json()
    assert j["schedule_target_seconds"] == 36 and not j["regular_completed"]
    sid = j["session"]["id"]
    assert j["session"]["schedule"] == "regular"

    db = _db()
    _push_active(db, o.id, 30)                                            # 30 s counted, 6 s to go
    db.close()
    j = o.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()
    assert j["regular_remaining_seconds"] >= 1 and not j["regular_completed"]

    db = _db()
    _push_active(db, o.id, 6)                                             # target reached
    db.close()
    j = o.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()
    assert j["regular_completed"] and j["session"] is None

    s = _session(o.id, sid)
    assert s.state == "ended" and s.end_reason == "day_complete"
    att = _attendance(o.id)
    assert att.regular_completed_at is not None
    assert o.get("/api/sessions/current").json()["regular_completed"]    # survives a refresh


def test_auto_start_stays_off_after_the_day_is_done(org, monkeypatch):
    monkeypatch.setattr(settings, "WORKDAY_TARGET_HOURS", 0.01)
    o = org.onroll
    o.post("/api/sessions/start", {"client_id": A, "auto": True})
    db = _db()
    _push_active(db, o.id, 40)
    db.close()
    assert o.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()["regular_completed"]
    j = o.post("/api/sessions/start", {"client_id": A, "auto": True}).json()
    assert j["session"] is None and j["regular_completed"]


def test_continue_schedule_is_separate_and_never_touches_regular_totals(org, monkeypatch):
    monkeypatch.setattr(settings, "WORKDAY_TARGET_HOURS", 0.01)
    o = org.offroll
    # before the target is reached, Continue is refused
    o.post("/api/sessions/start", {"client_id": A, "auto": True})
    r = o.post("/api/sessions/continue", {"client_id": A})
    assert r.status_code == 409
    db = _db()
    att = _push_active(db, o.id, 36)
    db.close()
    assert o.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()["regular_completed"]

    r = o.post("/api/sessions/continue", {"client_id": A})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["session"]["schedule"] == "extra"
    extra_id = j["session"]["id"]
    regular_active = _attendance(o.id).active_seconds

    db = _db()
    for _ in range(3):
        _rewind(db, extra_id, 15)
        j = o.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()
    db.close()
    assert j["session"]["schedule"] == "extra"

    att = _attendance(o.id)
    assert att.active_seconds == regular_active            # the regular totals never move
    assert att.extra_seconds > 0                           # extra seconds land in their own column
    assert j["today"]["extra_seconds"] == att.extra_seconds
    assert j["extra_seconds_today"] == att.extra_seconds
    s = _session(o.id, extra_id)
    assert s.schedule == "extra" and s.active_seconds > 0

    # pressing plain Start again while the extra session runs does not create a second one
    j = o.post("/api/sessions/start", {"client_id": "tab-bbbbbbbb", "auto": False}).json()
    assert j["session"]["id"] == extra_id

    def row(admin_actor):
        rows = admin_actor.get("/api/timer/overview").json()["rows"]
        return [x for x in rows if x["user_id"] == o.id][0]

    r0 = row(org.admin)
    assert r0["extra_running"] is True and r0["schedule_label"] == "Extra"
    assert r0["extra_start"] is not None and r0["extra_end"] is None

    j = o.post("/api/sessions/stop").json()
    assert j["session"] is None
    r1 = row(org.admin)
    assert r1["extra_running"] is False and r1["extra_end"] is not None
    assert r1["schedule_label"] == "Completed"
    assert r1["extra_seconds"] >= 45                     # period total: the three 15 s heartbeats
    assert r1["days_present"] == 1
    # a new day is not implied: after stopping, Continue just restarts the extra session (same day)
    r = o.post("/api/sessions/continue", {"client_id": A})
    assert r.status_code == 200 and r.json()["session"]["schedule"] == "extra"


def test_regular_start_after_completion_presses_on_with_extra(org, monkeypatch):
    monkeypatch.setattr(settings, "WORKDAY_TARGET_HOURS", 0.01)
    o = org.onroll
    o.post("/api/sessions/start", {"client_id": A, "auto": True})
    db = _db()
    _push_active(db, o.id, 40)
    db.close()
    assert o.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()["regular_completed"]
    # the employee presses the normal Start button: that continues on the extra schedule
    j = o.post("/api/sessions/start", {"client_id": A, "auto": False}).json()
    assert j["session"]["schedule"] == "extra"


def test_interns_have_no_eight_hour_auto_close(org, monkeypatch):
    monkeypatch.setattr(settings, "WORKDAY_TARGET_HOURS", 0.01)
    o = org.intern
    s = o.post("/api/sessions/start", {"client_id": A, "auto": True}).json()["session"]
    db = _db()
    _push_active(db, o.id, 40000)
    db.close()
    j = o.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()
    assert j["session"] is not None and j["session"]["id"] == s["id"]
    assert not j["regular_completed"]
    assert o.post("/api/sessions/continue", {"client_id": A}).status_code == 409


def test_attendance_endpoint_shows_extra_separately(org):
    o = org.offroll
    db = _db()
    att = _push_active(db, o.id, 100)
    att.extra_seconds = 450
    att.regular_completed_at = utcnow()
    db.commit()
    db.close()
    rows = o.get("/api/attendance").json()
    me = [r for r in rows if r["day"] == local_day(utcnow()).isoformat()][0]
    assert me["active_seconds"] == 100 and me["extra_seconds"] == 450
    assert me["regular_completed_at"] is not None


def test_overview_reports_recording_and_schedule(org):
    o = org.offroll
    o.post("/api/sessions/start", {"client_id": A, "auto": True})
    r = o.post("/api/recordings/start", {"consent": True, "mime_type": "video/webm"})
    assert r.status_code == 201, r.text
    j = org.admin.get("/api/timer/overview").json()
    row = [x for x in j["rows"] if x["user_id"] == o.id][0]
    assert row["recording"] == "recording"
    assert row["schedule_target_seconds"] == 28800
    assert row["regular_completed"] is False


def test_csv_export_has_the_new_columns(org):
    org.offroll.post("/api/sessions/start", {"client_id": A, "auto": True})
    r = org.admin.get("/api/timer/overview", params={"format": "csv"})
    assert r.status_code == 200
    head = r.text.splitlines()[0]
    assert "Continue today (s)" in head and "8 h done" in head and "Recording now" in head
    assert "Extra total (s)" in head and "Extra start" in head and "Schedule" in head


def test_reports_summary_separates_continue_hours(org, monkeypatch):
    monkeypatch.setattr(settings, "WORKDAY_TARGET_HOURS", 0.01)
    o = org.offroll
    db = _db()
    att = _push_active(db, o.id, 3600)
    att.extra_seconds = 1800
    att.regular_completed_at = utcnow()
    db.commit()
    db.close()
    j = org.admin.get("/api/reports/summary").json()
    row = [r for r in j["rows"] if r["user_id"] == o.id][0]
    assert row["active_hours"] == 1.0 and row["extra_hours"] == 0.5
    assert row["total_hours"] == 1.5 and row["full_days"] == 1


# ---- recording retention --------------------------------------------------------------------------------

def _record_a_video(o):
    r = o.post("/api/recordings/start", {"consent": True, "mime_type": "video/webm"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    blob = b"\x1a\x45\xdf\xa3" + b"x" * 5000            # looks like a WebM file
    h = {**o.h, "Content-Type": "application/octet-stream"}
    c = o.client.post(f"/api/recordings/{rid}/chunk", headers=h, data=blob)
    assert c.status_code == 200, c.text
    s = o.post(f"/api/recordings/{rid}/stop")
    assert s.status_code == 200 and s.json()["status"] == "completed"
    return rid


def test_recording_policy_endpoint(org):
    j = org.offroll.get("/api/recordings/policy").json()
    assert j["retention_days"] == settings.RECORDING_RETENTION_DAYS
    assert j["max_bytes"] == settings.MAX_RECORDING_BYTES
    # build 31: the browser needs the number the promise is made with, including "close me at once"
    assert j["away_grace_seconds"] == settings.RECORDING_AWAY_GRACE_SECONDS


def test_away_grace_is_configurable(org, monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_AWAY_GRACE_SECONDS", 0)
    assert org.offroll.get("/api/recordings/policy").json()["away_grace_seconds"] == 0


def test_started_recording_carries_a_retention_date(org, monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_RETENTION_DAYS", 30)
    o = org.offroll
    rid = _record_a_video(o)
    db = _db()
    rec = db.get(ScreenRecording, rid)
    assert rec.retention_until > rec.ended_at
    db.close()


def test_expired_recordings_are_purged_with_their_chunks(org, monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_RETENTION_DAYS", 1)
    o = org.offroll
    rid = _record_a_video(o)
    db = _db()
    db.get(ScreenRecording, rid).retention_until = utcnow() - timedelta(days=2)
    db.commit()
    assert db.query(models.RecordingChunk).filter_by(recording_id=rid).count() == 1
    db.close()
    rows = o.get("/api/recordings").json()
    assert rid not in [r["id"] for r in rows]
    db = _db()
    assert db.get(ScreenRecording, rid) is None
    assert db.query(models.RecordingChunk).filter_by(recording_id=rid).count() == 0
    db.close()
    assert o.get(f"/api/recordings/{rid}/file").status_code == 404


def test_active_recordings_are_never_purged(org, monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_RETENTION_DAYS", 1)
    o = org.offroll
    r = o.post("/api/recordings/start", {"consent": True, "mime_type": "video/webm"})
    rid = r.json()["id"]
    db = _db()
    db.get(ScreenRecording, rid).retention_until = utcnow() - timedelta(days=2)   # even a weird date
    db.commit()
    db.close()
    o.get("/api/recordings")                                                        # runs the sweep
    db = _db()
    assert db.get(ScreenRecording, rid).status == "recording"                       # while recording: kept
    db.close()
    o.post(f"/api/recordings/{rid}/stop", {"failed": True})


def test_the_report_stops_claiming_a_live_recording_when_the_chunks_stop(org):
    """A browser that was killed, closed or refreshed leaves its recording row saying "recording".
    Only the recordings list repairs those rows, so the Admin timer report must not trust the status
    alone: a red dot must never claim somebody is being filmed while nothing is being uploaded."""
    from app.api.recordings import STALE_SECONDS
    o = org.intern
    rid = o.post("/api/recordings/start", {"consent": True, "mime_type": "video/webm"}).json()["id"]

    def dot():
        rows = org.admin.get("/api/timer/overview").json()["rows"]
        return next(r["recording"] for r in rows if r["user_id"] == o.id)

    assert dot() == "recording"                              # chunks are flowing: the dot is honest
    db = _db()
    rec = db.get(ScreenRecording, rid)
    rec.updated_at = utcnow() - timedelta(seconds=STALE_SECONDS + 60)   # time travel: the tab went away
    db.commit()
    db.close()
    assert dot() is None                                     # no chunks for longer than STALE_SECONDS
    db = _db()
    assert db.get(ScreenRecording, rid).status == "recording"  # the report reads, it never rewrites history
    db.close()
    o.get("/api/recordings")                                 # the owner's list repairs the row
    assert dot() is None                                     # and both screens now agree
    db = _db()
    assert db.get(ScreenRecording, rid).status == "interrupted"
    db.close()

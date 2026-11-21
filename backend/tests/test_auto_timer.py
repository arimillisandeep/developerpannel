"""Automatic timer: the 20 scenarios of the specification, on the server side.
Time is injected (`now=`), so the arithmetic is exact and nothing sleeps."""
from datetime import timedelta

from app.database.connection import SessionLocal
from app.database.models import Attendance, TimerEvent, WorkSession, utcnow
from app.services import timer
from app.services.timer import P_EXTERNAL, P_INACTIVE, P_MANUAL, RUNNING

import pytest

A, B = "tab-aaaaaaaa", "tab-bbbbbbbb"
OPEN = []


@pytest.fixture(autouse=True)
def close_sessions():
    yield
    while OPEN:
        OPEN.pop().close()


class Clock:
    """Drives one session with 15-second reports, like the real tab and extension do."""
    def __init__(self, user_id, minutes_ago=360):
        self.db = SessionLocal()
        OPEN.append(self.db)
        self.t = utcnow() - timedelta(minutes=minutes_ago)
        self.s = timer.start(self.db, user_id, A, now=self.t)
        self.db.commit()

    def tab(self, state, seconds=15, client=A):
        """`seconds` pass, then the tab reports `state` (the elapsed time belongs to the previous mode)."""
        for _ in range(seconds // 15):
            self.t += timedelta(seconds=15)
            timer.heartbeat(self.db, self.s, client, state, now=self.t)
        return self.s.mode

    def ext(self, category, seconds=15, idle=False, domain=None, tab_state="away"):
        for _ in range(seconds // 15):
            self.t += timedelta(seconds=15)
            timer.extension_report(self.db, self.s, category, domain, idle, now=self.t)
            if tab_state:
                timer.heartbeat(self.db, self.s, A, tab_state, now=self.t)
        return self.s.mode

    def events(self):
        self.db.flush()
        return [(e.to_state, e.reason) for e in self.db.query(TimerEvent).filter_by(session_id=self.s.id).order_by(TimerEvent.id)]


def ext_headers(actor):
    token = actor.post("/api/extension/token").json()["token"]
    return {"Authorization": f"Bearer {token}"}


# 1-5 ------------------------------------------------------------------------------------
def test_timer_runs_in_all_five_panels(org):
    for actor in (org.admin, org.dev, org.onroll, org.offroll, org.intern):
        r = actor.post("/api/sessions/start", {"client_id": A, "auto": True}).json()
        assert r["session"]["mode"] == "RUNNING" and r["inactivity_timeout_seconds"] == 300
        hb = actor.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).json()
        assert hb["session"]["mode"] == "RUNNING" and hb["session"]["category"] == "workcode"


# 6-9, 13 --------------------------------------------------------------------------------
def test_approved_sites_run_and_unapproved_sites_pause(admin):
    c = Clock(admin.id)
    assert c.tab("active", 60) == RUNNING
    assert c.ext("approved", 300, domain="meet.google.com") == RUNNING           # 6 Google Meet
    assert c.ext("approved", 300, domain="chatgpt.com") == RUNNING               # 7 ChatGPT
    assert c.s.active_seconds == 660 and c.s.ext_domain == "chatgpt.com"
    assert c.ext("unapproved", 15) == P_EXTERNAL                                 # 9 other site: paused
    before = c.s.active_seconds
    # 13: any amount of "activity" on an unapproved site keeps it paused (the tab is not focused, the extension says unapproved)
    assert c.ext("unapproved", 600, idle=False) == P_EXTERNAL
    assert c.s.active_seconds == before and c.s.away_seconds == 600
    assert c.s.ext_domain is None                                                # the address of unapproved sites is never stored
    assert c.ext("unfocused", 60) == P_EXTERNAL                                  # another program in front
    assert c.tab("active", 15) == RUNNING            # back in the WORKCODE tab with input: resumes even before the extension reports
    assert c.ext("workcode", 15, tab_state="active") == RUNNING
    ev = c.events()
    assert ("PAUSED_EXTERNAL", "unapproved_site") in ev and ev[-1] == ("RUNNING", "activity")


# 10-12 ----------------------------------------------------------------------------------
def test_five_minute_inactivity_pauses_and_activity_resumes(admin):
    c = Clock(admin.id)
    # the tab reports "active" until 5 minutes have passed without input, then "idle" (warning at 4 min is in the browser)
    assert c.tab("active", 300) == RUNNING
    assert c.tab("idle", 15) == P_INACTIVE                                        # 11
    assert c.s.active_seconds == 315                 # the interval before the idle report still counted
    assert c.tab("idle", 600) == P_INACTIVE
    assert (c.s.active_seconds, c.s.idle_seconds) == (315, 600)                   # idle time is not working time
    assert c.tab("active", 15) == RUNNING                                         # 12 input again: resumes
    assert c.s.last_return_at == c.t
    assert c.events() == [("RUNNING", "start"), ("PAUSED_INACTIVE", "inactivity"), ("RUNNING", "activity")]
    # inactivity on an approved site, reported by the extension
    assert c.ext("approved", 30, idle=True, domain="chatgpt.com") == P_INACTIVE
    assert c.ext("approved", 15, idle=False, domain="chatgpt.com") == RUNNING


# 14, 15, 18 -----------------------------------------------------------------------------
def test_manual_pause_and_stop_are_respected(org):
    c = Clock(org.intern.id, minutes_ago=8)     # 435 s of reports follow, so the session is still fresh
    c.tab("active", 60)
    timer.set_paused(c.db, c.s, True, now=c.t)
    assert c.s.mode == P_MANUAL
    assert c.tab("active", 300) == P_MANUAL and c.ext("approved", 60, domain="chatgpt.com") == P_MANUAL   # activity never un-pauses
    assert (c.s.active_seconds, c.s.paused_seconds) == (60, 360)
    timer.set_paused(c.db, c.s, False, now=c.t)
    assert c.tab("active", 15) == RUNNING
    c.db.commit()
    # 15 refresh: starting again returns the same session with its totals
    again = org.intern.post("/api/sessions/start", {"client_id": B, "auto": True}).json()
    assert again["session"]["id"] == c.s.id and again["session"]["active_seconds"] == 75
    # 14 manual stop: the automatic start does not bring it back; the Start button does
    assert org.intern.post("/api/sessions/stop").json()["session"] is None
    auto = org.intern.post("/api/sessions/start", {"client_id": A, "auto": True}).json()
    assert auto["session"] is None and auto["manual_stop"] is True
    assert org.intern.post("/api/sessions/heartbeat", {"client_id": A, "state": "active"}).status_code == 409
    manual = org.intern.post("/api/sessions/start", {"client_id": A}).json()
    assert manual["session"]["mode"] == "RUNNING" and manual["session"]["id"] != c.s.id
    # 18 logout closes the session
    org.intern.post("/api/auth/logout")
    db = SessionLocal(); OPEN.append(db)
    s = db.get(WorkSession, manual["session"]["id"])
    assert (s.state, s.end_reason, s.mode) == ("ended", "logout", "STOPPED")


# 16 -------------------------------------------------------------------------------------
def test_two_tabs_and_the_extension_never_double_count(admin):
    c = Clock(admin.id)
    for _ in range(20):                                   # 5 minutes; three reporters every 15 s
        c.t += timedelta(seconds=15)
        timer.heartbeat(c.db, c.s, A, "active", now=c.t)
        timer.heartbeat(c.db, c.s, B, "away", now=c.t)   # background tab: ignored
        timer.extension_report(c.db, c.s, "workcode", None, False, now=c.t)
    assert c.s.active_seconds == 300 and c.s.away_seconds == 0
    assert c.db.query(WorkSession).filter_by(user_id=admin.id).count() == 1
    assert c.events() == [("RUNNING", "start")]           # no duplicate events either


# 17, 20 ---------------------------------------------------------------------------------
def test_network_loss_and_extension_loss_are_safe(admin):
    c = Clock(admin.id)
    c.tab("active", 60)
    c.t += timedelta(minutes=20)                          # 17 network down for 20 minutes
    timer.heartbeat(c.db, c.s, A, "active", now=c.t)
    assert c.s.active_seconds == 60 + 45                  # only the 45 s cap is credited
    # 20 on ChatGPT, then the extension stops reporting while the tab stays in the background
    assert c.ext("approved", 60, domain="chatgpt.com") == RUNNING
    counted = c.s.active_seconds
    assert c.tab("away", 60) == RUNNING                   # still inside the 75 s freshness window
    assert c.tab("away", 300) == P_EXTERNAL               # extension silent: paused
    assert c.s.active_seconds <= counted + 75             # at most the freshness window was counted
    assert ("PAUSED_EXTERNAL", "extension_lost") in c.events()
    # session expiry
    c.db.commit()
    assert timer.expire_stale(c.db, now=c.t + timedelta(hours=1)) == 1
    assert (c.s.state, c.s.mode, c.s.ended_at) == ("ended", "SESSION_EXPIRED", c.t)


def test_working_time_formula(admin):
    """Active working time = session duration - paused duration, per session and per day."""
    c = Clock(admin.id, minutes_ago=180)
    start = c.t
    c.tab("active", 600); c.tab("idle", 300); c.tab("active", 15); c.ext("unapproved", 150); c.tab("active", 300)
    timer.set_paused(c.db, c.s, True, now=c.t); c.tab("active", 120)
    timer.end(c.db, c.s, "stopped", now=c.t)
    c.db.commit()
    s = c.s
    paused = s.idle_seconds + s.away_seconds + s.paused_seconds
    assert s.active_seconds + paused == int((s.ended_at - start).total_seconds())
    att = c.db.query(Attendance).filter_by(user_id=admin.id).all()
    assert sum(a.active_seconds for a in att) == s.active_seconds
    assert c.events()[-1] == ("STOPPED", "stopped")


# extension API, allowlist, privacy ------------------------------------------------------
def test_allowlist_is_admin_managed_and_enforced_by_the_server(org):
    assert org.intern.post("/api/timer/allowlist", {"domain": "figma.com"}).status_code == 403
    assert org.admin.post("/api/timer/allowlist", {"domain": "not a domain"}).status_code == 422
    meet = org.admin.post("/api/timer/allowlist", {"domain": "https://Meet.Google.com/abc-defg", "label": "Meet", "ignore_inactivity": True})
    assert meet.status_code == 201 and meet.json()["domain"] == "meet.google.com"
    assert org.admin.post("/api/timer/allowlist", {"domain": "meet.google.com"}).status_code == 409
    gpt = org.admin.post("/api/timer/allowlist", {"domain": "chatgpt.com"}).json()
    assert [s["domain"] for s in org.intern.get("/api/timer/allowlist").json()] == ["chatgpt.com", "meet.google.com"]
    assert org.admin.get("/api/audit-logs?action=timer.allowlist.add").json()

    h = ext_headers(org.intern)
    # the extension token is not a login token, and a login token is not an extension token
    assert org.intern.client.get("/api/auth/me", headers=h).status_code == 401
    assert org.intern.client.post("/api/extension/report", headers=org.intern.h, json={"category": "workcode"}).status_code == 401
    cfg = org.intern.client.get("/api/extension/config", headers=h).json()
    assert {"domain": "meet.google.com", "ignore_inactivity": True} in cfg["approved"] and cfg["workcode_hosts"]

    org.intern.post("/api/sessions/start", {"client_id": A})
    org.intern.post("/api/sessions/heartbeat", {"client_id": A, "state": "away"})
    report = lambda **b: org.intern.client.post("/api/extension/report", headers=h, json=b).json()["mode"]
    assert report(category="approved", domain="chatgpt.com") == "RUNNING"                       # 8 approved website
    assert report(category="approved", domain="www.chatgpt.com") == "RUNNING"                   # sub-domain of an approved site
    assert report(category="approved", domain="evil-chatgpt.com") == "PAUSED_EXTERNAL"          # a false claim is downgraded
    assert report(category="approved", domain="chatgpt.com", idle="idle") == "PAUSED_INACTIVE"
    assert report(category="approved", domain="meet.google.com", idle="idle") == "RUNNING"      # listening in a meeting
    assert report(category="approved", domain="meet.google.com", idle="locked") == "PAUSED_INACTIVE"
    assert report(category="unapproved", domain="youtube.com") == "PAUSED_EXTERNAL"
    db = SessionLocal(); OPEN.append(db)
    assert db.query(WorkSession).filter_by(user_id=org.intern.id).one().ext_domain is None      # youtube.com was not stored
    # removing a site takes effect on the next report
    assert org.admin.delete(f"/api/timer/allowlist/{gpt['id']}").status_code == 200
    assert report(category="approved", domain="chatgpt.com") == "PAUSED_EXTERNAL"


# 19 -------------------------------------------------------------------------------------
def test_admin_overview_history_and_csv(org):
    c = Clock(org.intern.id, minutes_ago=25)
    # 600 s active; the idle report arrives 15 s later (still active until then); 300 s idle; then 285 s active
    c.tab("active", 600); c.tab("idle", 300); c.tab("active", 300)
    c.db.commit()
    data = org.admin.get("/api/timer/overview").json()
    row = next(r for r in data["rows"] if r["user_id"] == org.intern.id)
    assert row["active_seconds"] == 900 and row["inactive_seconds"] == 300 and row["paused_seconds"] == 300
    assert row["today_active_seconds"] == 900 and row["role"] == "intern" and row["session_start"]
    assert row["state"] == "NO_SIGNAL"                    # the last report is 5 minutes old; not shown as running
    assert len(data["rows"]) == 7
    assert {r["user_id"] for r in org.admin.get("/api/timer/overview?role=intern").json()["rows"]} == {org.intern.id, org.outsider.id}
    assert {r["user_id"] for r in org.dev.get("/api/timer/overview").json()["rows"]} == {org.dev.id, org.onroll.id, org.offroll.id, org.intern.id}
    assert [r["user_id"] for r in org.offroll.get("/api/timer/overview").json()["rows"]] == [org.offroll.id]
    csv_file = org.admin.get("/api/timer/overview?format=csv")
    assert csv_file.headers["content-type"].startswith("text/csv") and "Intern One" in csv_file.text and "900" in csv_file.text
    yesterday = (utcnow() - timedelta(days=1)).date().isoformat()
    old = org.admin.get(f"/api/timer/overview?start={yesterday}&end={yesterday}").json()
    assert next(r for r in old["rows"] if r["user_id"] == org.intern.id)["active_seconds"] in (0, 900)   # 900 only if the test runs just after local midnight
    hist = org.admin.get(f"/api/timer/sessions?user_id={org.intern.id}&start={yesterday}").json()
    assert [e["to"] for e in hist[0]["events"]] == ["RUNNING", "PAUSED_INACTIVE", "RUNNING"]
    assert hist[0]["events"][1]["reason"] == "inactivity" and hist[0]["paused_seconds"] == 300
    assert org.intern.get(f"/api/timer/sessions?start={yesterday}").json()[0]["id"] == hist[0]["id"]      # own history
    assert org.offroll.get(f"/api/timer/sessions?user_id={org.intern.id}").status_code == 403
    assert org.other_dev.get(f"/api/timer/sessions?user_id={org.intern.id}").status_code == 403

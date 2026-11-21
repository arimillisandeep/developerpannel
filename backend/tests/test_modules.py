"""Meetings, chat, recordings and reports."""
from datetime import datetime, timedelta, timezone

from tests.conftest import assign, work_and_submit

WEBM = b"\x1a\x45\xdf\xa3" + b"0" * 200
SOON = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def test_meetings_permissions_and_visibility(org):
    body = {"title": "Sprint planning", "starts_at": SOON, "link": "https://meet.google.com/abc-defg-hij",
            "participant_ids": [org.intern.id, org.offroll.id]}
    for actor in (org.intern, org.offroll):
        assert actor.post("/api/meetings", body).status_code == 403
    r = org.dev.post("/api/meetings", body)
    assert r.status_code == 201 and len(r.json()["participants"]) == 3
    mid = r.json()["id"]
    # an On-Roll employee cannot invite an admin
    assert org.dev.post("/api/meetings", {**body, "participant_ids": [org.admin.id]}).status_code == 403
    assert org.dev.post("/api/meetings", {**body, "link": "javascript:alert(1)"}).status_code == 422
    assert [m["id"] for m in org.intern.get("/api/meetings").json()] == [mid]
    assert org.outsider.get("/api/meetings").json() == []          # not invited
    assert len(org.admin.get("/api/meetings").json()) == 1          # admin sees all
    assert org.intern.get("/api/notifications").json()["items"][0]["type"] == "meeting_scheduled"
    assert org.intern.delete(f"/api/meetings/{mid}").status_code == 403
    assert org.dev.delete(f"/api/meetings/{mid}").status_code == 200
    assert org.intern.get("/api/meetings").json()[0]["cancelled"] is True   # history is kept


def test_chat_direct_group_announcement_and_privacy(org, client):
    c = org.intern.post("/api/chat/conversations", {"user_ids": [org.dev.id]}).json()
    again = org.dev.post("/api/chat/conversations", {"user_ids": [org.intern.id]}).json()
    assert again["id"] == c["id"]                                    # one direct chat per pair
    with client.websocket_connect(f"/ws?token={org.dev.token}") as ws:
        assert org.intern.post(f"/api/chat/conversations/{c['id']}/messages", {"body": "Hello"}).status_code == 201
        msg = ws.receive_json()
        assert msg["event"] == "chat" and msg["data"]["body"] == "Hello"
    assert org.dev.get("/api/chat/conversations").json()[0]["unread"] == 1
    got = org.dev.get(f"/api/chat/conversations/{c['id']}/messages").json()
    assert [m["body"] for m in got["messages"]] == ["Hello"]
    assert org.dev.get("/api/chat/conversations").json()[0]["unread"] == 0          # reading marks it read
    seen = org.intern.get(f"/api/chat/conversations/{c['id']}/messages").json()
    assert seen["read_by_all_up_to"] == seen["messages"][-1]["id"]                  # read receipt
    # outsiders cannot read or post
    assert org.offroll.get(f"/api/chat/conversations/{c['id']}/messages").status_code == 404
    assert org.offroll.post(f"/api/chat/conversations/{c['id']}/messages", {"body": "x"}).status_code == 404
    assert org.admin.get(f"/api/chat/conversations/{c['id']}/messages").status_code == 404
    # groups and announcements
    group = {"kind": "group", "title": "Alpha", "user_ids": [org.intern.id, org.offroll.id]}
    assert org.intern.post("/api/chat/conversations", group).status_code == 403
    assert org.dev.post("/api/chat/conversations", group).status_code == 201
    assert org.dev.post("/api/chat/conversations", {"kind": "announcement", "title": "All"}).status_code == 403
    ann = org.admin.post("/api/chat/conversations", {"kind": "announcement", "title": "Company news"}).json()
    assert len(ann["members"]) == 7
    assert org.admin.post(f"/api/chat/conversations/{ann['id']}/messages", {"body": "Holiday"}).status_code == 201
    assert org.intern.post(f"/api/chat/conversations/{ann['id']}/messages", {"body": "ok"}).status_code == 403
    assert org.intern.get(f"/api/chat/conversations/{ann['id']}/messages").json()["messages"][0]["body"] == "Holiday"


def test_recording_lifecycle_and_access(org, tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    assert org.intern.post("/api/recordings/start", {"consent": False}).status_code == 422   # consent is mandatory
    rec = org.intern.post("/api/recordings/start", {"consent": True}).json()
    rid = rec["id"]
    assert rec["status"] == "recording"
    up = lambda actor, data: actor.client.post(f"/api/recordings/{rid}/chunk", headers=actor.h, content=data)
    assert up(org.intern, b"not a video").status_code == 422        # file type check
    assert up(org.intern, WEBM).status_code == 200
    assert up(org.intern, b"more").json()["size_bytes"] == len(WEBM) + 4
    assert up(org.offroll, WEBM).status_code == 404                  # cannot write to someone else's recording
    done = org.intern.post(f"/api/recordings/{rid}/stop").json()
    assert done["status"] == "completed"
    assert up(org.intern, WEBM).status_code == 409
    # playback: owner, team developer and admin only
    for actor in (org.intern, org.dev, org.admin):
        r = actor.get(f"/api/recordings/{rid}/file")
        assert r.status_code == 200 and r.content == WEBM + b"more"
    for actor in (org.offroll, org.onroll, org.other_dev, org.outsider):
        assert actor.get(f"/api/recordings/{rid}/file").status_code == 404
        assert actor.get("/api/recordings").json() == []
    assert [x["id"] for x in org.dev.get("/api/recordings").json()] == [rid]
    assert org.admin.get("/api/audit-logs?action=recording.view").json()   # viewing someone else's is audited
    assert not (tmp_path / "recordings").exists()          # build 20: the video is in the database, not in a folder
    # starting again closes a forgotten one; an empty recording is "failed", never "completed"
    r2 = org.intern.post("/api/recordings/start", {"consent": True}).json()
    r3 = org.intern.post("/api/recordings/start", {"consent": True}).json()
    states = {x["id"]: x["status"] for x in org.intern.get("/api/recordings").json()}
    assert states[r2["id"]] == "interrupted" and states[r3["id"]] == "recording"
    assert org.intern.post(f"/api/recordings/{r3['id']}/stop").json()["status"] == "failed"


def test_reports_scope_and_exports(org):
    t = assign(org.admin, org.intern).json()
    _, r = work_and_submit(org.intern, t["id"])
    org.dev.post(f"/api/submissions/{r.json()['id']}/review", {"decision": "approved"})
    org.admin.post(f"/api/submissions/{r.json()['id']}/review", {"decision": "approved"})
    assign(org.admin, org.intern, "Second task")
    rows = org.admin.get("/api/reports/summary").json()["rows"]
    assert len(rows) == 6                                             # everyone except admins
    mine = next(x for x in rows if x["user_id"] == org.intern.id)
    assert (mine["tasks_assigned"], mine["tasks_completed"], mine["completion_percent"], mine["submissions"]) == (2, 1, 50, 1)
    assert {x["user_id"] for x in org.dev.get("/api/reports/summary").json()["rows"]} == {
        org.dev.id, org.onroll.id, org.offroll.id, org.intern.id}
    assert [x["user_id"] for x in org.intern.get("/api/reports/summary").json()["rows"]] == [org.intern.id]
    csv_file = org.admin.get("/api/reports/summary?format=csv")
    assert csv_file.headers["content-type"].startswith("text/csv") and "Intern One" in csv_file.text
    xlsx = org.intern.get("/api/reports/summary?format=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"

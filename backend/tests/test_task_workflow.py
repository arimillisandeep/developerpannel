"""Task assignment, On-Roll review, Admin approval, versions, file history: the 20 scenarios.
`org.dev` is the On-Roll team lead of onroll / offroll / intern; `org.other_dev` leads another team."""
import io
import zipfile
from datetime import timedelta

from app.database.connection import SessionLocal
from app.database.models import Submission, Task, TaskTime, WorkSession, utcnow
from app.services import timer, workflow
from tests.conftest import assign


def ws_id(actor, task_id):
    return actor.get(f"/api/tasks/{task_id}/workspace").json()["id"]


def save(actor, wid, path, content):
    r = actor.put(f"/api/workspaces/{wid}/files", {"path": path, "content": content, "manual": True})
    assert r.status_code == 200, r.text
    return r.json()["file"]


def submit(actor, wid, note=None):
    return actor.post(f"/api/workspaces/{wid}/submit", {"note": note})


def decide(actor, sid, decision, comment=None):
    return actor.post(f"/api/submissions/{sid}/review", {"decision": decision, "comment": comment})


def status(actor, task_id):
    return actor.get(f"/api/tasks/{task_id}").json()["status"]


def actions(actor, task_id):
    return [h["action"] for h in actor.get(f"/api/tasks/{task_id}/history").json()]


def types(actor):
    return [n["type"] for n in actor.get("/api/notifications").json()["items"]]


# 1-6, 17, 18 ------------------------------------------------------------------------------
def test_intern_task_goes_through_onroll_review_and_admin_approval(org):
    t = org.admin.post("/api/tasks", {"title": "Build login page", "assigned_to": org.intern.id, "priority": "high",
                                      "requirements": "Form with validation", "deliverables": "Working page + notes",
                                      "reviewer_id": org.dev.id, "deadline": "2030-01-01"}).json()
    tid = t["id"]
    assert t["code"] == f"WC-{tid:04d}" and t["status"] == "assigned" and t["reviewer_name"] == "Dev One"
    assert "task_assigned" in types(org.intern) and "review_assigned" in types(org.dev)                 # 1
    wid = ws_id(org.intern, tid)
    # nothing can be changed before the task is accepted
    assert org.intern.put(f"/api/workspaces/{wid}/files", {"path": "a.py", "content": "x"}).status_code == 409
    assert org.intern.post(f"/api/tasks/{tid}/start").status_code == 409
    assert org.offroll.post(f"/api/tasks/{tid}/accept").status_code == 403
    assert org.intern.post(f"/api/tasks/{tid}/accept").json()["status"] == "accepted"
    assert org.intern.post(f"/api/tasks/{tid}/accept").status_code == 409
    assert "task_accepted" in types(org.admin)
    assert org.intern.post(f"/api/tasks/{tid}/start").json()["status"] == "in_progress"
    save(org.intern, wid, "login.py", "print('login')\n")
    r = submit(org.intern, wid, "first version")                                                          # 2
    assert r.status_code == 201 and r.json()["version"] == "1.0" and r.json()["stage"] == "onroll_review"
    sid = r.json()["id"]
    assert status(org.intern, tid) == "under_onroll_review"
    # files are locked while it is under review; a second submission is impossible
    assert org.intern.put(f"/api/workspaces/{wid}/files", {"path": "login.py", "content": "changed"}).status_code == 409
    assert submit(org.intern, wid).status_code == 409
    # 3: the named On-Roll reviewer has it in the queue; another On-Roll does not
    assert [s["id"] for s in org.dev.get("/api/submissions").json()] == [sid]
    assert org.onroll.get("/api/submissions").json() == [] and org.admin.get("/api/submissions").json() == []
    assert "task_submitted" in types(org.dev)
    sub = org.dev.get(f"/api/submissions/{sid}").json()
    assert sub["note"] == "first version" and sub["can_review"] and sub["task_deliverables"] == "Working page + notes"
    assert {f["path"] for f in sub["files"]} == {"README.md", "login.py"}
    # 15: nobody else can decide at this stage
    for actor in (org.admin, org.onroll, org.other_dev, org.intern, org.offroll):
        assert decide(actor, sid, "approved").status_code == 403, actor.user["full_name"]
    r = decide(org.dev, sid, "approved", "clean code")                                                    # 4
    assert r.status_code == 200 and r.json()["stage"] == "admin_review"
    assert status(org.intern, tid) == "under_admin_review"
    assert decide(org.dev, sid, "approved").status_code == 403           # On-Roll approval is never final
    assert [s["id"] for s in org.admin.get("/api/submissions").json()] == [sid]                           # 5
    assert "admin_pending" in types(org.admin) and "review_approved" in types(org.intern)
    r = decide(org.admin, sid, "approved", "good")                                                        # 6
    assert r.json()["status"] == "approved" and r.json()["decided_at"]
    task = org.intern.get(f"/api/tasks/{tid}").json()
    assert task["status"] == "completed" and task["completed_at"] and task["accepted_at"] and task["started_at"]
    assert "admin_approved" in types(org.intern)
    assert decide(org.admin, sid, "rejected", "late").status_code == 409  # already decided
    # 17: the history has every step, in order, with who and which version
    hist = org.admin.get(f"/api/tasks/{tid}/history").json()
    assert [h["action"] for h in hist] == [
        "created", "assigned", "accepted", "work_started", "submitted", "version_created", "sent_to_onroll_review",
        "onroll_approved", "sent_to_admin_review", "admin_approved", "completed"]
    assert [h["to_status"] for h in hist][-4:] == ["onroll_approved", "under_admin_review", "admin_approved", "completed"]
    approved = next(h for h in hist if h["action"] == "onroll_approved")
    assert (approved["user"], approved["user_role"], approved["comment"], approved["version"], approved["from_status"]) == (
        "Dev One", "onroll", "clean code", "1.0", "under_onroll_review")
    # there is no way to edit or delete history through the API
    assert org.admin.delete(f"/api/tasks/{tid}/history").status_code == 405
    assert org.admin.patch(f"/api/tasks/{tid}/history", {}).status_code == 405
    # only the assignee, assigner, reviewer, team lead and admins see the task
    assert org.outsider.get(f"/api/tasks/{tid}").status_code == 403
    assert org.other_dev.get(f"/api/tasks/{tid}/history").status_code == 403
    # a completed task cannot be changed by status edits
    assert org.admin.patch(f"/api/tasks/{tid}", {"title": "other title"}).status_code == 409
    assert org.intern.patch(f"/api/tasks/{tid}", {"status": "completed"}).status_code == 403


# 7, 8, 11, 12, 13, 14 ---------------------------------------------------------------------
def test_reject_rework_resubmit_keeps_every_version(org):
    tid = assign(org.admin, org.intern).json()["id"]
    org.intern.post(f"/api/tasks/{tid}/accept")
    wid = ws_id(org.intern, tid)
    save(org.intern, wid, "app.py", "a = 1\nprint(a)\n")
    save(org.intern, wid, "old.py", "legacy\n")
    v1 = submit(org.intern, wid, "v1").json()
    assert decide(org.dev, v1["id"], "rejected").status_code == 422                # 7: a reason is required
    assert decide(org.dev, v1["id"], "rejected", "does not run").status_code == 200
    assert status(org.intern, tid) == "onroll_rejected"
    assert types(org.intern)[0] == "rejected"
    # 8: the intern corrects and resubmits
    assert submit(org.intern, wid).status_code == 409 and "Nothing changed" in submit(org.intern, wid).text
    save(org.intern, wid, "app.py", "a = 2\nprint(a)\nprint('fixed')\n")
    save(org.intern, wid, "util.py", "def helper():\n    return 1\n")
    old = next(f for f in org.intern.get(f"/api/tasks/{tid}/workspace").json()["files"] if f["path"] == "old.py")
    org.intern.delete(f"/api/workspaces/{wid}/files/{old['id']}")
    v2 = submit(org.intern, wid, "fixed the crash").json()
    assert v2["version"] == "1.1" and v2["stage"] == "onroll_review"
    assert status(org.intern, tid) == "under_onroll_review"
    assert "task_resubmitted" in types(org.dev)
    assert decide(org.dev, v2["id"], "approved").status_code == 200
    # 11: admin asks for rework; it goes through On-Roll review again
    assert decide(org.admin, v2["id"], "changes_requested").status_code == 422
    assert decide(org.admin, v2["id"], "changes_requested", "add tests").status_code == 200
    assert status(org.intern, tid) == "rework_required"
    save(org.intern, wid, "test_app.py", "assert True\n")
    v3 = submit(org.intern, wid).json()
    assert v3["version"] == "1.2" and v3["stage"] == "onroll_review"
    # admin rejects
    decide(org.dev, v3["id"], "approved")
    assert decide(org.admin, v3["id"], "rejected", "wrong approach").status_code == 200
    assert status(org.intern, tid) == "admin_rejected"
    # 12: all versions are still there, unchanged
    versions = org.intern.get(f"/api/tasks/{tid}/versions").json()
    assert [(v["version"], v["status"]) for v in versions] == [("1.2", "rejected"), ("1.1", "changes_requested"), ("1.0", "rejected")]
    assert versions[1]["note"] == "fixed the crash" and versions[1]["submitter_role"] == "intern"
    assert versions[1]["changes"] == {"added": ["util.py"], "deleted": ["old.py"], "modified": ["app.py"]}
    assert versions[1]["authors"]["app.py"]["name"] == "Intern One"
    first = org.intern.get(f"/api/submissions/{v1['id']}").json()
    assert {f["path"]: f["content"] for f in first["files"]}["app.py"] == "a = 1\nprint(a)\n"
    # 14: review comments of every round are still available
    assert [(r["stage"], r["decision"], r["comment"]) for r in first["reviews"]] == [("onroll_review", "rejected", "does not run")]
    second = org.admin.get(f"/api/submissions/{v2['id']}").json()
    assert [r["comment"] for r in second["reviews"]] == [None, "add tests"]
    # 13: comparison shows the real differences
    cmp = org.dev.get(f"/api/tasks/{tid}/compare?a={v1['id']}&b={v2['id']}").json()
    by = {f["path"]: f for f in cmp["files"]}
    assert {p: f["status"] for p, f in by.items()} == {"app.py": "modified", "old.py": "deleted", "util.py": "added"}
    assert (by["app.py"]["lines_added"], by["app.py"]["lines_removed"]) == (2, 1)
    assert "-a = 1" in by["app.py"]["diff"] and "+a = 2" in by["app.py"]["diff"] and "+print('fixed')" in by["app.py"]["diff"]
    assert cmp["summary"] == {"added": 1, "modified": 1, "deleted": 1} and cmp["unchanged"] == 1
    assert org.dev.get(f"/api/tasks/{tid}/compare?a={v1['id']}&b=9999").status_code == 404
    # download exactly one version
    z = zipfile.ZipFile(io.BytesIO(org.dev.get(f"/api/submissions/{v1['id']}/download").content))
    assert sorted(z.namelist()) == ["README.md", "app.py", "old.py"] and z.read("app.py") == b"a = 1\nprint(a)\n"
    # restore: only the assignee, only while editable; the old version itself stays as it was
    assert org.dev.post(f"/api/submissions/{v1['id']}/restore").status_code == 403
    assert org.intern.post(f"/api/submissions/{v1['id']}/restore").json()["files"] == 3
    now = {f["path"]: f["content"] for f in org.intern.get(f"/api/tasks/{tid}/workspace").json()["files"]}
    assert now == {f["path"]: f["content"] for f in first["files"]}
    assert "version_restored" in actions(org.intern, tid)
    # a stored version cannot be changed in the database layer either
    db = SessionLocal()
    try:
        s = db.get(Submission, v1["id"])
        s.snapshot = [{"path": "hack.py", "content": "x"}]
        try:
            db.commit()
            raise AssertionError("snapshot was overwritten")
        except ValueError as e:
            assert "immutable" in str(e)
    finally:
        db.rollback(); db.close()


# 9 ----------------------------------------------------------------------------------------
def test_offroll_follows_the_same_two_step_review(org):
    tid = assign(org.admin, org.offroll).json()["id"]
    org.offroll.post(f"/api/tasks/{tid}/accept")
    wid = ws_id(org.offroll, tid)
    save(org.offroll, wid, "main.py", "print(1)")
    v = submit(org.offroll, wid).json()
    assert v["stage"] == "onroll_review"
    assert decide(org.admin, v["id"], "approved").status_code == 403          # admin cannot skip the On-Roll review
    # no reviewer named on the task: the On-Roll lead of the team reviews, not an On-Roll outside the team
    assert decide(org.other_dev, v["id"], "approved").status_code == 403
    assert decide(org.onroll, v["id"], "approved").status_code == 403
    assert decide(org.dev, v["id"], "approved").json()["stage"] == "admin_review"
    assert decide(org.admin, v["id"], "approved").json()["status"] == "approved"
    assert status(org.offroll, tid) == "completed"


# 10 ---------------------------------------------------------------------------------------
def test_onroll_own_task_goes_directly_to_admin_and_no_self_approval(org):
    tid = assign(org.admin, org.onroll).json()["id"]
    org.onroll.post(f"/api/tasks/{tid}/accept")
    wid = ws_id(org.onroll, tid)
    save(org.onroll, wid, "main.py", "print(1)")
    v = submit(org.onroll, wid).json()
    assert v["stage"] == "admin_review" and status(org.onroll, tid) == "under_admin_review"
    assert decide(org.onroll, v["id"], "approved").status_code == 403         # own work
    assert decide(org.dev, v["id"], "approved").status_code == 403            # On-Roll cannot give final approval
    assert decide(org.admin, v["id"], "changes_requested", "more").status_code == 200
    save(org.onroll, wid, "main.py", "print(2)")
    v2 = submit(org.onroll, wid).json()
    assert v2["version"] == "1.1" and v2["stage"] == "admin_review"
    assert decide(org.admin, v2["id"], "approved").status_code == 200
    assert actions(org.admin, tid)[-6:] == ["admin_rework_requested", "resubmitted", "version_created", "sent_to_admin_review", "admin_approved", "completed"]
    # an On-Roll reviewer who is also the assignee can never be the reviewer of that task
    r = org.admin.post("/api/tasks", {"title": "Self review", "assigned_to": org.onroll.id, "reviewer_id": org.onroll.id})
    assert r.status_code == 422
    assert org.admin.post("/api/tasks", {"title": "Bad reviewer", "assigned_to": org.intern.id, "reviewer_id": org.offroll.id}).status_code == 422
    # major revision: admin reopens a completed task; the next version is 2.0
    assert org.dev.post(f"/api/tasks/{tid}/reopen", {"comment": "x"}).status_code == 403
    assert org.admin.post(f"/api/tasks/{tid}/reopen", {"comment": "new requirement"}).json()["status"] == "rework_required"
    save(org.onroll, wid, "main.py", "print(3)")
    assert submit(org.onroll, wid).json()["version"] == "2.0"


# 16 ---------------------------------------------------------------------------------------
def test_users_cannot_reach_other_users_projects(org):
    tid = assign(org.admin, org.intern).json()["id"]
    org.intern.post(f"/api/tasks/{tid}/accept")
    wid = ws_id(org.intern, tid)
    f = save(org.intern, wid, "secret.py", "token = 1")
    v = submit(org.intern, wid).json()
    for other in (org.offroll, org.outsider, org.onroll, org.other_dev):
        assert other.get(f"/api/tasks/{tid}/workspace").status_code == 403
        assert other.put(f"/api/workspaces/{wid}/files", {"path": "x.py", "content": "x"}).status_code == 403
        assert other.get(f"/api/workspaces/{wid}/history").status_code == 403
        assert other.get(f"/api/workspaces/{wid}/files/{f['id']}/versions").status_code == 403
        assert other.get(f"/api/submissions/{v['id']}").status_code == 403
        assert other.get(f"/api/submissions/{v['id']}/download").status_code == 403
        assert other.get(f"/api/tasks/{tid}/versions").status_code == 403
        assert other.get(f"/api/tasks/{tid}/compare?a={v['id']}&b={v['id']}").status_code == 403
    # the reviewer reads, but can never write into the employee's workspace
    assert org.dev.get(f"/api/submissions/{v['id']}").status_code == 200
    assert org.dev.put(f"/api/workspaces/{wid}/files", {"path": "x.py", "content": "x"}).status_code == 403
    assert org.admin.put(f"/api/workspaces/{wid}/files", {"path": "x.py", "content": "x"}).status_code == 403


# file-level change tracking ---------------------------------------------------------------
def test_file_history_records_every_kind_of_change(org):
    tid = assign(org.admin, org.intern).json()["id"]
    org.intern.post(f"/api/tasks/{tid}/accept")
    wid = ws_id(org.intern, tid)
    f = save(org.intern, wid, "a.py", "one\n")
    save(org.intern, wid, "a.py", "one\ntwo\n")
    org.intern.post(f"/api/workspaces/{wid}/files/{f['id']}/rename", {"new_path": "b.py"})
    versions = org.intern.get(f"/api/workspaces/{wid}/files/{f['id']}/versions").json()
    assert versions[0]["saved_by_name"] == "Intern One"
    org.intern.post(f"/api/workspaces/{wid}/files/{f['id']}/versions/{versions[-1]['id']}/restore")
    g = save(org.intern, wid, "tmp.py", "x")
    org.intern.delete(f"/api/workspaces/{wid}/files/{g['id']}")
    submit(org.intern, wid)
    log = org.intern.get(f"/api/workspaces/{wid}/history").json()
    mine = [(e["action"], e["path"]) for e in reversed(log) if e["file_id"] == f["id"]]
    assert mine == [("created", "a.py"), ("edited", "a.py"), ("renamed", "b.py"), ("restored", "b.py"), ("submitted", "b.py")]
    edit = next(e for e in log if e["action"] == "edited" and e["file_id"] == f["id"])
    assert (edit["previous_version"], edit["new_version"], edit["summary"], edit["modified_by_name"]) == (1, 2, "+1 -0 lines", "Intern One")
    assert next(e for e in log if e["action"] == "renamed")["from_path"] == "a.py"
    assert ("deleted", "tmp.py") in [(e["action"], e["path"]) for e in log]
    assert next(e for e in log if e["action"] == "submitted")["submission_version"] == "1.0"
    assert [e["action"] for e in org.intern.get(f"/api/workspaces/{wid}/history?path=tmp.py").json()] == ["deleted", "created"]
    assert org.dev.get(f"/api/workspaces/{wid}/history").status_code == 200       # team lead may read


# admin task management --------------------------------------------------------------------
def test_admin_assigns_to_several_people_reassigns_cancels_archives(org):
    r = org.admin.post("/api/tasks", {"title": "Same task for three", "assigned_to_ids": [org.intern.id, org.offroll.id, org.onroll.id]})
    assert r.status_code == 201
    made = r.json()["created"]
    assert len(made) == 3 and len({m["code"] for m in made}) == 3
    one = org.intern.get(f"/api/tasks/{made[0]['id']}").json()
    assert one["group_code"] and [g["id"] for g in one["group"]] == [made[0]["id"]]      # others' copies are not visible
    assert len(org.admin.get(f"/api/tasks/{made[0]['id']}").json()["group"]) == 3
    assert org.admin.post("/api/tasks", {"title": "Nobody chosen"}).status_code == 422
    for actor in (org.intern, org.offroll):
        assert actor.post("/api/tasks", {"title": "Not allowed", "assigned_to": org.intern.id}).status_code == 403
    # reassign before submission
    tid = made[0]["id"]
    org.intern.post(f"/api/tasks/{tid}/accept")
    r = org.admin.patch(f"/api/tasks/{tid}", {"assigned_to": org.outsider.id, "reviewer_id": org.other_dev.id})
    assert r.json()["status"] == "assigned" and r.json()["assigned_to"] == org.outsider.id
    assert org.intern.get(f"/api/tasks/{tid}").status_code == 403
    assert "reassigned" in actions(org.admin, tid)
    # cancel needs a reason; archive only when completed or cancelled; only admin
    assert org.admin.post(f"/api/tasks/{tid}/archive").status_code == 409
    assert org.admin.post(f"/api/tasks/{tid}/cancel", {}).status_code == 422
    assert org.outsider.post(f"/api/tasks/{tid}/cancel", {"comment": "no"}).status_code == 403
    assert org.admin.post(f"/api/tasks/{tid}/cancel", {"comment": "not needed"}).json()["status"] == "cancelled"
    assert org.outsider.post(f"/api/tasks/{tid}/accept").status_code == 409
    assert org.other_dev.post(f"/api/tasks/{tid}/archive").status_code == 403
    assert org.admin.post(f"/api/tasks/{tid}/archive").json()["status"] == "archived"
    assert tid not in [t["id"] for t in org.admin.get("/api/tasks").json()]
    assert tid in [t["id"] for t in org.admin.get("/api/tasks?archived=true").json()]
    assert actions(org.admin, tid)[-2:] == ["cancelled", "archived"]
    # delete = hide; a task with submissions keeps all its data
    t2 = made[1]["id"]
    org.offroll.post(f"/api/tasks/{t2}/accept")
    wid = ws_id(org.offroll, t2)
    save(org.offroll, wid, "m.py", "1")
    sid = submit(org.offroll, wid).json()["id"]
    assert org.admin.delete(f"/api/tasks/{t2}").status_code == 409       # under review
    decide(org.dev, sid, "rejected", "no")
    assert org.admin.delete(f"/api/tasks/{t2}").status_code == 200
    db = SessionLocal()
    try:
        assert db.get(Task, t2).deleted_at is not None and db.get(Submission, sid).snapshot
    finally:
        db.close()


def test_attachments_are_checked_and_private(org):
    tid = assign(org.admin, org.intern).json()["id"]
    up = lambda actor, name, data=b"hello": actor.client.post(f"/api/tasks/{tid}/attachments", headers=actor.h,
                                                             files={"file": (name, data, "text/plain")})
    ref = up(org.admin, "../../etc/spec v1.txt")
    assert ref.status_code == 201 and ref.json()["kind"] == "reference" and ref.json()["filename"] == "spec v1.txt"
    assert up(org.admin, "virus.exe").status_code == 422
    assert up(org.admin, "empty.txt", b"").status_code == 422
    assert up(org.admin, "big.bin", b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert up(org.outsider, "x.txt").status_code == 403
    assert up(org.intern, "early.txt").status_code == 409                 # not accepted yet
    org.intern.post(f"/api/tasks/{tid}/accept")
    mine = up(org.intern, "notes.txt", b"my notes")
    assert mine.json()["kind"] == "deliverable"
    got = org.intern.get(f"/api/tasks/{tid}/attachments/{ref.json()['id']}")
    assert got.content == b"hello" and "attachment" in got.headers["content-disposition"] and got.headers["x-content-type-options"] == "nosniff"
    assert org.outsider.get(f"/api/tasks/{tid}/attachments/{ref.json()['id']}").status_code == 403
    assert org.intern.delete(f"/api/tasks/{tid}/attachments/{ref.json()['id']}").status_code == 403
    wid = ws_id(org.intern, tid)
    save(org.intern, wid, "m.py", "1")
    sid = submit(org.intern, wid).json()["id"]
    # the deliverable is now part of version 1.0 and cannot be removed
    assert org.intern.delete(f"/api/tasks/{tid}/attachments/{mine.json()['id']}").status_code == 409
    files = org.dev.get(f"/api/submissions/{sid}").json()["attachments"]
    assert [(a["filename"], a["kind"], a["submission_id"]) for a in files] == [("spec v1.txt", "reference", None), ("notes.txt", "deliverable", sid)]
    assert org.dev.get(f"/api/tasks/{tid}/attachments/{mine.json()['id']}").content == b"my notes"


# 18 ---------------------------------------------------------------------------------------
def test_deadline_reminders_once_per_day(org):
    today = utcnow().date()
    due = org.admin.post("/api/tasks", {"title": "Due soon", "assigned_to": org.intern.id, "deadline": str(today + timedelta(days=1))}).json()
    org.admin.post("/api/tasks", {"title": "Far away", "assigned_to": org.intern.id, "deadline": str(today + timedelta(days=30))})
    db = SessionLocal()
    try:
        assert workflow.send_deadline_reminders(db, force=True) == 1
        db.commit()
        assert workflow.send_deadline_reminders(db, force=True) == 0      # not twice on the same day
        db.commit()
    finally:
        db.close()
    notes = [n for n in org.intern.get("/api/notifications").json()["items"] if n["type"] == "task_deadline"]
    assert len(notes) == 1 and due["code"] in notes[0]["title"]


# 19 ---------------------------------------------------------------------------------------
def test_timer_books_time_on_the_open_task(org):
    tid = assign(org.admin, org.intern).json()["id"]
    other = assign(org.admin, org.offroll).json()["id"]
    org.intern.post(f"/api/tasks/{tid}/accept")
    org.intern.post("/api/sessions/start", {"client_id": "tab-aaaaaaaa"})
    hb = lambda task: org.intern.post("/api/sessions/heartbeat", {"client_id": "tab-aaaaaaaa", "state": "active", "task_id": task})
    assert hb(tid).json()["session"]["mode"] == "RUNNING"
    db = SessionLocal()
    try:
        s = db.query(WorkSession).filter_by(user_id=org.intern.id).one()
        assert s.task_id == tid
        t0 = s.last_heartbeat_at
        for i in range(1, 5):                                           # 60 s working on the task
            timer.heartbeat(db, s, "tab-aaaaaaaa", "active", now=t0 + timedelta(seconds=15 * i), task_id=tid)
        for i in range(5, 9):                                           # 60 s inactive
            timer.heartbeat(db, s, "tab-aaaaaaaa", "idle", now=t0 + timedelta(seconds=15 * i), task_id=tid)
        for i in range(9, 13):                                          # 60 s on another page: not booked on the task
            timer.heartbeat(db, s, "tab-aaaaaaaa", "active", now=t0 + timedelta(seconds=15 * i), task_id=None)
        db.commit()
        row = db.query(TaskTime).filter_by(task_id=tid, user_id=org.intern.id).one()
        assert (row.active_seconds, row.paused_seconds) == (75, 60)     # the idle report arrives one interval late
        assert s.active_seconds >= 120                                   # the day total still counts everything
    finally:
        db.close()
    t = org.admin.get(f"/api/tasks/{tid}").json()["time"]
    assert t["active_seconds"] == 75 and t["paused_seconds"] == 60 and t["total_seconds"] == 135
    # someone else's task is never booked
    hb(other)
    db = SessionLocal()
    try:
        assert db.query(WorkSession).filter_by(user_id=org.intern.id).one().task_id is None
    finally:
        db.close()

"""The ten critical permission tests from the specification, plus workflow details."""
from tests.conftest import Actor, assign, work_and_submit


# 1 + 2
def test_intern_and_offroll_cannot_assign_tasks(org):
    for actor in (org.intern, org.offroll):
        assert assign(actor, org.onroll).status_code == 403
        assert assign(actor, org.intern).status_code == 403
        assert actor.get("/api/users/assignable").json() == []


# 3
def test_onroll_can_assign_to_onroll_offroll_intern_only(org, make_user):
    peer = make_user("onroll", "Onroll Two")
    for target in (peer, org.offroll, org.intern):
        assert assign(org.onroll, target).status_code == 201
    assert assign(org.onroll, org.admin).status_code == 403


# 4
def test_developer_role_is_retired(org, admin):
    r = admin.post("/api/users", {"email": "d@wc.test", "password": "Passw0rd!123", "full_name": "Dev Three", "role": "developer"})
    assert r.status_code == 422 and "retired" in r.text
    assert admin.post(f"/api/users/{org.onroll.id}/convert", {"to_role": "developer", "confirm_early": True}).status_code == 422
    assert assign(org.dev, org.admin).status_code == 403


# 5
def test_admin_has_full_access(org):
    for target in (org.dev, org.onroll, org.offroll, org.intern):
        assert assign(org.admin, target).status_code == 201
    assert len(org.admin.get("/api/tasks").json()) == 4
    assert org.admin.get("/api/users").status_code == 200
    assert org.admin.get("/api/dashboard/admin").status_code == 200
    assert org.admin.get("/api/audit-logs").status_code == 200


# 6
def test_onroll_submission_goes_directly_to_admin(org):
    task = assign(org.admin, org.onroll).json()
    _, r = work_and_submit(org.onroll, task["id"])
    assert r.status_code == 201 and r.json()["stage"] == "admin_review"
    sid = r.json()["id"]
    assert [s["id"] for s in org.admin.get("/api/submissions?view=queue").json()] == [sid]
    assert org.dev.get("/api/submissions?view=queue").json() == []
    assert org.dev.post(f"/api/submissions/{sid}/review", {"decision": "approved"}).status_code == 403
    r = org.admin.post(f"/api/submissions/{sid}/review", {"decision": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert org.onroll.get(f"/api/tasks/{task['id']}").json()["status"] == "completed"


# 7
def test_offroll_and_intern_submissions_go_to_developer_first(org):
    for worker in (org.offroll, org.intern):
        task = assign(org.onroll, worker).json()
        _, r = work_and_submit(worker, task["id"])
        assert r.status_code == 201 and r.json()["stage"] == "onroll_review"
        sid = r.json()["id"]
        assert sid in [s["id"] for s in org.dev.get("/api/submissions?view=queue").json()]
        assert sid not in [s["id"] for s in org.admin.get("/api/submissions?view=queue").json()]
        # admin cannot skip the developer stage
        assert org.admin.post(f"/api/submissions/{sid}/review", {"decision": "approved"}).status_code == 403
        # developer approval is not final: it moves to admin
        r = org.dev.post(f"/api/submissions/{sid}/review", {"decision": "approved"})
        assert r.json()["stage"] == "admin_review"
        assert worker.get(f"/api/tasks/{task['id']}").json()["status"] == "under_admin_review"
        assert org.dev.post(f"/api/submissions/{sid}/review", {"decision": "approved"}).status_code == 403
        r = org.admin.post(f"/api/submissions/{sid}/review", {"decision": "approved"})
        assert r.json()["status"] == "approved"
        assert worker.get(f"/api/tasks/{task['id']}").json()["status"] == "completed"
        stages = [(x["stage"], x["decision"]) for x in r.json()["reviews"]]
        assert stages == [("onroll_review", "approved"), ("admin_review", "approved")]


# 8
def test_only_authorised_reviewers_can_approve(org):
    task = assign(org.admin, org.intern).json()
    _, r = work_and_submit(org.intern, task["id"])
    sid = r.json()["id"]
    for actor in (org.intern, org.offroll, org.onroll, org.other_dev, org.outsider):
        assert actor.post(f"/api/submissions/{sid}/review", {"decision": "approved"}).status_code == 403
    # people outside the review chain cannot even read the code
    for actor in (org.offroll, org.onroll, org.other_dev, org.outsider):
        assert actor.get(f"/api/submissions/{sid}").status_code == 403
    assert org.dev.post(f"/api/submissions/{sid}/review", {"decision": "approved"}).status_code == 200


# 9
def test_private_workspace_is_not_accessible_to_other_employees(org):
    task = assign(org.admin, org.offroll).json()
    wid = org.offroll.get(f"/api/tasks/{task['id']}/workspace").json()["id"]
    org.offroll.put(f"/api/workspaces/{wid}/files", {"path": "secret.py", "content": "x=1"})
    for actor in (org.intern, org.onroll, org.other_dev, org.outsider):
        assert actor.get(f"/api/tasks/{task['id']}/workspace").status_code == 403
        assert actor.put(f"/api/workspaces/{wid}/files", {"path": "a.py", "content": "hack"}).status_code == 403
        assert actor.post(f"/api/workspaces/{wid}/submit").status_code == 403
    # reviewers may read but never write
    for actor in (org.dev, org.admin):
        assert actor.get(f"/api/tasks/{task['id']}/workspace").json()["read_only"] is True
        assert actor.put(f"/api/workspaces/{wid}/files", {"path": "a.py", "content": "x"}).status_code == 403


# 10
def test_role_change_keeps_all_history(org):
    task = assign(org.admin, org.intern).json()
    wid, r = work_and_submit(org.intern, task["id"])
    sid = r.json()["id"]
    r = org.admin.post(f"/api/users/{org.intern.id}/convert",
                       {"to_role": "onroll", "reason": "great work", "confirm_early": True})
    assert r.status_code == 200 and r.json()["role"] == "onroll"
    assert r.json()["employee_code"] == org.intern.user["employee_code"]  # same identity
    me = Actor(org.intern.client, org.intern.user["email"])
    assert me.user["role"] == "onroll"
    assert [t["id"] for t in me.get("/api/tasks?scope=mine").json()] == [task["id"]]
    assert me.get(f"/api/tasks/{task['id']}/workspace").json()["id"] == wid
    sub = me.get(f"/api/submissions/{sid}").json()
    assert sub["submitter_role"] == "intern" and sub["stage"] == "onroll_review"
    hist = org.admin.get(f"/api/users/{me.id}/history").json()
    assert [(h["event"], h["from_role"], h["to_role"]) for h in hist] == [
        ("joined", None, "intern"), ("converted", "intern", "onroll")]
    # now on-roll: may assign tasks, and new submissions go straight to admin
    assert assign(me, org.offroll).status_code == 201
    t2 = assign(org.admin, me, "Second").json()
    _, r = work_and_submit(me, t2["id"])
    assert r.json()["stage"] == "admin_review"


def test_changes_requested_returns_to_employee_and_resubmit_creates_new_version(org):
    task = assign(org.dev, org.intern).json()
    wid, r = work_and_submit(org.intern, task["id"])
    sid = r.json()["id"]
    # locked while under review
    assert org.intern.put(f"/api/workspaces/{wid}/files", {"path": "main.py", "content": "x"}).status_code == 409
    assert org.intern.post(f"/api/workspaces/{wid}/submit").status_code == 409
    # comment is mandatory
    assert org.dev.post(f"/api/submissions/{sid}/review", {"decision": "changes_requested"}).status_code == 422
    r = org.dev.post(f"/api/submissions/{sid}/review", {"decision": "changes_requested", "comment": "fix bug"})
    assert r.status_code == 200
    assert org.intern.get(f"/api/tasks/{task['id']}").json()["status"] == "rework_required"
    notes = org.intern.get("/api/notifications").json()
    assert notes["unread"] >= 2 and notes["items"][0]["type"] == "changes_requested"
    wid, r = work_and_submit(org.intern, task["id"], "print('fixed')")
    assert r.status_code == 201 and r.json()["version_no"] == 2
    sid2 = r.json()["id"]
    org.dev.post(f"/api/submissions/{sid2}/review", {"decision": "approved"})
    # admin sends it back too
    r = org.admin.post(f"/api/submissions/{sid2}/review", {"decision": "changes_requested", "comment": "tests"})
    assert r.status_code == 200
    assert org.intern.get(f"/api/tasks/{task['id']}").json()["status"] == "rework_required"
    _, r = work_and_submit(org.intern, task["id"], "print('final')")
    assert r.json()["version_no"] == 3 and r.json()["stage"] == "onroll_review"
    # the first frozen snapshot is unchanged
    first = org.intern.get(f"/api/submissions/{sid}").json()
    assert {"path": "main.py", "content": "print('hi')"} in first["files"]


def test_submission_without_team_can_be_reviewed_by_any_onroll(admin, make_user):
    dev = make_user("onroll", "Solo Lead")
    intern = make_user("intern", "Teamless")
    task = assign(admin, intern).json()
    _, r = work_and_submit(intern, task["id"])
    assert dev.post(f"/api/submissions/{r.json()['id']}/review", {"decision": "approved"}).status_code == 200


def test_task_visibility(org):
    t = assign(org.admin, org.offroll).json()
    assert org.intern.get(f"/api/tasks/{t['id']}").status_code == 403
    assert org.other_dev.get(f"/api/tasks/{t['id']}").status_code == 403
    assert org.dev.get(f"/api/tasks/{t['id']}").status_code == 200
    assert org.intern.get("/api/tasks").json() == []
    assert org.offroll.patch(f"/api/tasks/{t['id']}", {"title": "easier task"}).status_code == 403


def test_file_versions_restore_and_validation(org):
    task = assign(org.admin, org.onroll).json()
    org.onroll.post(f"/api/tasks/{task['id']}/accept")
    wid = org.onroll.get(f"/api/tasks/{task['id']}/workspace").json()["id"]
    save = lambda c, manual=True: org.onroll.put(f"/api/workspaces/{wid}/files",
                                                 {"path": "src/app.js", "content": c, "manual": manual})
    fid = save("v1").json()["file"]["id"]
    save("v2")
    save("v3-auto", manual=False)
    save("v3-auto-b", manual=False)  # folded into the same auto version
    vers = org.onroll.get(f"/api/workspaces/{wid}/files/{fid}/versions").json()
    assert [v["content"] for v in vers] == ["v3-auto-b", "v2", "v1"]
    r = org.onroll.post(f"/api/workspaces/{wid}/files/{fid}/versions/{vers[-1]['id']}/restore")
    assert r.json()["content"] == "v1"
    assert org.onroll.get(f"/api/tasks/{task['id']}").json()["status"] == "in_progress"
    for bad in ("../etc/passwd", "/abs.py", "a/../../b", "x;rm.py"):
        r = org.onroll.put(f"/api/workspaces/{wid}/files", {"path": bad, "content": "x"})
        assert r.status_code == 422, bad
    big = org.onroll.put(f"/api/workspaces/{wid}/files", {"path": "big.txt", "content": "a" * 1_000_001})
    assert big.status_code == 413
    # delete + empty submit rejected
    org.onroll.delete(f"/api/workspaces/{wid}/files/{fid}")
    assert org.onroll.post(f"/api/workspaces/{wid}/submit").status_code == 422


def test_notifications_and_websocket(org, client):
    with client.websocket_connect(f"/ws?token={org.intern.token}") as ws:
        assign(org.dev, org.intern, "Realtime task")
        msg = ws.receive_json()
        assert msg["event"] == "notification" and msg["data"]["type"] == "task_assigned"
    n = org.intern.get("/api/notifications").json()
    assert n["unread"] == 1
    # cannot mark someone else's notification
    assert org.offroll.post(f"/api/notifications/{n['items'][0]['id']}/read").status_code == 404
    org.intern.post("/api/notifications/read-all")
    assert org.intern.get("/api/notifications").json()["unread"] == 0


def test_websocket_rejects_bad_token(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=bad") as ws:
            ws.receive_json()


def test_dashboards_use_real_counts(org):
    t = assign(org.admin, org.intern).json()
    assign(org.admin, org.onroll)
    work_and_submit(org.intern, t["id"])
    d = org.admin.get("/api/dashboard/admin").json()
    assert d["people"] == {"total_employees": 6, "developers": 0, "onroll": 3, "offroll": 1, "interns": 2,
                           "admins": 1, "active": 6, "inactive": 0}
    assert d["tasks"]["total"] == 2 and d["tasks"]["under_review"] == 1 and d["tasks"]["pending"] == 1
    assert d["review_queue"] == {"onroll": 1, "admin": 0}
    dd = org.dev.get("/api/dashboard/developer").json()
    assert dd["team"]["total"] == 3 and dd["pending_reviews"] == 1
    me = org.intern.get("/api/dashboard/me").json()
    assert me["tasks"]["under_review"] == 1 and me["training_period"]["days_left"] > 150
    assert org.intern.get("/api/dashboard/developer").status_code == 403

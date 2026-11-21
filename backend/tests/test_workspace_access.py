"""Who may open somebody else's workspace, read-only.

The case this file exists for: an On-Roll employee reviews an intern's submitted task, the review page opens
fine, but "View workspace (read-only)" answered 403 "You cannot access this workspace" - because the read rule
only looked at team membership while the review rule also accepts the task's named reviewer and, for a submitter
without a team, any On-Roll employee.
"""
from tests.conftest import work_and_submit


def task_for(assigner, assignee, reviewer=None, title="Review me"):
    body = {"title": title, "assigned_to": assignee.id, "requirements": "Do it well"}
    if reviewer is not None:
        body["reviewer_id"] = reviewer.id
    r = assigner.post("/api/tasks", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_named_reviewer_can_read_the_workspace_he_reviews(org):
    t = task_for(org.onroll, org.intern, reviewer=org.onroll)
    wid, submitted = work_and_submit(org.intern, t["id"])
    assert submitted.status_code == 201, submitted.text

    answer = org.onroll.get(f"/api/tasks/{t['id']}/workspace")
    assert answer.status_code == 200, answer.text
    assert answer.json()["read_only"] is True
    assert answer.json()["id"] == wid
    assert [f["path"] for f in answer.json()["files"]] == ["main.py", "README.md"] or \
           "main.py" in [f["path"] for f in answer.json()["files"]]

    # read-only really is read-only: the reviewer cannot touch the files
    assert org.onroll.put(f"/api/workspaces/{wid}/files", {"path": "x.py", "content": "x"}).status_code == 403
    assert org.onroll.post(f"/api/workspaces/{wid}/move", {"from_path": "main.py", "to_path": "a.py"}).status_code == 403
    # and the history / download of the reviewed work can be read
    assert org.onroll.get(f"/api/workspaces/{wid}/history").status_code == 200
    assert org.onroll.get(f"/api/workspaces/{wid}/download").status_code == 200


def test_reviewer_can_read_even_when_the_submitter_has_no_team(org, make_user):
    """Any On-Roll employee may review a submitter without a team - so any of them can open that workspace."""
    solo = make_user("intern", "Solo Intern")          # in no team at all
    t = task_for(org.onroll, solo, reviewer=org.onroll)
    work_and_submit(solo, t["id"])
    answer = org.onroll.get(f"/api/tasks/{t['id']}/workspace")
    assert answer.status_code == 200, answer.text
    assert answer.json()["read_only"] is True


def test_reviewer_from_another_team_can_read(org):
    """The named reviewer does not have to lead the owner's team (here: Beta leads, Alpha intern)."""
    t = task_for(org.onroll, org.intern, reviewer=org.other_dev)
    work_and_submit(org.intern, t["id"])
    answer = org.other_dev.get(f"/api/tasks/{t['id']}/workspace")
    assert answer.status_code == 200, answer.text
    assert answer.json()["read_only"] is True


def test_an_unrelated_onroll_still_gets_403(org, make_user):
    third = make_user("onroll", "Third Lead")          # no team, not the reviewer
    t = task_for(org.onroll, org.intern, reviewer=org.other_dev)
    work_and_submit(org.intern, t["id"])
    assert third.get(f"/api/tasks/{t['id']}/workspace").status_code == 403


def test_the_owner_and_the_admin_are_unchanged(org):
    t = task_for(org.onroll, org.intern, reviewer=org.onroll)
    work_and_submit(org.intern, t["id"])
    mine = org.intern.get(f"/api/tasks/{t['id']}/workspace")
    assert mine.status_code == 200 and mine.json()["read_only"] is True   # submitted = locked, still readable
    assert org.admin.get(f"/api/tasks/{t['id']}/workspace").status_code == 200


def task_ids(actor):
    return [t["id"] for t in actor.get("/api/tasks").json()]


def test_a_task_waiting_for_my_review_is_in_my_task_list(org, make_user):
    """Reported: the review queue showed the intern's task, but the On-Roll task list did not.

    Here the task is assigned by another On-Roll lead and names no reviewer; the submitter has no team, so any
    On-Roll employee may review it - including Onroll One, who is neither the assigner nor a team lead here.
    """
    solo = make_user("intern", "Solo Two")            # no team
    t = task_for(org.other_dev, solo)                 # assigned by somebody else, no reviewer named
    work_and_submit(solo, t["id"])
    queue = org.onroll.get("/api/submissions?view=queue").json()
    assert t["id"] in [s["task_id"] for s in queue]   # the review queue offers it
    assert t["id"] in task_ids(org.onroll)            # ... and the task list must too


def test_the_task_stays_in_my_list_after_i_reviewed_it(org, make_user):
    solo = make_user("intern", "Solo Three")
    t = task_for(org.other_dev, solo)
    _, submitted = work_and_submit(solo, t["id"])
    sub_id = submitted.json()["id"]
    assert org.onroll.post(f"/api/submissions/{sub_id}/review",
                           {"decision": "approved", "comment": "fine"}).status_code == 200
    assert t["id"] in task_ids(org.onroll)


def test_a_foreign_task_is_still_hidden(org):
    """The intern is in Dev One's team, so Onroll One (who leads nothing) must not see the task."""
    t = task_for(org.dev, org.intern)
    work_and_submit(org.intern, t["id"])
    assert t["id"] not in task_ids(org.onroll)
    assert org.onroll.get(f"/api/tasks/{t['id']}").status_code == 403


def test_automatic_reviewer_and_no_team_still_opens_the_workspace(org, make_user):
    """The exact screen reported: task 16, 'On-Roll reviewer: Automatic' (no reviewer named), assigned by
    another On-Roll, submitted by an intern without a team. The reviewing On-Roll must be able to look."""
    solo = make_user("intern", "Solo Four")
    t = task_for(org.other_dev, solo, reviewer=None, title="Automatic reviewer")
    assert t["reviewer_id"] is None
    work_and_submit(solo, t["id"])
    answer = org.onroll.get(f"/api/tasks/{t['id']}/workspace")
    assert answer.status_code == 200, answer.text
    assert answer.json()["read_only"] is True

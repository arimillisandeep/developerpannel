"""API audit: success paths that the other live scripts did not reach.
Edit a task, comment on a submission, rework + restore an old version, final approval, reopen, cancel.
Every step is a real HTTP request and is checked again in the SQLite test database."""
import json, os, sys, time
import httpx

A = os.environ.get("AUDIT_API", "http://127.0.0.1:8010") + "/api"
DB = os.environ.get("AUDIT_DB", "")
SFX = str(int(time.time()))[-6:]
R = []

def chk(name, ok, detail=""):
    R.append({"area": "tasks and reviews (extra)", "check": name, "result": "PASS" if ok else "FAIL", "detail": "" if ok else str(detail)[:300]})
    print("PASS" if ok else "FAIL", name, "" if ok else str(detail)[:200])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_dbconn import rows
def db(q, *a):
    return rows(q, a)

def login(who):
    r = httpx.post(A + "/auth/login", json={"email": who + "@workcode.local", "password": "Workcode@123"})
    return httpx.Client(base_url=A, headers={"Authorization": "Bearer " + r.json()["access_token"]}, timeout=30), r.json()["user"]

ad, _ = login("admin"); lead, lead_me = login("reviewer"); it, it_me = login("intern")

r = ad.post("/tasks", json={"title": f"Extra audit {SFX}", "assigned_to_ids": [it_me["id"]], "reviewer_id": lead_me["id"], "requirements": "first"})
tid = r.json()["created"][0]["id"]
r = ad.patch(f"/tasks/{tid}", json={"title": f"Extra audit edited {SFX}", "priority": "high"})
row = db("select title, priority from tasks where id=?", tid)[0]
chk("PATCH /tasks/{id}: admin edits title and priority -> 200 and stored", r.status_code == 200 and row == (f"Extra audit edited {SFX}", "high"), (r.status_code, r.text, row))
chk("PATCH /tasks/{id}: the intern cannot edit the task -> 403", it.patch(f"/tasks/{tid}", json={"title": "hacked title"}).status_code == 403)

it.post(f"/tasks/{tid}/accept"); it.post(f"/tasks/{tid}/start")
ws = it.get(f"/tasks/{tid}/workspace").json(); wid = ws["workspace"]["id"] if "workspace" in ws else ws["id"]
it.put(f"/workspaces/{wid}/files", json={"path": "main.py", "content": "print('version one')\n", "manual": True})
sub = it.post(f"/workspaces/{wid}/submit", json={"note": "v1"}).json(); sid = sub.get("id") or sub.get("submission", {}).get("id")

r = lead.post(f"/submissions/{sid}/comments", json={"body": "Please rename the variable", "file_path": "main.py", "line_no": 1})
row = db("select body, file_path, line_no, author_id from review_comments where submission_id=?", sid)
chk("POST /submissions/{id}/comments: reviewer comment -> 2xx and stored once", r.status_code in (200, 201) and row == [("Please rename the variable", "main.py", 1, lead_me["id"])], (r.status_code, r.text, row))
off, _ = login("offroll")
chk("POST /submissions/{id}/comments: an unrelated user -> 403/404", off.post(f"/submissions/{sid}/comments", json={"body": "x"}).status_code in (403, 404))

chk("restore while under review is refused (409)", it.post(f"/submissions/{sid}/restore").status_code == 409)
lead.post(f"/submissions/{sid}/review", json={"decision": "changes_requested", "comment": "rework please"})
it.put(f"/workspaces/{wid}/files", json={"path": "main.py", "content": "print('broken edit')\n", "manual": True})
r = it.post(f"/submissions/{sid}/restore")
now = db("select content from workspace_files where workspace_id=? and path='main.py' and deleted_at is null", wid)
chk("POST /submissions/{id}/restore: old version back in the workspace -> 200 and stored", r.status_code == 200 and now == [("print('version one')\n",)], (r.status_code, r.text, now))
chk("POST /submissions/{id}/restore: the reviewer cannot restore -> 403", lead.post(f"/submissions/{sid}/restore").status_code == 403)

r = it.post(f"/workspaces/{wid}/submit", json={"note": "v2"})
chk("submitting again with no change since the last version is refused", r.status_code in (400, 409, 422), (r.status_code, r.text))
it.put(f"/workspaces/{wid}/files", json={"path": "main.py", "content": "print('version two')\n", "manual": True})
sub2 = it.post(f"/workspaces/{wid}/submit", json={"note": "v2"}).json(); sid2 = sub2.get("id") or sub2.get("submission", {}).get("id")
lead.post(f"/submissions/{sid2}/review", json={"decision": "approved", "comment": "ok"})
ad.post(f"/submissions/{sid2}/review", json={"decision": "approved", "comment": "final ok"})
chk("task completed after the admin approval", db("select status from tasks where id=?", tid)[0][0] == "completed")
chk("POST /tasks/{id}/reopen: only admin (reviewer -> 403), reason required (422)", lead.post(f"/tasks/{tid}/reopen", json={"comment": "x"}).status_code == 403 and ad.post(f"/tasks/{tid}/reopen", json={"comment": ""}).status_code == 422)
r = ad.post(f"/tasks/{tid}/reopen", json={"comment": "add a second page"})
chk("POST /tasks/{id}/reopen -> 200, task is rework_required again", r.status_code == 200 and db("select status from tasks where id=?", tid)[0][0] == "rework_required", (r.status_code, r.text))
chk("POST /tasks/{id}/cancel: reason required (422), intern cannot cancel (403)", ad.post(f"/tasks/{tid}/cancel", json={"comment": ""}).status_code == 422 and it.post(f"/tasks/{tid}/cancel", json={"comment": "no"}).status_code == 403)
r = ad.post(f"/tasks/{tid}/cancel", json={"comment": "not needed any more"})
st = db("select status from tasks where id=?", tid)[0][0]
chk("POST /tasks/{id}/cancel -> 200, task cancelled, a second cancel -> 409", r.status_code == 200 and st == "cancelled" and ad.post(f"/tasks/{tid}/cancel", json={"comment": "again"}).status_code == 409, (r.status_code, r.text, st))
chk("files are locked after cancel (save refused)", it.put(f"/workspaces/{wid}/files", json={"path": "main.py", "content": "x", "manual": True}).status_code in (403, 409))
json.dump(R, open(os.path.join(os.path.dirname(__file__), "..", "..", "audit", "extra.json"), "w"), indent=1)
print(sum(1 for x in R if x["result"] == "PASS"), "of", len(R), "passed")
sys.exit(0 if all(x["result"] == "PASS" for x in R) else 1)

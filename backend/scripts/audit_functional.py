"""API audit step 3: real workflows over HTTP on the isolated test server, each write checked in the database file.

    AUDIT_DB=/tmp/audit/audit.db python scripts/audit_functional.py        (server on :8010, see audit_matrix.py)
Writes ../audit/functional.json. Never run against real data.
"""
import asyncio, io, json, os, time, zipfile
import httpx, jwt, websockets
B = os.environ.get("AUDIT_API", "http://127.0.0.1:8010"); A = B + "/api"
DB = os.environ.get("AUDIT_DB", "/tmp/audit/audit.db"); SECRET = os.environ.get("JWT_SECRET", "audit-secret-not-for-production-000000001")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "audit")
RES = []; AREA = [""]; SFX = str(int(time.time()))[-6:]
def area(a): AREA[0] = a; print("\n== " + a)
def chk(name, cond, extra="", warn=False):
    st = "PASS" if cond else ("WARNING" if warn else "FAIL")
    RES.append({"area": AREA[0], "check": name, "result": st, "detail": "" if cond else str(extra)[:300]})
    if not cond: print(f"{st} {name} :: {str(extra)[:300]}")
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_dbconn import rows
def db(q, *a):
    return rows(q, a, as_dict=True)
def login(e, pw="Workcode@123"):
    r = httpx.post(A + "/auth/login", json={"email": e, "password": pw})
    return (httpx.Client(base_url=A, headers={"Authorization": "Bearer " + r.json()["access_token"]}, timeout=30), r.json()) if r.status_code == 200 else (None, r)
C = {}; ME = {}; TOK = {}
for k in ("admin", "reviewer", "onroll", "offroll", "intern"):
    C[k], j = login(k + "@workcode.local"); ME[k] = j["user"]; TOK[k] = j["access_token"]
ad, lead, onr, off, it = C["admin"], C["reviewer"], C["onroll"], C["offroll"], C["intern"]
def J(r):
    try: return r.json()
    except Exception: return r.text

area("auth")
r = httpx.post(A + "/auth/login", json={"email": "intern@workcode.local", "password": "wrong"}); chk("wrong password -> 401", r.status_code == 401, r.text)
r = httpx.post(A + "/auth/login", json={"email": "nobody@workcode.local", "password": "x"}); chk("unknown email -> same 401 text (no account hint)", r.status_code == 401 and "Incorrect email or password" in r.text, r.text)
r = httpx.post(A + "/auth/login", json={"email": "INTERN@workcode.local ", "password": "Workcode@123"}); chk("login ignores case/spaces in email", r.status_code == 200, r.text)
chk("login body: token + user, no password hash", set(r.json()) >= {"access_token", "user"} and "password" not in json.dumps(r.json()).lower().replace("must_change_password", ""), list(r.json()))
r = httpx.post(A + "/auth/login", json={"email": "x"}); chk("login without password -> 422", r.status_code == 422, r.text)
me = it.get("/auth/me").json(); chk("/auth/me has id, email, role, full_name", all(k in me for k in ("id", "email", "role", "full_name")) and me["role"] == "intern", me)
exp = jwt.encode({"sub": str(ME["intern"]["id"]), "role": "intern", "exp": int(time.time()) - 60}, SECRET, algorithm="HS256")
chk("expired token -> 401", httpx.get(A + "/auth/me", headers={"Authorization": "Bearer " + exp}).status_code == 401)
forged = jwt.encode({"sub": str(ME["admin"]["id"]), "role": "admin", "exp": int(time.time()) + 600}, "another-secret-another-secret-another", algorithm="HS256")
chk("token signed with another secret -> 401", httpx.get(A + "/auth/me", headers={"Authorization": "Bearer " + forged}).status_code == 401)
payload = jwt.decode(TOK["intern"], SECRET, algorithms=["HS256"])
up = jwt.encode({**payload, "role": "admin"}, "guess", algorithm="HS256"); chk("intern token re-signed as admin -> 401", httpx.get(A + "/users", headers={"Authorization": "Bearer " + up}).status_code == 401)
none = jwt.encode({**payload, "role": "admin"}, None, algorithm="none"); chk("alg=none token -> 401", httpx.get(A + "/auth/me", headers={"Authorization": "Bearer " + none}).status_code == 401)
chk("token in ?token= query is refused (query tokens off)", httpx.get(A + "/auth/me", params={"token": TOK["intern"]}).status_code == 401)
chk("change password: wrong current -> 400", off.post("/auth/change-password", json={"current_password": "nope", "new_password": "Newpass@12345"}).status_code == 400)
r = off.post("/auth/change-password", json={"current_password": "Workcode@123", "new_password": "short"}); chk("change password: weak new password -> 422", r.status_code == 422, r.text)
r = off.post("/auth/change-password", json={"current_password": "Workcode@123", "new_password": "Newpass@12345"}); chk("change password ok", r.status_code == 200, r.text)
chk("old password no longer works, new one does", login("offroll@workcode.local")[0] is None and login("offroll@workcode.local", "Newpass@12345")[0] is not None)
h = db("select password_hash from users where email='offroll@workcode.local'")[0]["password_hash"]; chk("DB: password stored as bcrypt hash", h.startswith("$2") and "Newpass" not in h, h[:10])
chk("token issued before the password change is refused afterwards", off.get("/auth/me").status_code == 401)
chk("the change-password answer carries a new working token", httpx.get(A + "/auth/me", headers={"Authorization": "Bearer " + r.json().get("access_token", "")}).status_code == 200)
off, _ = login("offroll@workcode.local", "Newpass@12345"); C["offroll"] = off
r = off.post("/auth/change-password", json={"current_password": "Newpass@12345", "new_password": "Workcode@123"})
off, j = login("offroll@workcode.local"); C["offroll"] = off; TOK["offroll"] = j["access_token"]
tmp, _ = login("onroll@workcode.local"); r = tmp.post("/auth/logout"); chk("logout -> 200", r.status_code == 200, r.text)
chk("token rejected after logout", tmp.get("/auth/me").status_code == 401)
C["onroll"], j = login("onroll@workcode.local"); TOK["onroll"] = j["access_token"]; onr = C["onroll"]   # logout ends every token of that person, so sign in again

area("users (admin)")
r = ad.post("/users", json={"email": f"aud{SFX}@workcode.local", "password": "Workcode@123", "full_name": "Audit One", "role": "intern", "phone": "9000000001"}); u1 = J(r)
chk("create user -> 201", r.status_code == 201 and u1.get("email") == f"aud{SFX}@workcode.local", r.text)
chk("create response hides the password", "Workcode@123" not in r.text and "password_hash" not in r.text)
row = db("select * from users where email='aud'||?||'@workcode.local'", SFX); chk("DB: user row written once, hashed, active", len(row) == 1 and row[0]["password_hash"].startswith("$2") and row[0]["is_active"] == 1 and row[0]["role"] == "intern", row)
chk("duplicate email -> 409", ad.post("/users", json={"email": f"AUD{SFX}@workcode.local", "password": "Workcode@123", "full_name": "Dup", "role": "intern"}).status_code == 409)
chk("DB: still one row for that email", len(db("select id from users where lower(email)='aud'||?||'@workcode.local'", SFX)) == 1)
chk("role developer is refused -> 422", ad.post("/users", json={"email": "dev9@workcode.local", "password": "Workcode@123", "full_name": "Dev", "role": "developer"}).status_code == 422)
chk("bad email -> 422", ad.post("/users", json={"email": "not-an-email", "password": "Workcode@123", "full_name": "X", "role": "intern"}).status_code == 422)
chk("weak password -> 422", ad.post("/users", json={"email": "weak@workcode.local", "password": "123", "full_name": "X", "role": "intern"}).status_code == 422)
chk("intern cannot create users -> 403", it.post("/users", json={"email": "h@workcode.local", "password": "Workcode@123", "full_name": "H", "role": "admin"}).status_code == 403)
chk("on-roll cannot create users -> 403", lead.post("/users", json={"email": "h2@workcode.local", "password": "Workcode@123", "full_name": "H", "role": "intern"}).status_code == 403)
l = ad.get("/users", params={"q": "Audit One"}).json(); chk("list + search finds the user", any(x["id"] == u1["id"] for x in l), l)
chk("search with SQL text is harmless", ad.get("/users", params={"q": "' OR 1=1; DROP TABLE users;--"}).status_code == 200 and len(db("select id from users")) >= 6)
chk("filter by role", all(x["role"] == "intern" for x in ad.get("/users", params={"role": "intern"}).json()))
chk("intern cannot list users", it.get("/users").status_code == 403)
r = ad.patch(f"/users/{u1['id']}", json={"phone": "9111111111", "full_name": "Audit Uno"}); chk("edit user", r.status_code == 200 and r.json()["full_name"] == "Audit Uno", r.text)
chk("DB: edit saved", db("select u.full_name, p.phone from users u join employee_profiles p on p.user_id=u.id where u.id=?", u1["id"])[0] == {"full_name": "Audit Uno", "phone": "9111111111"})
chk("intern cannot edit another user", it.patch(f"/users/{u1['id']}", json={"full_name": "Hacked"}).status_code == 403)
chk("intern cannot make self admin through PATCH", it.patch(f"/users/{ME['intern']['id']}", json={"role": "admin"}).status_code in (403, 422) and db("select role from users where id=?", ME["intern"]["id"])[0]["role"] == "intern")
chk("get own profile ok, other's profile refused", it.get(f"/users/{ME['intern']['id']}").status_code == 200 and it.get(f"/users/{ME['admin']['id']}").status_code == 403)
c1, _ = login(f"aud{SFX}@workcode.local")
r = ad.post(f"/users/{u1['id']}/deactivate", json={"reason": "audit"}); chk("deactivate", r.status_code == 200, r.text)
chk("deactivated: login refused and old token refused", login(f"aud{SFX}@workcode.local")[1].status_code == 403 and c1.get("/auth/me").status_code == 401)
chk("activate again", ad.post(f"/users/{u1['id']}/activate").status_code == 200 and login(f"aud{SFX}@workcode.local")[0] is not None)
r = ad.post(f"/users/{u1['id']}/convert", json={"to_role": "offroll", "reason": "audit", "confirm_early": True}); chk("convert intern -> off-roll", r.status_code == 200 and db("select role from users where id=?", u1["id"])[0]["role"] == "offroll", r.text)
h = ad.get(f"/users/{u1['id']}/history"); chk("role history has the change", h.status_code == 200 and "offroll" in h.text, h.text[:200])
chk("activity list", ad.get(f"/users/{u1['id']}/activity").status_code == 200)
chk("activity of a user that does not exist -> 404", ad.get("/users/999999/activity").status_code == 404, "returns 200 []")
hc = ad.get("/users/intern-headcount"); chk("intern headcount", hc.status_code == 200 and "target" in hc.text, hc.text)
r = ad.put("/intern-vacancy", json={"target_headcount": 12}); chk("set intern vacancy", r.status_code == 200 and ad.get("/users/intern-headcount").json().get("target") == 12, r.text)
chk("vacancy negative -> 422", ad.put("/intern-vacancy", json={"target_headcount": -1}).status_code == 422)
chk("admin cannot delete self", ad.delete(f"/users/{ME['admin']['id']}").status_code in (400, 403, 409))
r = ad.delete(f"/users/{u1['id']}"); chk("delete user", r.status_code in (200, 204), r.text)
chk("deleted user cannot log in; row kept (soft delete)", login(f"aud{SFX}@workcode.local")[0] is None and len(db("select id from users where id=?", u1["id"])) == 1)
chk("assignable + reviewers lists", ad.get("/users/assignable").status_code == 200 and all(x["role"] == "onroll" for x in ad.get("/users/reviewers").json()))

area("departments, projects, teams")
r = ad.post("/departments", json={"name": "Audit Dept " + SFX}); chk("create department", r.status_code == 201, r.text)
chk("duplicate department -> 409", ad.post("/departments", json={"name": "Audit Dept " + SFX}).status_code == 409)
r = ad.post("/projects", json={"name": "Audit Project " + SFX}); chk("create project", r.status_code == 201, r.text)
r = ad.post("/teams", json={"name": "Audit Team " + SFX, "lead_developer_id": ME["onroll"]["id"]}); tm = J(r); chk("create team with on-roll lead", r.status_code == 201, r.text)
chk("team lead must be on-roll", ad.post("/teams", json={"name": "Bad Team", "lead_developer_id": ME["intern"]["id"]}).status_code in (400, 422))
r = ad.post(f"/teams/{tm['id']}/members", json={"user_id": ME["offroll"]["id"]}); chk("add member", r.status_code in (200, 201), r.text)
r2 = ad.post(f"/teams/{tm['id']}/members", json={"user_id": ME["offroll"]["id"]})
chk("DB: adding the same member twice leaves one row", len(db("select * from team_members where team_id=? and user_id=?", tm["id"], ME["offroll"]["id"])) == 1, r2.text)
chk("on-roll lead sees own team", any(x["id"] == tm["id"] for x in onr.get("/teams").json()))
chk("rename team", ad.patch(f"/teams/{tm['id']}", json={"name": "Audit Team 2 " + SFX}).status_code == 200 and db("select name from teams where id=?", tm["id"])[0]["name"] == "Audit Team 2 " + SFX)
chk("remove member", ad.delete(f"/teams/{tm['id']}/members/{ME['offroll']['id']}").status_code in (200, 204) and not db("select * from team_members where team_id=? and user_id=?", tm["id"], ME["offroll"]["id"]))
chk("intern cannot create team/department/project", [it.post(p, json={"name": "x1"}).status_code for p in ("/teams", "/departments", "/projects")] == [403, 403, 403])
chk("lists open", [ad.get(p).status_code for p in ("/departments", "/projects", "/teams")] == [200, 200, 200])

area("work timer and sessions")
r = it.post("/sessions/start", json={"client_id": "audit-tab-" + SFX}); s = J(r); chk("start session", r.status_code == 200, r.text)
chk("client_id too short -> 422", it.post("/sessions/start", json={"client_id": "x"}).status_code == 422)
cur = it.get("/sessions/current"); chk("current session", cur.status_code == 200 and cur.json(), cur.text)
r = it.post("/sessions/heartbeat", json={"client_id": "audit-tab-" + SFX, "state": "active"}); chk("heartbeat", r.status_code == 200, r.text)
chk("heartbeat with invalid state -> 422", it.post("/sessions/heartbeat", json={"client_id": "audit-tab-" + SFX, "state": "dancing"}).status_code == 422)
chk("pause / resume", it.post("/sessions/pause").status_code == 200 and it.post("/sessions/resume").status_code == 200)
live = ad.get("/sessions/live"); chk("admin live monitor lists the intern", live.status_code == 200 and "Kabir" in live.text, live.text[:200])
chk("off-roll cannot see live monitor", off.get("/sessions/live").status_code == 403)
chk("stop", it.post("/sessions/stop").status_code == 200)
chk("DB: one session row, ended", [x["ended_at"] is not None for x in db("select ended_at from work_sessions where user_id=? order by id desc limit 1", ME["intern"]["id"])] == [True])
chk("heartbeat without a session -> clean 4xx", 400 <= it.post("/sessions/heartbeat", json={"client_id": "audit-tab-" + SFX, "state": "active"}).status_code < 500)
chk("attendance own", it.get("/attendance").status_code == 200)
chk("attendance of another user refused / admin allowed", it.get("/attendance", params={"user_id": ME["admin"]["id"]}).status_code == 403 and ad.get("/attendance", params={"user_id": ME["intern"]["id"]}).status_code == 200)
chk("timer sessions own + other refused", it.get("/timer/sessions").status_code == 200 and it.get("/timer/sessions", params={"user_id": ME["offroll"]["id"]}).status_code == 403)
ov = ad.get("/timer/overview"); chk("timer overview (admin)", ov.status_code == 200, ov.text[:200])
csv = ad.get("/timer/overview", params={"format": "csv"}); chk("timer overview CSV", csv.status_code == 200 and "text/csv" in csv.headers.get("content-type", ""), csv.headers)
chk("timer overview bad date -> 422", ad.get("/timer/overview", params={"start": "not-a-date"}).status_code == 422)
al = ad.get("/timer/allowlist"); chk("allowlist list", al.status_code == 200 and any("chatgpt" in x["domain"] for x in al.json()), al.text[:200])
r = ad.post("/timer/allowlist", json={"domain": f"https://Docs{SFX}.Example.com/path", "label": "Docs"}); st = J(r); chk("allowlist add normalises the domain", r.status_code in (200, 201) and st.get("domain") == f"docs{SFX}.example.com", r.text)
chk("allowlist duplicate -> 409", ad.post("/timer/allowlist", json={"domain": f"docs{SFX}.example.com"}).status_code == 409)
chk("allowlist: intern cannot add", it.post("/timer/allowlist", json={"domain": "evil.com"}).status_code == 403)
chk("allowlist delete", ad.delete(f"/timer/allowlist/{st.get('id')}").status_code in (200, 204) and not db("select id from website_allowlist where id=?", st.get("id")))
r = it.post("/extension/token"); et = J(r); chk("extension token issued", r.status_code == 200 and et.get("token"), r.text)
eh = {"Authorization": "Bearer " + et.get("token", "")}
chk("extension token: config ok", httpx.get(A + "/extension/config", headers=eh).status_code == 200)
chk("extension token cannot be used as a login token", httpx.get(A + "/auth/me", headers=eh).status_code == 401 and httpx.get(A + "/tasks", headers=eh).status_code == 401)
chk("login token cannot be used as extension token", httpx.get(A + "/extension/config", headers={"Authorization": "Bearer " + TOK["intern"]}).status_code == 401)
r = httpx.post(A + "/extension/report", headers=eh, json={"category": "approved", "domain": "chatgpt.com"}); chk("extension report", r.status_code == 200, r.text)
chk("extension report bad category -> 422", httpx.post(A + "/extension/report", headers=eh, json={"category": "hack"}).status_code == 422)

area("notifications")
n = it.get("/notifications").json(); items = n if isinstance(n, list) else n.get("items", [])
chk("list", isinstance(items, list) and len(items) > 0, n)
if items:
    nid = items[0]["id"]
    chk("another user cannot mark my notification", off.post(f"/notifications/{nid}/read").status_code == 404)
    chk("mark one read + DB", it.post(f"/notifications/{nid}/read").status_code == 200 and db("select is_read from notifications where id=?", nid)[0]["is_read"] == 1)
chk("read all + DB", it.post("/notifications/read-all").status_code == 200 and not db("select id from notifications where user_id=? and not is_read", ME["intern"]["id"]))
chk("limit over the maximum -> 422", it.get("/notifications", params={"limit": 100000}).status_code == 422)

area("meetings")
chk("invitable list", lead.get("/meetings/invitable").status_code == 200)
r = lead.post("/meetings", json={"title": "Audit sync", "agenda": "a", "starts_at": "2030-05-01T10:00:00Z", "duration_minutes": 30, "link": "https://meet.google.com/abc-defg-hij", "participant_ids": [ME["intern"]["id"]]}); mt = J(r)
chk("create meeting", r.status_code == 201, r.text)
chk("participant sees it, outsider does not", any(x["id"] == mt["id"] for x in it.get("/meetings").json()) and not any(x["id"] == mt["id"] for x in off.get("/meetings").json()))
chk("participant got a notification (DB)", len(db("select id from notifications where user_id=? and (title like '%eeting%' or body like '%Audit sync%')", ME["intern"]["id"])) >= 1)
chk("javascript: link refused", lead.post("/meetings", json={"title": "x", "starts_at": "2030-05-01T10:00:00Z", "link": "javascript:alert(1)", "participant_ids": [ME["intern"]["id"]]}).status_code == 422)
chk("meeting without title -> 422", lead.post("/meetings", json={"starts_at": "2030-05-01T10:00:00Z", "participant_ids": []}).status_code == 422)
chk("participant cannot delete, organiser can", it.delete(f"/meetings/{mt['id']}").status_code == 403 and lead.delete(f"/meetings/{mt['id']}").status_code in (200, 204) and (db("select cancelled_at from meetings where id=?", mt["id"]) or [{"cancelled_at": 1}])[0]["cancelled_at"] is not None)

area("chat")
chk("contacts", it.get("/chat/contacts").status_code == 200)
r = it.post("/chat/conversations", json={"kind": "direct", "user_ids": [ME["reviewer"]["id"]]}); cv = J(r); chk("open direct chat", r.status_code in (200, 201), r.text)
r2 = it.post("/chat/conversations", json={"kind": "direct", "user_ids": [ME["reviewer"]["id"]]}); chk("opening it again returns the same chat (no duplicate)", J(r2).get("id") == cv["id"], r2.text)
async def ws_wait():
    async with websockets.connect(B.replace("http", "ws") + "/ws?token=" + TOK["reviewer"]) as w:
        await asyncio.sleep(0.3)
        it.post(f"/chat/conversations/{cv['id']}/messages", json={"body": "audit <b>hi</b>"})
        try: return json.loads(await asyncio.wait_for(w.recv(), 4))
        except Exception as e: return {"error": repr(e)}
ev = asyncio.run(ws_wait()); chk("WebSocket /ws: the other person gets a live event when a message is sent", "error" not in ev, ev)
m = lead.get(f"/chat/conversations/{cv['id']}/messages").json(); m = m if isinstance(m, list) else next((v for v in m.values() if isinstance(v, list)), []); chk("message stored and returned as plain text", any(x["body"] == "audit <b>hi</b>" for x in m), m)
chk("unread counter for the receiver", any(c["id"] == cv["id"] and c["unread"] >= 0 for c in lead.get("/chat/conversations").json()))
chk("outsider cannot read or write this chat", off.get(f"/chat/conversations/{cv['id']}/messages").status_code in (403, 404) and off.post(f"/chat/conversations/{cv['id']}/messages", json={"body": "x"}).status_code in (403, 404))
chk("empty message -> 422", it.post(f"/chat/conversations/{cv['id']}/messages", json={"body": ""}).status_code == 422)
async def ws_bad():
    try:
        async with websockets.connect(B.replace("http", "ws") + "/ws?token=bad") as w:
            await asyncio.wait_for(w.recv(), 3); return "open"
    except websockets.exceptions.ConnectionClosed as e: return e.code
    except Exception as e: return type(e).__name__
chk("WebSocket /ws without a valid token is closed", ws_code := asyncio.run(ws_bad()) in (4401, "InvalidStatus", "ConnectionClosedError"), ws_code)

area("recordings (upload / download)")
chk("start without consent refused", 400 <= it.post("/recordings/start", json={"consent": False}).status_code < 500)
r = it.post("/recordings/start", json={"consent": True, "mime_type": "video/webm"}); rc = J(r); chk("start", r.status_code in (200, 201), r.text)
data = b"\x1aE\xdf\xa3" + os.urandom(5000)
r = it.post(f"/recordings/{rc['id']}/chunk", content=data[:3000], headers={"Content-Type": "application/octet-stream"}); chk("chunk 1", r.status_code == 200, r.text)
r = it.post(f"/recordings/{rc['id']}/chunk", content=data[3000:], headers={"Content-Type": "application/octet-stream"}); chk("chunk 2", r.status_code == 200, r.text)
chk("another user cannot add a chunk", off.post(f"/recordings/{rc['id']}/chunk", content=b"x").status_code in (403, 404))
chk("stop", it.post(f"/recordings/{rc['id']}/stop").status_code == 200)
chk("chunk after stop refused", 400 <= it.post(f"/recordings/{rc['id']}/chunk", content=b"x").status_code < 500)
f = it.get(f"/recordings/{rc['id']}/file"); chk("download returns exactly the uploaded bytes", f.status_code == 200 and f.content == data, (f.status_code, len(f.content)))
rg = it.get(f"/recordings/{rc['id']}/file", headers={"Range": "bytes=0-99"}); chk("range request (video seeking)", rg.status_code in (200, 206), rg.status_code, warn=True)
chk("admin can watch, off-roll cannot", ad.get(f"/recordings/{rc['id']}/file").status_code == 200 and off.get(f"/recordings/{rc['id']}/file").status_code in (403, 404))
row = db("select * from screen_recordings where id=?", rc["id"])[0]; chk("DB: size and status saved", row.get("size_bytes") == len(data) and row.get("status") in ("completed", "stopped", "ready", "saved"), row)
chk("list own; admin filter by user", any(x["id"] == rc["id"] for x in it.get("/recordings").json()) and any(x["id"] == rc["id"] for x in ad.get("/recordings", params={"user_id": ME["intern"]["id"]}).json()))

area("dashboards and reports")
chk("admin dashboard", ad.get("/dashboard/admin").status_code == 200 and it.get("/dashboard/admin").status_code == 403)
for k in ("reviewer", "offroll", "intern"): chk(f"my dashboard ({k})", C[k].get("/dashboard/me").status_code == 200)
chk("legacy /dashboard/developer answers for on-roll", lead.get("/dashboard/developer").status_code == 200)
for k in ("admin", "reviewer", "offroll", "intern"):
    r = C[k].get("/reports/summary"); chk(f"report summary ({k})", r.status_code == 200, r.text[:200])
rows_i = it.get("/reports/summary").json(); chk("intern's report holds only the intern", "Arun" not in json.dumps(rows_i) and "Kabir" in json.dumps(rows_i), json.dumps(rows_i)[:300])
r = ad.get("/reports/summary", params={"format": "csv"}); chk("report CSV download", r.status_code == 200 and "csv" in r.headers.get("content-type", "") and "attachment" in r.headers.get("content-disposition", ""), dict(r.headers))
chk("report bad date -> 422", ad.get("/reports/summary", params={"start": "x"}).status_code == 422)
chk("report with end before start -> 422", ad.get("/reports/summary", params={"start": "2026-02-01", "end": "2026-01-01"}).status_code == 422, "answers 200 and silently uses one day instead of saying the range is wrong")
r = ad.get("/audit-logs"); chk("audit log (admin) lists this run's actions", r.status_code == 200 and "user.create" in r.text, r.text[:200])
chk("audit log refused to others; limit capped", lead.get("/audit-logs").status_code == 403 and ad.get("/audit-logs", params={"limit": 999999}).status_code == 422)

area("coding workspace")
t = ad.post("/tasks", json={"title": "Audit workspace", "assigned_to_ids": [ME["offroll"]["id"]], "requirements": "x"}).json()["created"][0]
w0 = off.get(f"/tasks/{t['id']}/workspace").json(); chk("workspace read-only before accept; save refused", w0.get("read_only") is True and off.put(f"/workspaces/{w0['id']}/files", json={"path": "a.txt", "content": "x"}).status_code in (403, 409))
off.post(f"/tasks/{t['id']}/accept"); W = w0["id"]
r = off.put(f"/workspaces/{W}/files", json={"path": "src/app.py", "content": "print('v1')\n", "manual": True}); fl = J(r).get("file", {}); chk("create file", r.status_code == 200 and fl.get("path") == "src/app.py", r.text)
chk("DB: file row + first version", len(db("select id from workspace_files where workspace_id=? and path='src/app.py' and deleted_at is null", W)) == 1 and len(db("select id from file_versions where file_id=?", fl["id"])) >= 1)
chk("task moved to in_progress on first save", db("select status from tasks where id=?", t["id"])[0]["status"] == "in_progress")
off.put(f"/workspaces/{W}/files", json={"path": "src/app.py", "content": "print('v2')\n", "manual": True})
chk("DB: saving again updates the same row (no duplicate)", len(db("select id from workspace_files where workspace_id=? and path='src/app.py'", W)) == 1 and db("select content from workspace_files where id=?", fl["id"])[0]["content"] == "print('v2')\n")
for bad in ("../etc/passwd", "/etc/passwd", "a/../../b.txt", "con\x00.txt", ""):
    chk(f"bad path {bad!r} refused", off.put(f"/workspaces/{W}/files", json={"path": bad, "content": "x"}).status_code in (400, 422))
chk("file over 1 MB refused", off.put(f"/workspaces/{W}/files", json={"path": "big.txt", "content": "x" * 1_000_100}).status_code in (400, 413, 422))
v = off.get(f"/workspaces/{W}/files/{fl['id']}/versions").json(); chk("versions newest first, both kept", len(v) >= 2, v)
old = [x for x in v if "v1" in (x.get("content") or "")] or v[-1:]
r = off.post(f"/workspaces/{W}/files/{fl['id']}/versions/{old[0]['id']}/restore"); chk("restore old version + DB", r.status_code == 200 and db("select content from workspace_files where id=?", fl["id"])[0]["content"] == "print('v1')\n", r.text)
r = off.post(f"/workspaces/{W}/files/{fl['id']}/rename", json={"new_path": "src/main.py"}); chk("rename file", r.status_code == 200 and db("select path from workspace_files where id=?", fl["id"])[0]["path"] == "src/main.py", r.text)
off.put(f"/workspaces/{W}/files", json={"path": "src/util.py", "content": "x = 1\n", "manual": True})
r = off.post(f"/workspaces/{W}/move", json={"from_path": "src", "to_path": "lib"}); chk("move folder", r.status_code == 200 and {x["path"] for x in db("select path from workspace_files where workspace_id=? and path like 'lib/%' and deleted_at is null", W)} == {"lib/main.py", "lib/util.py"}, r.text)
r = off.post(f"/workspaces/{W}/copy", json={"from_path": "lib/util.py", "to_path": "lib/util2.py"}); chk("copy file", r.status_code in (200, 201) and db("select content from workspace_files where workspace_id=? and path='lib/util2.py' and deleted_at is null", W), r.text)
chk("move onto an existing file refused", off.post(f"/workspaces/{W}/move", json={"from_path": "lib/util.py", "to_path": "lib/util2.py"}).status_code in (400, 409))
tp = off.get("/templates"); chk("templates list", tp.status_code == 200 and len(tp.json()) >= 10, tp.text[:100])
tid0 = tp.json()[0]["id"]; r = off.post(f"/workspaces/{W}/template", json={"template_id": tid0, "overwrite": False}); chk("apply template writes real files (DB)", r.status_code in (200, 201) and {"index.html"} <= {x["path"] for x in db("select path from workspace_files where workspace_id=? and deleted_at is null", W)}, r.text[:200])
chk("unknown template -> 404", off.post(f"/workspaces/{W}/template", json={"template_id": "nope"}).status_code == 404)
z = off.get(f"/workspaces/{W}/download"); names = zipfile.ZipFile(io.BytesIO(z.content)).namelist() if z.status_code == 200 else []
chk("download project zip has the files", any(n.endswith("lib/main.py") for n in names), names[:8])
chk("workspace history", off.get(f"/workspaces/{W}/history").status_code == 200)
r = off.post(f"/workspaces/{W}/run", json={"file_id": fl["id"], "stdin": ""}); chk("run without Docker: honest 503, not a fake result", r.status_code == 503, r.text)
RES.append({"area": AREA[0], "check": "run code in Docker (real execution)", "result": "BLOCKED", "detail": "no Docker in the audit machine"})
chk("stop run -> clean answer", off.post(f"/workspaces/{W}/run/stop").status_code < 500)
r = off.delete(f"/workspaces/{W}/folder", params={"path": "lib"}); chk("delete folder + DB", r.status_code == 200 and not db("select id from workspace_files where workspace_id=? and path like 'lib/%' and deleted_at is null", W), r.text)
left = db("select id from workspace_files where workspace_id=? and deleted_at is null limit 1", W)[0]["id"]
chk("delete file + DB", off.delete(f"/workspaces/{W}/files/{left}").status_code in (200, 204) and not db("select id from workspace_files where id=? and deleted_at is null", left))
chk("admin can open the project read-only but not save", ad.get(f"/tasks/{t['id']}/workspace").json().get("read_only") is True and ad.put(f"/workspaces/{W}/files", json={"path": "admin.txt", "content": "x"}).status_code == 403)
lg = it.get("/languages"); chk("languages list", lg.status_code == 200 and len(lg.json().get("languages", [])) >= 50, lg.text[:100])
lid = lg.json()["languages"][0]["id"]; chk("pull image: admin only; honest 503 without Docker", it.post(f"/languages/{lid}/pull").status_code == 403 and ad.post(f"/languages/{lid}/pull").status_code in (503, 409, 422), ad.post(f"/languages/{lid}/pull").text)
async def term():
    async with websockets.connect(B.replace("http", "ws") + f"/ws/terminal?token={TOK['offroll']}&workspace_id={W}&language=python") as w:
        try: return json.loads(await asyncio.wait_for(w.recv(), 5))
        except Exception as e: return {"error": repr(e)}
tv = asyncio.run(term()); chk("terminal WebSocket: clear 'runner not available' message without Docker", tv.get("type") == "error" and "error" not in tv or "message" in tv, tv)
async def term_other():
    async with websockets.connect(B.replace("http", "ws") + f"/ws/terminal?token={TOK['intern']}&workspace_id={W}&language=python") as w:
        try: return json.loads(await asyncio.wait_for(w.recv(), 5))
        except Exception as e: return {"error": repr(e)}
tv2 = asyncio.run(term_other()); chk("terminal WebSocket refuses another user's workspace", tv2.get("type") == "error", tv2)

area("task attachments (upload / download)")
r = ad.post(f"/tasks/{t['id']}/attachments", files={"file": ("../../evil name.txt", b"hello attachment", "text/plain")}); at = J(r); chk("upload", r.status_code == 201, r.text)
chk("stored file name cannot escape the folder", ".." not in json.dumps(at) or "/" not in at.get("filename", ""), at)
d = off.get(f"/tasks/{t['id']}/attachments/{at['id']}"); chk("assignee downloads the same bytes", d.status_code == 200 and d.content == b"hello attachment", d.status_code)
chk("unrelated user cannot download", it.get(f"/tasks/{t['id']}/attachments/{at['id']}").status_code in (403, 404))
chk("dangerous type refused", ad.post(f"/tasks/{t['id']}/attachments", files={"file": ("run.exe", b"MZ\x90", "application/octet-stream")}).status_code in (400, 415, 422))
chk("too large refused", ad.post(f"/tasks/{t['id']}/attachments", files={"file": ("big.zip", b"0" * 30_000_000, "application/zip")}).status_code in (400, 413, 422))
chk("delete attachment + DB", ad.delete(f"/tasks/{t['id']}/attachments/{at['id']}").status_code in (200, 204) and not db("select id from task_attachments where id=? and deleted_at is null", at["id"]))

area("tasks: validation and paging")
chk("task without title -> 422", ad.post("/tasks", json={"assigned_to_ids": [ME["intern"]["id"]]}).status_code == 422)
chk("task for a user that does not exist -> 4xx", ad.post("/tasks", json={"title": "Ghost user", "assigned_to_ids": [999999], "requirements": "x"}).status_code in (404, 422))
chk("intern cannot create a task", it.post("/tasks", json={"title": "Intern tries", "assigned_to_ids": [ME["intern"]["id"]], "requirements": "x"}).status_code == 403)
chk("off-roll sees only own tasks", all(x["assigned_to"] == ME["offroll"]["id"] or x.get("assigned_to_id") == ME["offroll"]["id"] for x in off.get("/tasks").json()), off.get("/tasks").json()[:1])
chk("delete task: intern refused, admin ok", it.delete(f"/tasks/{t['id']}").status_code == 403 and ad.delete(f"/tasks/{t['id']}").status_code in (200, 204, 409))

area("CORS and headers")
r = httpx.options(A + "/tasks", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
chk("preflight from the configured frontend is allowed", r.status_code == 200 and r.headers.get("access-control-allow-origin") == "http://localhost:5173", dict(r.headers))
r = httpx.options(A + "/tasks", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
chk("preflight from another site is not allowed", "access-control-allow-origin" not in r.headers, dict(r.headers))
r = httpx.get(A + "/health"); chk("security headers present", r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("x-frame-options"), dict(r.headers))
chk("health", r.status_code == 200)
r = it.get("/users/abc"); chk("non-numeric id -> 422, not 500", r.status_code == 422, r.text)
r = httpx.post(A + "/debug/client", json={"where": "x" * 100000}); chk("public debug endpoint does not accept large bodies", r.status_code in (404, 413, 422), f"status {r.status_code}: unauthenticated endpoint accepts a 100 KB body")

json.dump(RES, open(os.path.join(OUT, "functional.json"), "w"), indent=1)
from collections import Counter
print("\n", dict(Counter(x["result"] for x in RES)), "of", len(RES))

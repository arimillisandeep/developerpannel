"""API audit step 2: authentication + authorization matrix over REAL HTTP, on an isolated test database.

Start a throwaway server first (never point this at real data; it creates and tries to change records):
    DATABASE_URL=sqlite:////tmp/audit/audit.db STORAGE_DIR=/tmp/audit/storage alembic upgrade head && python -m app.demo_seed
    ... uvicorn app.main:app --port 8010
    python scripts/audit_inventory.py && python scripts/audit_matrix.py
Writes ../audit/matrix.json. A check is only PASS when the request was really sent and the status was the expected one.
"""
import json, os, re, time
import httpx
B = os.environ.get("AUDIT_API", "http://127.0.0.1:8010")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "audit")
routes = [r for r in json.load(open(os.path.join(OUT, "routes.json"))) if r["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE") and r["path"].startswith("/api")]
PUBLIC = {"POST /api/auth/login", "GET /api/health", "POST /api/debug/client"}

def login(e, pw="Workcode@123"):
    r = httpx.post(B + "/api/auth/login", json={"email": e, "password": pw}); r.raise_for_status()
    return httpx.Client(base_url=B, headers={"Authorization": "Bearer " + r.json()["access_token"]}, timeout=30), r.json()
C = {}; ME = {}
for k in ("admin", "reviewer", "onroll", "offroll", "intern"):
    C[k], _ = login(k + "@workcode.local"); ME[k] = C[k].get("/api/auth/me").json()
ad, intern = C["admin"], C["intern"]

# ---- fixtures: everything below belongs to the INTERN (reviewer = reviewer@) ----
t = ad.post("/api/tasks", json={"title": "Audit fixture", "assigned_to_ids": [ME["intern"]["id"]], "reviewer_id": ME["reviewer"]["id"], "requirements": "x"}).json()["created"][0]
att = ad.post(f"/api/tasks/{t['id']}/attachments", files={"file": ("spec.txt", b"spec", "text/plain")}).json()
intern.post(f"/api/tasks/{t['id']}/accept"); intern.post(f"/api/tasks/{t['id']}/start")
ws = intern.get(f"/api/tasks/{t['id']}/workspace").json()
f = intern.put(f"/api/workspaces/{ws['id']}/files", json={"path": "index.html", "content": "<h1>one</h1>\n", "manual": True}).json()["file"]
intern.put(f"/api/workspaces/{ws['id']}/files", json={"path": "index.html", "content": "<h1>two</h1>\n", "manual": True})
intern.put(f"/api/workspaces/{ws['id']}/files", json={"path": "src/a.js", "content": "let a = 1\n", "manual": True})
vers = intern.get(f"/api/workspaces/{ws['id']}/files/{f['id']}/versions").json()
# a second task of the intern that is already submitted (for submission routes)
t2 = ad.post("/api/tasks", json={"title": "Audit fixture 2", "assigned_to_ids": [ME["intern"]["id"]], "reviewer_id": ME["reviewer"]["id"], "requirements": "x"}).json()["created"][0]
intern.post(f"/api/tasks/{t2['id']}/accept"); intern.post(f"/api/tasks/{t2['id']}/start")
ws2 = intern.get(f"/api/tasks/{t2['id']}/workspace").json()
intern.put(f"/api/workspaces/{ws2['id']}/files", json={"path": "main.py", "content": "print(1)\n", "manual": True})
sub = intern.post(f"/api/workspaces/{ws2['id']}/submit", json={"note": "audit"}).json()
aiconv = intern.post("/api/ai/conversations", json={"workspace_id": ws["id"]}).json()
chat = intern.post("/api/chat/conversations", json={"kind": "direct", "user_ids": [ME["reviewer"]["id"]]}).json()
intern.post(f"/api/chat/conversations/{chat['id']}/messages", json={"body": "hello"})
notes = intern.get("/api/notifications").json(); notes = notes if isinstance(notes, list) else notes.get("items", [])
rec = intern.post("/api/recordings/start", json={"consent": True, "mime_type": "video/webm"}).json()
intern.post(f"/api/recordings/{rec['id']}/chunk", content=b"\x1aE\xdf\xa3fakewebm", headers={"Content-Type": "application/octet-stream"})
intern.post(f"/api/recordings/{rec['id']}/stop")
meet = C["reviewer"].post("/api/meetings", json={"title": "Audit", "starts_at": "2030-01-01T10:00:00Z", "participant_ids": [ME["intern"]["id"]]}).json()
teams = ad.get("/api/teams").json()
site = ad.post("/api/timer/allowlist", json={"domain": "audit-example.com", "label": "Audit"}).json()
prov = ad.post("/api/ai/providers", json={"name": "Audit provider", "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-audit-secret-key", "models": ["m1"]}).json()
langs = ad.get("/api/languages").json(); lang_id = (langs.get("languages") or [{}])[0].get("id", "python")
FIX = {"task": t, "att": att, "ws": ws, "file": f, "vers": vers[:2], "sub": sub, "aiconv": aiconv, "chat": chat, "rec": rec, "meet": meet, "site": site, "prov": prov}
print("fixtures:", {k: (v.get("id") if isinstance(v, dict) else len(v)) for k, v in FIX.items()}, "notifications:", len(notes))

def ids(path, real=True):
    """Fill path parameters with the intern's real resources (or with ids that do not exist)."""
    ai = path.startswith("/api/ai")
    m = {"task_id": t["id"], "attachment_id": att.get("id"), "ws_id": ws["id"], "file_id": f["id"], "version_id": vers[-1]["id"] if vers else 1,
         "sub_id": sub.get("id"), "conv_id": aiconv["id"] if ai else chat["id"], "message_id": 1, "notification_id": notes[0]["id"] if notes else 1,
         "rec_id": rec["id"], "meeting_id": meet.get("id"), "user_id": ME["intern"]["id"], "team_id": teams[0]["id"] if teams else 1,
         "site_id": site.get("id"), "provider_id": prov.get("id"), "lang_id": lang_id}
    return re.sub(r"\{(\w+)\}", lambda x: str(m.get(x.group(1), 1) if real else 999999), path)

BODY = {   # a VALID body per mutating route, so the request reaches the permission check instead of stopping at 422
 "POST /api/auth/change-password": {"current_password": "wrong-password-1", "new_password": "Another@12345"},
 "POST /api/users": {"email": "audit-new@workcode.local", "password": "Workcode@123", "full_name": "Audit New", "role": "intern"},
 "PATCH /api/users/{user_id}": {"phone": "9999999999"},
 "POST /api/users/{user_id}/deactivate": {"reason": "audit"},
 "POST /api/users/{user_id}/convert": {"to_role": "offroll", "reason": "audit", "confirm_early": True},
 "POST /api/departments": {"name": "Audit dept"}, "POST /api/projects": {"name": "Audit project"}, "POST /api/teams": {"name": "Audit team"},
 "PATCH /api/teams/{team_id}": {"name": "Renamed by audit"}, "POST /api/teams/{team_id}/members": {"user_id": 1},
 "PUT /api/intern-vacancy": {"target_headcount": 11},
 "POST /api/tasks": {"title": "Made by audit matrix", "assigned_to_ids": [1], "requirements": "x"},
 "PATCH /api/tasks/{task_id}": {"title": "Changed by audit"},
 "PUT /api/workspaces/{ws_id}/files": {"path": "hacked.txt", "content": "x", "manual": True},
 "POST /api/workspaces/{ws_id}/files/{file_id}/rename": {"new_path": "renamed.html"},
 "POST /api/workspaces/{ws_id}/submit": {"note": "audit"},
 "POST /api/workspaces/{ws_id}/move": {"from_path": "src/a.js", "to_path": "src/b.js"},
 "POST /api/workspaces/{ws_id}/copy": {"from_path": "src/a.js", "to_path": "src/c.js"},
 "POST /api/workspaces/{ws_id}/template": {"template_id": "html-css-js", "overwrite": False},
 "POST /api/workspaces/{ws_id}/run": {"file_id": 1, "stdin": ""},
 "POST /api/submissions/{sub_id}/review": {"decision": "approved", "comment": "audit"},
 "POST /api/submissions/{sub_id}/comments": {"body": "audit comment", "comment": "audit comment"},
 "POST /api/submissions/{sub_id}/run": {"path": "main.py", "stdin": ""},
 "POST /api/sessions/start": {"client_id": "audit-client-1"}, "POST /api/sessions/heartbeat": {"client_id": "audit-client-1", "state": "active"},
 "POST /api/meetings": {"title": "M", "starts_at": "2030-01-01T10:00:00Z", "participant_ids": [1]},
 "POST /api/chat/conversations": {"kind": "direct", "user_ids": [1]},
 "POST /api/chat/conversations/{conv_id}/messages": {"body": "audit"},
 "POST /api/recordings/start": {"consent": True},
 "POST /api/timer/allowlist": {"domain": "audit2-example.com", "label": "x"},
 "POST /api/extension/report": {"category": "workcode", "domain": "x.com"},
 "POST /api/ai/providers": {"name": "P2", "base_url": "http://127.0.0.1:9/v1"}, "PATCH /api/ai/providers/{provider_id}": {"name": "P3"},
 "PUT /api/ai/settings": {"max_output_tokens": 4000},
 "POST /api/ai/conversations": {}, "PATCH /api/ai/conversations/{conv_id}": {"title": "renamed"},
 "POST /api/ai/conversations/{conv_id}/messages": {"content": "hi"}, "POST /api/ai/conversations/{conv_id}/regenerate": {},
 "PATCH /api/ai/messages/{message_id}": {"saved": True},
 "POST /api/ai/patch/preview": {"workspace_id": ws["id"], "changes": [{"path": "x.txt", "content": "x"}]},
 "POST /api/ai/patch/apply": {"workspace_id": ws["id"], "changes": [{"path": "hacked-by-ai.txt", "content": "x"}]},
 "POST /api/debug/client": {"where": "audit"},
}
QUERY = {"DELETE /api/workspaces/{ws_id}/folder": {"path": "src"}, "GET /api/tasks/{task_id}/compare": {"a": sub.get("id"), "b": sub.get("id")}}

EXT = {}
def call(c, r, real=True, body=True):
    key = r["method"] + " " + r["path"]; url = ids(r["path"], real)
    kw = {"params": QUERY.get(key)}
    if r["method"] in ("POST", "PUT", "PATCH"):
        if key == "POST /api/tasks/{task_id}/attachments": kw["files"] = {"file": ("x.txt", b"x", "text/plain")}
        elif key == "POST /api/recordings/{rec_id}/chunk": kw["content"] = b"x"
        elif body: kw["json"] = BODY.get(key, {})
    if c is not None and c is not bad and r["path"] in ("/api/extension/config", "/api/extension/report"):
        # these two take the browser-extension token (from POST /api/extension/token), not the login token
        if id(c) not in EXT:
            EXT[id(c)] = httpx.Client(base_url=B, headers={"Authorization": "Bearer " + c.post("/api/extension/token").json()["token"]}, timeout=30)
        c = EXT[id(c)]
    t0 = time.time()
    try: resp = (c or httpx).request(r["method"], (B if c is None else "") + url, **kw) if c is None else c.request(r["method"], url, **kw)
    except Exception as e: return {"status": -1, "ms": 0, "err": type(e).__name__ + ": " + str(e)[:80]}
    return {"status": resp.status_code, "ms": round((time.time() - t0) * 1000), "body": resp.text[:160]}

res = {}
def note(key, name, got, ok, why=""):
    res.setdefault(key, {})[name] = {"status": got["status"], "ms": got["ms"], "result": "PASS" if ok else "FAIL", "why": "" if ok else (why + " | " + got.get("body", got.get("err", "")))[:240]}

# 1. no token / broken token / token signed with another secret
bad = httpx.Client(base_url=B, headers={"Authorization": "Bearer not.a.token"}, timeout=30)
for r in routes:
    key = r["method"] + " " + r["path"]
    g = call(None, r)
    note(key, "no_token", g, (g["status"] in (401, 403)) if key not in PUBLIC else g["status"] < 500, "expected 401 without a token")
    if key not in PUBLIC:
        g = call(bad, r); note(key, "bad_token", g, g["status"] == 401, "expected 401 with a broken token")

# 2. outsider: an Off-Roll user and another On-Roll (not the reviewer) try the INTERN's resources. Nothing may succeed on a route with a path id.
OWN_OK = set()   # routes with ids that are legitimately open to these users are listed in the report instead of being silently passed
for who in ("offroll", "onroll"):
    for r in routes:
        key = r["method"] + " " + r["path"]
        if "{" not in r["path"] and key not in ("POST /api/ai/patch/preview", "POST /api/ai/patch/apply"): continue
        g = call(C[who], r)
        note(key, "outsider_" + who, g, g["status"] in (401, 403, 404, 405, 409, 410, 422, 503) and g["status"] != 500, "an unrelated user got through")

# 3. role-restricted routes: every role outside the allowed list must get 403
for r in routes:
    key = r["method"] + " " + r["path"]
    allowed = next((set(d[4:-1].split(",")) for d in r["deps"] if d.startswith("dep(")), None)
    if not allowed: continue
    for who in ("reviewer", "offroll", "intern"):
        role = ME[who]["role"]
        if role in allowed: continue
        g = call(C[who], r, real=False); note(key, "role_" + role, g, g["status"] == 403, "expected 403 for role " + role)

# 4. every role: ids that do not exist and empty bodies must give a clean 4xx, never a 5xx
for who in ("admin", "reviewer", "offroll", "intern"):
    for r in routes:
        key = r["method"] + " " + r["path"]
        if key in ("POST /api/auth/logout",): continue
        if "{" in r["path"]:
            g = call(C[who], r, real=False); note(key, "missing_id_" + who, g, 400 <= g["status"] < 500 or g["status"] == 503, "expected 4xx for an id that does not exist")
        if r["method"] in ("POST", "PUT", "PATCH") and r["body"]:
            g = call(C[who], r, real=False, body=False)
            g2 = (C[who]).request(r["method"], ids(r["path"], False), content=b"{not json", headers={"Content-Type": "application/json"})
            note(key, "empty_body_" + who, g, g["status"] < 500, "5xx on an empty body")
            note(key, "broken_json_" + who, {"status": g2.status_code, "ms": 0, "body": g2.text[:160]}, g2.status_code < 500, "5xx on broken JSON")

# 5. every role: plain GET of every list route (no ids) must answer without a 5xx
for who in ("admin", "reviewer", "onroll", "offroll", "intern"):
    for r in routes:
        if r["method"] != "GET" or "{" in r["path"]: continue
        g = call(C[who], r); note(r["method"] + " " + r["path"], "get_" + who, g, g["status"] in (200, 403), "list route failed")

# the outsider attempts must not have changed the intern's project
files_after = {x["path"]: x["content"] for x in intern.get(f"/api/tasks/{t['id']}/workspace").json()["files"]}
intact = files_after.get("index.html") == "<h1>two</h1>\n" and "hacked.txt" not in files_after and "hacked-by-ai.txt" not in files_after and "src/a.js" in files_after and "renamed.html" not in files_after
task_after = ad.get(f"/api/tasks/{t['id']}").json()
print("intern's project untouched by outsiders:", intact, "| task title untouched:", task_after["title"] == "Audit fixture", "| submission still waiting:", ad.get(f"/api/submissions/{sub['id']}").json().get("status"))
json.dump({"results": res, "intact": intact, "fixtures": {k: (v.get("id") if isinstance(v, dict) else None) for k, v in FIX.items()}}, open(os.path.join(OUT, "matrix.json"), "w"), indent=1)
tot = sum(len(v) for v in res.values()); fails = [(k, n, x) for k, v in res.items() for n, x in v.items() if x["result"] == "FAIL"]
print(f"routes probed: {len(res)} | checks: {tot} | failed: {len(fails)}")
for k, n, x in fails: print("FAIL", k, n, x["status"], x["why"][:200])
slow = sorted(((x["ms"], k, n) for k, v in res.items() for n, x in v.items()), reverse=True)[:8]; print("slowest:", slow)

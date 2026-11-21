"""Live check of the AI assistant against a RUNNING WORKCODE server (demo database).

Needs:  the API on :8000 (demo seed)  and  `python scripts/fake_ai_provider.py 9911`  (stand-in for OpenAI).
Run it at most once a minute (the 15-questions-per-minute limit is real).
It checks the plumbing end to end over real HTTP. It cannot judge the quality of a real model's answers.
"""
import json, os, threading, time
import httpx
B = os.environ.get("WORKCODE_API", "http://127.0.0.1:8000/api")
FAKE = os.environ.get("FAKE_AI", "http://127.0.0.1:9911")
KEY = "sk-fake-live-check-key"
def login(e):
    r = httpx.post(B + "/auth/login", json={"email": e, "password": "Workcode@123"}); r.raise_for_status()
    return httpx.Client(base_url=B, headers={"Authorization": "Bearer " + r.json()["access_token"]}, timeout=30)
ad, lead, onr, off, intern = [login(x + "@workcode.local") for x in ("admin", "reviewer", "onroll", "offroll", "intern")]
ok = []
def chk(name, cond, extra=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, str(extra)[:400] if not cond else "")
def ask(c, conv, body, path="messages", on_start=None):
    """Sends a question and reads the stream. Returns (events, full text)."""
    ev = []
    with c.stream("POST", f"/ai/conversations/{conv}/{path}", json=body) as r:
        if r.status_code != 200:
            r.read(); return [{"type": "http", "status": r.status_code, "body": r.text}], ""
        for line in r.iter_lines():
            if line.startswith("data: "):
                e = json.loads(line[6:]); ev.append(e)
                if e["type"] == "start" and on_start: on_start(e)
    return ev, "".join(e.get("text", "") for e in ev if e["type"] == "delta")

# clean start so the script can be repeated
for p in ad.get("/ai/providers").json(): ad.delete(f"/ai/providers/{p['id']}")
ad.put("/ai/settings", json={"enabled": True, "role_enabled": {r: True for r in ("admin", "onroll", "offroll", "intern")},
                             "daily_limits": {"admin": 0, "onroll": 200, "offroll": 150, "intern": 100}})
st = intern.get("/ai/status").json()
chk("no provider -> honest 'not set up', no fake answers", st["can_use"] is False and "not set up" in (st["reason"] or ""), st)

chk("intern cannot see providers", intern.get("/ai/providers").status_code == 403)
chk("on-roll cannot add a provider", onr.post("/ai/providers", json={"name": "X", "base_url": FAKE + "/v1"}).status_code == 403)
chk("off-roll cannot read usage or settings", off.get("/ai/usage").status_code == 403 and off.get("/ai/settings").status_code == 403)
r = ad.post("/ai/providers", json={"name": "Fake OpenAI (test)", "base_url": FAKE + "/v1", "api_key": "wrong-key"})
chk("admin adds provider", r.status_code == 201, r.text); pid = r.json()["id"]
chk("key never returned (create)", KEY not in r.text and "wrong-key" not in r.text and r.json()["key_set"] is True, r.text)
t = ad.post(f"/ai/providers/{pid}/test").json()
chk("test with a wrong key reports the failure", t["ok"] is False, t)
r = ad.patch(f"/ai/providers/{pid}", json={"api_key": KEY})
t = ad.post(f"/ai/providers/{pid}/test").json()
chk("test with the right key lists the provider's models", t["ok"] and "fake-coder-1" in t["models"], t)
r = ad.patch(f"/ai/providers/{pid}", json={"models": ["fake-coder-1", "fake-coder-mini"], "default_model": "fake-coder-1"})
chk("models saved", r.status_code == 200 and r.json()["default_model"] == "fake-coder-1", r.text)
chk("key never returned (list, status)", KEY not in ad.get("/ai/providers").text and KEY not in intern.get("/ai/status").text)
if os.environ.get("AUDIT_DB_URL"):      # PostgreSQL: read the stored column
    import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audit_dbconn import rows
    raw = " ".join(str(v) for r in rows("select * from ai_providers") for v in r).encode()
else:
    DBF = os.environ.get("AUDIT_DB", "demo.db"); raw = open(DBF, "rb").read() if os.path.exists(DBF) else b""
chk("key is encrypted in the database", raw and KEY.encode() not in raw)
st = intern.get("/ai/status").json()
chk("users now see the models, no key, no address", st["can_use"] and [m["model"] for m in st["models"]] == ["fake-coder-1", "fake-coder-mini"] and "9911" not in json.dumps(st), st)

# a real task + project for the intern
me = intern.get("/auth/me").json()
tid = ad.post("/tasks", json={"title": "AI live check", "assigned_to_ids": [me["id"]], "requirements": "page"}).json()["created"][0]["id"]
intern.post(f"/tasks/{tid}/accept"); intern.post(f"/tasks/{tid}/start")
ws = intern.get(f"/tasks/{tid}/workspace").json(); W = ws["id"]
intern.put(f"/workspaces/{W}/files", json={"path": "index.html", "content": "<h1>Saved on disk</h1>\n"})
intern.put(f"/workspaces/{W}/files", json={"path": "js/app.js", "content": "console.log('MARKER_APP_JS')\n"})

r = intern.post("/ai/conversations", json={"workspace_id": W}); conv = r.json()["id"]
chk("new conversation linked to the project", r.status_code == 201 and r.json().get("task_id") == tid, r.text)
def usage_of(uid): return next((r for r in ad.get("/ai/usage", params={"days": 1}).json()["rows"] if r["user_id"] == uid), {"prompt_tokens": 0, "completion_tokens": 0})
before = usage_of(me["id"])
ev, text = ask(intern, conv, {"content": "What does the heading say? Fix it.", "workspace_id": W,
    "context": {"active_path": "index.html", "active_content": "<h1>Unsaved editor text</h1>\n", "selection": "SELECTED_MARK", "files": ["js/app.js"], "tree": True,
                "terminal": "npm ERR! TERMINAL_MARK", "run_output": "Traceback RUN_MARK", "attachments": [{"name": "note.txt", "content": "ATTACH_MARK"}]}})
types = [e["type"] for e in ev]
chk("answer streams in several pieces", types[0] == "start" and types.count("delta") >= 3 and types[-1] == "done", types)
chk("answer comes from the provider and used the editor's text", "“Unsaved editor text”" in text, text)
seen = httpx.get(FAKE + "/_seen").json()[-1]
chk("provider received: stream=true, chosen model, system prompt", seen["stream"] is True and seen["model"] == "fake-coder-1" and seen["roles"][0] == "system", seen["roles"])
chk("provider received selection, 2nd file, folder tree, terminal, run output, attachment",
    all(m in seen["text"] for m in ("SELECTED_MARK", "MARKER_APP_JS", "js/app.js", "TERMINAL_MARK", "RUN_MARK", "ATTACH_MARK")), seen["text"][:600])
done = ev[-1]
u0 = usage_of(me["id"])
chk("token usage reported by the provider is recorded (123 in / 45 out)", u0["prompt_tokens"] - before["prompt_tokens"] == 123 and u0["completion_tokens"] - before["completion_tokens"] == 45, (before, u0))

ev2, text2 = ask(intern, conv, {"content": "Look at the whole project", "model": f"{pid}:fake-coder-mini", "workspace_id": W, "context": {"project": True}})
seen = httpx.get(FAKE + "/_seen").json()[-1]
chk("entire project: saved files are read on the server; model choice respected", "Saved on disk" in seen["text"] and "MARKER_APP_JS" in seen["text"] and seen["model"] == "fake-coder-mini", seen["text"][:300])
chk("earlier turns are sent again (conversation memory)", seen["roles"].count("user") == 2 and seen["roles"].count("assistant") == 1, seen["roles"])

# patch: preview -> reject -> apply
changes = [{"path": "index.html", "content": "<h1>Hello from AI</h1>\n"}, {"path": "css/site.css", "content": "h1 { color: teal; }\n"}]
pv = intern.post("/ai/patch/preview", json={"workspace_id": W, "changes": changes}).json()
chk("preview: 1 modified + 1 new, with real diff lines", [f["status"] for f in pv["files"]] == ["modified", "new"] and "-<h1>Saved on disk</h1>" in pv["files"][0]["diff"] and "+<h1>Hello from AI</h1>" in pv["files"][0]["diff"] and pv["can_apply"], pv)
files = {f["path"]: f["content"] for f in intern.get(f"/tasks/{tid}/workspace").json()["files"]}
chk("preview / reject writes nothing", files["index.html"] == "<h1>Saved on disk</h1>\n" and "css/site.css" not in files)
ap = intern.post("/ai/patch/apply", json={"workspace_id": W, "changes": changes[:1]}).json()
files = {f["path"]: f for f in intern.get(f"/tasks/{tid}/workspace").json()["files"]}
chk("accepted file is really saved; rejected file is not created", [f["path"] for f in ap["applied"]] == ["index.html"] and files["index.html"]["content"] == "<h1>Hello from AI</h1>\n" and "css/site.css" not in files, ap)
vs = intern.get(f"/workspaces/{W}/files/{files['index.html']['id']}/versions")
chk("version history keeps the old text and marks the AI change", vs.status_code == 200 and vs.json()[0]["kind"] == "ai" and any("Saved on disk" in (v.get("content") or "") or v["kind"] != "ai" for v in vs.json()[1:]), vs.text[:300])
ap = intern.post("/ai/patch/apply", json={"workspace_id": W, "changes": changes}).json()
chk("multi-file apply creates the new file in a new folder", [f["path"] for f in ap["applied"]] == ["css/site.css"] and ap["unchanged"] == 1, ap)
chk("path escape refused", intern.post("/ai/patch/apply", json={"workspace_id": W, "changes": [{"path": "../../etc/passwd", "content": "x"}]}).status_code in (400, 422))

# privacy and project permissions
chk("off-roll cannot read the intern's conversation", off.get(f"/ai/conversations/{conv}").status_code == 404)
chk("admin cannot read it either", ad.get(f"/ai/conversations/{conv}").status_code == 404)
chk("other users do not see it in their list", all(c["id"] != conv for c in off.get("/ai/conversations").json() + ad.get("/ai/conversations").json()))
oc = off.post("/ai/conversations", json={}).json()["id"]
n = len(httpx.get(FAKE + "/_seen").json())
ev, _ = ask(off, oc, {"content": "show me", "workspace_id": W, "context": {"project": True}})
chk("off-roll cannot pull the intern's project into a question", ev[0].get("status") in (403, 404) and len(httpx.get(FAKE + "/_seen").json()) == n, ev)
chk("off-roll cannot preview or apply on the intern's project", off.post("/ai/patch/preview", json={"workspace_id": W, "changes": changes}).status_code in (403, 404) and off.post("/ai/patch/apply", json={"workspace_id": W, "changes": changes}).status_code in (403, 404))
chk("admin may look (preview) but cannot write into someone's project", ad.post("/ai/patch/preview", json={"workspace_id": W, "changes": changes}).json().get("can_apply") is False and ad.post("/ai/patch/apply", json={"workspace_id": W, "changes": [{"path": "x.txt", "content": "x"}]}).status_code in (403, 409))

# history
chk("auto title from the first question", intern.get(f"/ai/conversations/{conv}").json()["title"].startswith("What does the heading"))
chk("rename", intern.patch(f"/ai/conversations/{conv}", json={"title": "Heading fix"}).json()["title"] == "Heading fix")
chk("search by text finds it; nonsense finds nothing", any(c["id"] == conv for c in intern.get("/ai/conversations", params={"q": "whole project"}).json()) and intern.get("/ai/conversations", params={"q": "zzqq"}).json() == [])
chk("filter by project", any(c["id"] == conv for c in intern.get("/ai/conversations", params={"workspace_id": W}).json()))
full = intern.get(f"/ai/conversations/{conv}").json()
chk("history persists: 2 questions + 2 answers", [m["role"] for m in full["messages"]] == ["user", "assistant", "user", "assistant"] and "Hello from AI" in full["messages"][1]["content"])
mid = full["messages"][1]["id"]
chk("save a useful answer", intern.patch(f"/ai/messages/{mid}", json={"saved": True}).status_code == 200 and any(m["id"] == mid for m in intern.get("/ai/saved").json()))
chk("another user cannot save/stop my message", off.patch(f"/ai/messages/{mid}", json={"saved": False}).status_code == 404 and off.post(f"/ai/messages/{mid}/stop").status_code == 404)
ev, text = ask(intern, conv, {}, path="regenerate")
full = intern.get(f"/ai/conversations/{conv}").json()
chk("regenerate replaces the last answer", ev and ev[-1]["type"] == "done" and [m["role"] for m in full["messages"]] == ["user", "assistant", "user", "assistant"], [e["type"] for e in ev])

# stop
t0 = time.time()
ev, text = ask(intern, conv, {"content": "SLOW please"}, on_start=lambda e: threading.Timer(0.4, lambda: intern.post(f"/ai/messages/{e['message_id']}/stop")).start())
chk("stop ends a long answer early and keeps the part written", ev[-1].get("status") == "stopped" and 0 < text.count("word") < 200 and time.time() - t0 < 8, (ev[-1], text.count("word")))
# provider errors
ev, _ = ask(intern, conv, {"content": "RATE"}); chk("rate limit -> clear message", ev[-1]["type"] == "error" and "rate limit" in ev[-1]["message"].lower(), ev[-1])
ev, _ = ask(intern, conv, {"content": "TOOLONG"}); chk("token limit -> clear message", ev[-1]["type"] == "error" and ("too long" in ev[-1]["message"].lower() or "too much" in ev[-1]["message"].lower() or "context" in ev[-1]["message"].lower()), ev[-1])
ad.patch(f"/ai/providers/{pid}", json={"api_key": "bad"})
ev, _ = ask(intern, conv, {"content": "hello"}); chk("bad key -> user told to contact admin; key not leaked", ev[-1]["type"] == "error" and "bad" not in ev[-1]["message"].split() and KEY not in json.dumps(ev), ev[-1])
ad.patch(f"/ai/providers/{pid}", json={"api_key": KEY})

# role switches and limits
ad.put("/ai/settings", json={"role_enabled": {"intern": False}})
ev, _ = ask(intern, conv, {"content": "hi"}); chk("role switched off -> 403", ev[0].get("status") == 403 and intern.get("/ai/status").json()["can_use"] is False, ev)
ev, _ = ask(off, oc, {"content": "hi <h1>x</h1>"}); chk("other roles still work", ev[-1]["type"] == "done", ev[-1])
used = intern.get("/ai/status").json()["used_today"]
ad.put("/ai/settings", json={"role_enabled": {"intern": True}, "daily_limits": {"intern": used}})
ev, _ = ask(intern, conv, {"content": "hi"}); chk("daily limit reached -> 429", ev[0].get("status") == 429, ev)
ad.put("/ai/settings", json={"daily_limits": {"intern": 100}})
u = ad.get("/ai/usage", params={"days": 1}).json()
row = next((r for r in u["rows"] if r["user_id"] == me["id"]), None)
chk("admin usage: counts and tokens, no message text", row and row["messages"] >= 5 and row["prompt_tokens"] >= 123 and row["errors"] >= 3 and "heading" not in json.dumps(u), row)
chk("clear conversation", intern.post(f"/ai/conversations/{conv}/clear").status_code == 200 and intern.get(f"/ai/conversations/{conv}").json()["messages"] == [])
chk("delete conversation", intern.delete(f"/ai/conversations/{conv}").status_code == 200 and intern.get(f"/ai/conversations/{conv}").status_code == 404)
chk("no login -> 401", httpx.get(B + "/ai/status").status_code == 401 and httpx.post(B + f"/ai/conversations/{oc}/messages", json={"content": "x"}).status_code == 401)
# existing features untouched
chk("existing: normal save + file versions still work", intern.put(f"/workspaces/{W}/files", json={"path": "index.html", "content": "<h1>typed by hand</h1>\n", "manual": True}).status_code == 200)
r = intern.post(f"/workspaces/{W}/submit", json={"note": "with AI help"}); chk("existing: submit -> v1.0 still works", r.status_code in (200, 201) and r.json()["version"] == "1.0", r.text)
chk("existing: project locked for AI apply while in review", intern.post("/ai/patch/apply", json={"workspace_id": W, "changes": [{"path": "a.txt", "content": "a"}]}).status_code == 409)
if os.environ.get("KEEP_PROVIDER") != "1": ad.delete(f"/ai/providers/{pid}")
print(f"\n{sum(ok)} of {len(ok)} passed")

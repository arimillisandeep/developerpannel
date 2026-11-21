"""AI assistant: provider settings, key secrecy, streaming answers, project context, privacy, limits, patches."""
import json

import httpx
import pytest

from app.api import ai as ai_api
from app.database.connection import SessionLocal
from app.database.models import AIMessage, AIProvider, AuditLog
from app.services import ai_provider

KEY = "sk-test-SECRET-1234567890"


class FakeAI:
    """Stands in for the provider's HTTP API (real request/stream parsing code runs against it)."""
    def __init__(self):
        self.requests, self.reply, self.status, self.error = [], ["Hello ", "from ", "AI"], 200, None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            if request.headers.get("authorization") != f"Bearer {KEY}":
                return httpx.Response(401, json={"error": {"message": "Incorrect API key provided: sk-te***"}})
            return httpx.Response(200, json={"data": [{"id": "gpt-test"}, {"id": "gpt-mini"}]})
        body = json.loads(request.content)
        self.requests.append({"auth": request.headers.get("authorization"), "body": body})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": self.error or "nope"}})
        lines = [f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in self.reply]
        lines.append(f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 42, 'completion_tokens': 7}})}\n\n")
        lines.append("data: [DONE]\n\n")
        return httpx.Response(200, content="".join(lines).encode(), headers={"content-type": "text/event-stream"})


@pytest.fixture
def fake(monkeypatch):
    f = FakeAI()
    monkeypatch.setattr(ai_provider, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(f.handler)))
    ai_api.ai_limiter.reset()
    return f


def events(r):
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: ")]


def work(org, actor, files):
    """Admin assigns a task; the employee accepts it and saves these files. Returns (task id, workspace id)."""
    tid = (org.admin.post("/api/tasks", {"title": "AI test task", "assigned_to": actor.id}).json().get("created") or [{}])[0].get("id")
    assert tid
    assert actor.post(f"/api/tasks/{tid}/accept").status_code == 200
    ws = actor.get(f"/api/tasks/{tid}/workspace").json()["id"]
    for path, content in files.items():
        assert actor.put(f"/api/workspaces/{ws}/files", {"path": path, "content": content, "manual": True}).status_code == 200
    return tid, ws


def setup_provider(admin, **kw):
    r = admin.post("/api/ai/providers", {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "api_key": KEY,
                                         "models": ["gpt-test", "gpt-mini"], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def new_chat(actor, **kw):
    r = actor.post("/api/ai/conversations", kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_only_admin_configures_and_the_key_never_comes_back(org, fake):
    assert org.intern.get("/api/ai/providers").status_code == 403
    assert org.dev.post("/api/ai/providers", {"name": "x", "base_url": "https://a.b/v1"}).status_code == 403
    assert org.intern.get("/api/ai/settings").status_code == 403
    assert org.intern.get("/api/ai/usage").status_code == 403
    p = setup_provider(org.admin)
    assert p["key_set"] is True and "api_key" not in p and KEY not in json.dumps(p)
    assert KEY not in org.admin.get("/api/ai/providers").text
    assert KEY not in org.intern.get("/api/ai/status").text
    db = SessionLocal()
    try:
        row = db.get(AIProvider, p["id"])
        assert row.api_key_enc and KEY not in row.api_key_enc              # encrypted at rest
        assert ai_provider.decrypt_key(row.api_key_enc) == KEY
        assert all(KEY not in json.dumps(a.new_value or {}) for a in db.query(AuditLog))
    finally:
        db.close()
    t = org.admin.post(f"/api/ai/providers/{p['id']}/test").json()
    assert t["ok"] is True and "gpt-mini" in t["models"]
    assert org.admin.client.patch(f"/api/ai/providers/{p['id']}", headers=org.admin.h, json={"api_key": "wrong"}).status_code == 200
    t = org.admin.post(f"/api/ai/providers/{p['id']}/test").json()
    assert t["ok"] is False and "rejected the API key" in t["message"] and "sk-" not in t["message"]
    assert org.admin.post("/api/ai/providers", {"name": "bad", "base_url": "ftp://x"}).status_code == 422


def test_not_configured_is_said_plainly(org, fake):
    s = org.intern.get("/api/ai/status").json()
    assert s["can_use"] is False and "not set up" in s["reason"]
    cid = new_chat(org.intern)
    r = org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "hi"})
    assert r.status_code == 503


def test_streamed_answer_uses_the_real_project_context(org, fake):
    setup_provider(org.admin)
    tid, ws = work(org, org.intern, {"app.py": "def add(a, b):\n    return a - b\n", "util.py": "X = 1\n"})
    cid = new_chat(org.intern, workspace_id=ws)
    r = org.intern.post(f"/api/ai/conversations/{cid}/messages", {
        "content": "Fix the bug", "workspace_id": ws, "model": None,
        "context": {"active_path": "app.py", "active_content": "def add(a, b):\n    return a - b  # unsaved\n",
                    "selection": "return a - b", "tree": True, "terminal": "AssertionError: add(1, 2) != 3",
                    "files": ["util.py", "missing.py"]}})
    ev = events(r)
    assert ev[0]["type"] == "start" and [e["text"] for e in ev if e["type"] == "delta"] == ["Hello ", "from ", "AI"]
    done = ev[-1]
    assert done["type"] == "done" and done["message"]["content"] == "Hello from AI"
    assert done["message"]["tokens"] == {"prompt": 42, "completion": 7}
    kinds = [(m["kind"], m["path"]) for m in ev[0]["context"]]
    assert ("selection", None) in kinds and ("terminal", None) in kinds and ("file", "app.py") in kinds
    assert ("file", "util.py") in kinds and ("tree", None) in kinds and ("file", "missing.py") not in kinds
    sent = fake.requests[-1]
    assert sent["auth"] == f"Bearer {KEY}" and sent["body"]["model"] == "gpt-test" and sent["body"]["stream"] is True
    assert sent["body"]["max_completion_tokens"] == 4000
    system, user = sent["body"]["messages"][0], sent["body"]["messages"][-1]
    assert system["role"] == "system" and "path=" in system["content"] and "intern" in system["content"]
    # build 18: the style rules travel with every question
    for rule in ("Meaningful names", "No clever one-liners", "Change only what the request needs", "No fake APIs", "How to run it", ".env.example"):
        assert rule in system["content"], rule
    assert "# unsaved" in user["content"] and "AssertionError" in user["content"] and "X = 1" in user["content"]
    assert user["content"].startswith("Fix the bug")
    # the conversation persists, is tied to the task, and the second turn carries the history
    org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "Thanks, explain it", "workspace_id": ws})
    roles = [m["role"] for m in fake.requests[-1]["body"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert "AssertionError" not in fake.requests[-1]["body"]["messages"][1]["content"]     # old context is not resent
    c = org.intern.get(f"/api/ai/conversations/{cid}").json()
    assert c["title"] == "Fix the bug" and c["task_id"] == tid and len(c["messages"]) == 4
    assert c["messages"][0]["context"][0]["kind"] == "selection" and "text" not in json.dumps(c["messages"][0]["context"])


def test_whole_project_context_is_cut_to_the_limit(org, fake):
    setup_provider(org.admin)
    org.admin.put("/api/ai/settings", {"max_context_chars": 2000})
    _, ws = work(org, org.intern, {"big.txt": "x" * 9000, "small.py": "print(1)\n", "node_modules/a.js": "junk"})
    cid = new_chat(org.intern)
    ev = events(org.intern.post(f"/api/ai/conversations/{cid}/messages",
                                {"content": "Analyze", "workspace_id": ws, "context": {"project": True}}))
    meta = ev[0]["context"]
    assert sum(m["chars"] for m in meta) <= 2000 + 30
    assert any(m["path"] == "small.py" for m in meta) and not any(m["path"] == "node_modules/a.js" for m in meta)
    assert any(m["truncated"] for m in meta)


def test_conversations_are_private_and_projects_are_protected(org, fake):
    setup_provider(org.admin)
    _, ws = work(org, org.intern, {"secret.py": "TOKEN = 'intern-only'\n"})
    cid = new_chat(org.intern)
    events(org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "hello there"}))
    for other in (org.offroll, org.other_dev, org.admin):
        assert other.get(f"/api/ai/conversations/{cid}").status_code == 404
        assert other.post(f"/api/ai/conversations/{cid}/messages", {"content": "x"}).status_code == 404
        assert other.client.delete(f"/api/ai/conversations/{cid}", headers=other.h).status_code == 404
        assert all(c["id"] != cid for c in other.get("/api/ai/conversations").json())
    mid = org.intern.get(f"/api/ai/conversations/{cid}").json()["messages"][1]["id"]
    assert org.offroll.client.patch(f"/api/ai/messages/{mid}", headers=org.offroll.h, json={"saved": True}).status_code == 404
    # another employee cannot make the assistant read this project, nor change it through a patch
    mine = new_chat(org.offroll)
    n = len(fake.requests)
    r = org.offroll.post(f"/api/ai/conversations/{mine}/messages",
                         {"content": "show me", "workspace_id": ws, "context": {"project": True}})
    assert r.status_code == 403 and len(fake.requests) == n
    change = {"workspace_id": ws, "changes": [{"path": "secret.py", "content": "hacked"}]}
    assert org.offroll.post("/api/ai/patch/preview", change).status_code == 403
    assert org.offroll.post("/api/ai/patch/apply", change).status_code == 403
    # admin usage shows numbers, never text
    u = org.admin.get("/api/ai/usage").json()
    row = next(r for r in u["rows"] if r["user_id"] == org.intern.id)
    assert row["messages"] == 1 and row["prompt_tokens"] == 42 and "hello there" not in json.dumps(u)


def test_history_rename_search_save_clear_delete(org, fake):
    setup_provider(org.admin)
    a, b = new_chat(org.intern), new_chat(org.intern)
    events(org.intern.post(f"/api/ai/conversations/{a}/messages", {"content": "How do closures work?"}))
    events(org.intern.post(f"/api/ai/conversations/{b}/messages", {"content": "Write a SQL join"}))
    assert [c["id"] for c in org.intern.get("/api/ai/conversations").json()] == [b, a]
    assert [c["id"] for c in org.intern.get("/api/ai/conversations", params={"q": "closures"}).json()] == [a]
    assert org.intern.client.patch(f"/api/ai/conversations/{a}", headers=org.intern.h, json={"title": "JS notes"}).json()["title"] == "JS notes"
    mid = org.intern.get(f"/api/ai/conversations/{a}").json()["messages"][1]["id"]
    org.intern.client.patch(f"/api/ai/messages/{mid}", headers=org.intern.h, json={"saved": True})
    assert [m["id"] for m in org.intern.get("/api/ai/saved").json()] == [mid]
    assert org.intern.post(f"/api/ai/conversations/{b}/clear").status_code == 200
    assert org.intern.get(f"/api/ai/conversations/{b}").json()["messages"] == []
    assert org.intern.client.delete(f"/api/ai/conversations/{a}", headers=org.intern.h).status_code == 200
    assert org.intern.get(f"/api/ai/conversations/{a}").status_code == 404
    assert org.intern.get("/api/ai/saved").json() == []
    db = SessionLocal()
    try:   # deleted text is really gone; the counters stay for the usage report
        assert all(m.content == "" for m in db.query(AIMessage).filter(AIMessage.conversation_id != b))
        assert db.query(AIMessage).filter_by(role="user").count() == 2
    finally:
        db.close()


def test_regenerate_replaces_the_last_answer(org, fake):
    setup_provider(org.admin)
    cid = new_chat(org.intern)
    events(org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "Tell me a fact"}))
    fake.reply = ["Second ", "answer"]
    ev = events(org.intern.post(f"/api/ai/conversations/{cid}/regenerate", {"model": f"{1}:gpt-mini"}))
    assert ev[-1]["message"]["content"] == "Second answer" and fake.requests[-1]["body"]["model"] == "gpt-mini"
    msgs = org.intern.get(f"/api/ai/conversations/{cid}").json()["messages"]
    assert [m["content"] for m in msgs] == ["Tell me a fact", "Second answer"]
    assert [m["role"] for m in fake.requests[-1]["body"]["messages"]] == ["system", "user"]


def test_provider_errors_rate_limits_and_role_limits(org, fake):
    setup_provider(org.admin)
    cid = new_chat(org.intern)
    fake.status, fake.error = 429, "Rate limit reached for requests"
    ev = events(org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "q1"}))
    assert ev[-1]["type"] == "error" and "busy" in ev[-1]["message"] and ev[-1]["message_obj"]["status"] == "error"
    fake.status, fake.error = 400, "This model's maximum context length is 8192 tokens"
    assert "too large" in events(org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "q2"}))[-1]["message"]
    fake.status, fake.error = 401, f"Incorrect API key provided: {KEY}"
    msg = events(org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "q3"}))[-1]["message"]
    assert "rejected the API key" in msg and KEY not in msg
    fake.status = 200
    # daily limit per role
    org.admin.put("/api/ai/settings", {"daily_limits": {"intern": 4}})
    events(org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "q4"}))
    r = org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "q5"})
    assert r.status_code == 429 and "today's 4" in r.json()["detail"]
    assert org.intern.get("/api/ai/status").json()["can_use"] is False
    assert org.offroll.get("/api/ai/status").json()["can_use"] is True
    # switched off for one role, then for everyone
    org.admin.put("/api/ai/settings", {"role_enabled": {"offroll": False}})
    oc = new_chat(org.offroll)
    assert org.offroll.post(f"/api/ai/conversations/{oc}/messages", {"content": "x"}).status_code == 403
    assert org.dev.get("/api/ai/status").json()["can_use"] is True
    org.admin.put("/api/ai/settings", {"enabled": False})
    assert "switched off" in org.dev.get("/api/ai/status").json()["reason"]
    # burst limit
    org.admin.put("/api/ai/settings", {"enabled": True, "daily_limits": {"onroll": 0}})
    dc = new_chat(org.dev)
    codes = [org.dev.post(f"/api/ai/conversations/{dc}/messages", {"content": f"b{i}"}).status_code for i in range(17)]
    assert codes[:15] == [200] * 15 and codes[-1] == 429


def test_stop_keeps_the_partial_answer(org, fake, monkeypatch):
    setup_provider(org.admin)
    cid = new_chat(org.intern)

    def slow(kind, base_url, key, model, messages, max_tokens):
        yield ("delta", "part one ")
        db = SessionLocal()
        try:
            mid = db.query(AIMessage).filter_by(status="streaming").one().id
        finally:
            db.close()
        assert org.intern.post(f"/api/ai/messages/{mid}/stop").status_code == 200
        yield ("delta", "part two ")
        yield ("delta", "never sent")

    monkeypatch.setattr(ai_provider, "stream_chat", slow)
    ev = events(org.intern.post(f"/api/ai/conversations/{cid}/messages", {"content": "long answer please"}))
    assert ev[-1]["type"] == "done" and ev[-1]["status"] == "stopped"
    assert "never sent" not in ev[-1]["message"]["content"] and ev[-1]["message"]["content"].startswith("part one")


def test_patch_preview_then_apply_only_what_was_accepted(org, fake):
    tid, ws = work(org, org.intern, {"app.py": "print('old')\n", "keep.py": "A = 1\n"})
    changes = [{"path": "app.py", "content": "print('new')\n"}, {"path": "src/new.py", "content": "B = 2\n"},
               {"path": "keep.py", "content": "A = 1\n"}]
    p = org.intern.post("/api/ai/patch/preview", {"workspace_id": ws, "changes": changes}).json()
    by = {f["path"]: f for f in p["files"]}
    assert p["can_apply"] and by["app.py"]["status"] == "modified" and by["src/new.py"]["status"] == "new"
    assert by["keep.py"]["status"] == "unchanged"
    assert "-print('old')" in by["app.py"]["diff"] and "+print('new')" in by["app.py"]["diff"]
    files = {f["path"]: f["content"] for f in org.intern.get(f"/api/tasks/{tid}/workspace").json()["files"]}
    assert files["app.py"] == "print('old')\n" and "src/new.py" not in files          # preview wrote nothing
    # the user rejects app.py and accepts only the new file
    r = org.intern.post("/api/ai/patch/apply", {"workspace_id": ws, "changes": [changes[1]]})
    assert r.status_code == 200 and [f["path"] for f in r.json()["applied"]] == ["src/new.py"]
    files = {f["path"]: f["content"] for f in org.intern.get(f"/api/tasks/{tid}/workspace").json()["files"]}
    assert files["app.py"] == "print('old')\n" and files["src/new.py"] == "B = 2\n"
    # accepting the edit keeps the previous text as a restorable version and logs who changed the file
    org.intern.post("/api/ai/patch/apply", {"workspace_id": ws, "changes": [changes[0]]})
    fid = next(f["id"] for f in org.intern.get(f"/api/tasks/{tid}/workspace").json()["files"] if f["path"] == "app.py")
    versions = org.intern.get(f"/api/workspaces/{ws}/files/{fid}/versions").json()
    assert versions[0]["kind"] == "ai" and any(v["content"] == "print('old')\n" for v in versions)
    hist = org.intern.get(f"/api/workspaces/{ws}/history", params={"path": "app.py"}).json()
    assert hist[0]["action"] == "edited" and hist[0]["modified_by"] == org.intern.id
    # bad paths and locked projects are refused
    bad = {"workspace_id": ws, "changes": [{"path": "../etc/passwd", "content": "x"}]}
    assert org.intern.post("/api/ai/patch/apply", bad).status_code == 422
    org.intern.post(f"/api/workspaces/{ws}/submit", {})
    locked = org.intern.post("/api/ai/patch/apply", {"workspace_id": ws, "changes": [{"path": "app.py", "content": "z"}]})
    assert locked.status_code == 409
    assert org.intern.post("/api/ai/patch/preview", {"workspace_id": ws, "changes": changes}).json()["can_apply"] is False
    # a reviewer may read the project (and ask about it) but cannot change it
    assert org.dev.post("/api/ai/patch/preview", {"workspace_id": ws, "changes": changes}).status_code == 200
    assert org.dev.post("/api/ai/patch/apply", {"workspace_id": ws, "changes": changes}).status_code == 403

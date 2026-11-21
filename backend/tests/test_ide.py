"""Explorer operations, quota, project download and templates."""
import io
import zipfile

from app.core.project_templates import TEMPLATES
from tests.conftest import assign


def ws_of(actor, admin):
    t = assign(admin, actor).json()
    actor.post(f"/api/tasks/{t['id']}/accept")
    return actor.get(f"/api/tasks/{t['id']}/workspace").json()["id"], t


def put(actor, wid, path, content="x"):
    r = actor.put(f"/api/workspaces/{wid}/files", {"path": path, "content": content, "manual": True})
    assert r.status_code == 200, r.text
    return r.json()["file"]


def paths(actor, t):
    return sorted(f["path"] for f in actor.get(f"/api/tasks/{t['id']}/workspace").json()["files"])


def test_move_copy_delete_files_and_folders(org):
    wid, t = ws_of(org.intern, org.admin)
    a = put(org.intern, wid, "src/app.js", "A")
    put(org.intern, wid, "src/lib/util.js", "U")
    put(org.intern, wid, "index.html", "H")
    # move a folder: ids (and so version history) are kept
    r = org.intern.post(f"/api/workspaces/{wid}/move", {"from_path": "src", "to_path": "client/src"})
    assert r.status_code == 200 and a["id"] in [f["id"] for f in r.json()["files"]]
    assert paths(org.intern, t) == ["README.md", "client/src/app.js", "client/src/lib/util.js", "index.html"]
    assert len(org.intern.get(f"/api/workspaces/{wid}/files/{a['id']}/versions").json()) == 1
    # copy a folder and a file
    assert org.intern.post(f"/api/workspaces/{wid}/copy", {"from_path": "client", "to_path": "backup"}).status_code == 201
    assert org.intern.post(f"/api/workspaces/{wid}/copy", {"from_path": "index.html", "to_path": "about.html"}).status_code == 201
    assert paths(org.intern, t) == ["README.md", "about.html", "backup/src/app.js", "backup/src/lib/util.js",
                                    "client/src/app.js", "client/src/lib/util.js", "index.html"]
    # clashes and nonsense are refused
    assert org.intern.post(f"/api/workspaces/{wid}/move", {"from_path": "index.html", "to_path": "about.html"}).status_code == 409
    assert org.intern.post(f"/api/workspaces/{wid}/move", {"from_path": "client", "to_path": "client/inner"}).status_code == 422
    assert org.intern.post(f"/api/workspaces/{wid}/move", {"from_path": "nope", "to_path": "x"}).status_code == 404
    assert org.intern.post(f"/api/workspaces/{wid}/move", {"from_path": "index.html", "to_path": "../x"}).status_code == 422
    # delete a folder (soft), then the name can be reused
    assert len(org.intern.delete(f"/api/workspaces/{wid}/folder?path=backup").json()["deleted"]) == 2
    assert org.intern.post(f"/api/workspaces/{wid}/move", {"from_path": "client", "to_path": "backup"}).status_code == 200
    assert paths(org.intern, t) == ["README.md", "about.html", "backup/src/app.js", "backup/src/lib/util.js", "index.html"]
    # other people cannot change anything; reviewers cannot write
    for actor in (org.offroll, org.dev, org.admin):
        assert actor.post(f"/api/workspaces/{wid}/move", {"from_path": "index.html", "to_path": "z.html"}).status_code == 403
        assert actor.post(f"/api/workspaces/{wid}/copy", {"from_path": "index.html", "to_path": "z.html"}).status_code == 403
        assert actor.delete(f"/api/workspaces/{wid}/folder?path=backup").status_code == 403


def test_many_files_and_quota(org, monkeypatch):
    from app.core.config import settings
    wid, t = ws_of(org.intern, org.admin)
    for i in range(60):
        put(org.intern, wid, f"pages/page{i}.html", f"<h1>{i}</h1>")
    ws = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
    assert ws["usage"]["files"] == 61 and ws["usage"]["max_files"] == settings.MAX_FILES_PER_WORKSPACE
    monkeypatch.setattr(settings, "MAX_FILES_PER_WORKSPACE", 61)
    assert org.intern.put(f"/api/workspaces/{wid}/files", {"path": "one-more.html", "content": ""}).status_code == 409
    assert org.intern.post(f"/api/workspaces/{wid}/copy", {"from_path": "pages", "to_path": "copy"}).status_code == 409
    monkeypatch.setattr(settings, "MAX_FILES_PER_WORKSPACE", 2000)
    monkeypatch.setattr(settings, "MAX_WORKSPACE_BYTES", ws["usage"]["bytes"] + 10)
    assert org.intern.put(f"/api/workspaces/{wid}/files", {"path": "big.txt", "content": "x" * 50}).status_code == 413
    assert org.intern.put(f"/api/workspaces/{wid}/files", {"path": "small.txt", "content": "x" * 5}).status_code == 200


def test_download_zip_is_permission_checked(org):
    wid, t = ws_of(org.intern, org.admin)
    put(org.intern, wid, "src/app.js", "console.log(1)")
    r = org.intern.get(f"/api/workspaces/{wid}/download")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["README.md", "src/app.js"] and z.read("src/app.js") == b"console.log(1)"
    assert org.dev.get(f"/api/workspaces/{wid}/download").status_code == 200       # team developer may read
    assert org.offroll.get(f"/api/workspaces/{wid}/download").status_code == 403
    assert org.other_dev.get(f"/api/workspaces/{wid}/download").status_code == 403


def test_templates_create_real_files(org):
    listed = org.intern.get("/api/templates").json()
    assert {x["id"] for x in listed} >= {"html", "react", "vue", "node", "express", "python", "flask", "fastapi", "django",
                                         "java", "springboot", "csharp", "aspnet", "php", "flutter", "fullstack"}
    for t in TEMPLATES:
        assert t["open"] in t["files"] and all(isinstance(c, str) for c in t["files"].values()), t["id"]
    wid, t = ws_of(org.intern, org.admin)
    r = org.intern.post(f"/api/workspaces/{wid}/template", {"template_id": "fullstack"})
    assert r.status_code == 201 and r.json()["open"] == "client/src/App.jsx"
    got = paths(org.intern, t)
    assert "client/package.json" in got and "server/src/routes/items.js" in got
    # README.md already existed in the workspace? fullstack has its own README -> first call had no clash only if contents differ
    again = org.intern.post(f"/api/workspaces/{wid}/template", {"template_id": "react"})
    assert again.status_code == 201
    clash = org.intern.post(f"/api/workspaces/{wid}/template", {"template_id": "react"})
    assert clash.status_code == 409 and "package.json" in clash.json()["detail"]["files"]
    put(org.intern, wid, "src/App.jsx", "mine")
    ok = org.intern.post(f"/api/workspaces/{wid}/template", {"template_id": "react", "overwrite": True})
    assert ok.status_code == 201 and "src/App.jsx" in ok.json()["replaced"]
    fid = next(f["id"] for f in ok.json()["files"] if f["path"] == "src/App.jsx")
    kept = [v["content"] for v in org.intern.get(f"/api/workspaces/{wid}/files/{fid}/versions").json()]
    assert "mine" in kept                                                         # the overwritten content is recoverable
    assert org.dev.post(f"/api/workspaces/{wid}/template", {"template_id": "html"}).status_code == 403
    assert org.intern.post(f"/api/workspaces/{wid}/template", {"template_id": "nope"}).status_code == 404


def test_terminal_containers_of_a_previous_start_are_removed(monkeypatch):
    """A restart cannot reach the shells of an old container, so start-up removes it instead of leaking it."""
    from app.services import runner

    calls = []

    class Result:
        def __init__(self, stdout="", returncode=0):
            self.stdout, self.returncode = stdout, returncode

    def fake(args, timeout=15, **kw):
        calls.append(args)
        if args[0] == "ps":
            return Result("abc123\ndef456\n")
        return Result("")

    monkeypatch.setattr(runner, "_docker", fake)
    assert runner.reap_orphans() == 2
    assert calls[0][:3] == ["ps", "-aq", "--filter"] and "name=wc-term-" in calls[0]
    assert calls[1] == ["rm", "-f", "abc123", "def456"]


def test_no_leftover_terminal_means_no_rm(monkeypatch):
    from app.services import runner

    calls = []

    class Result:
        stdout, returncode = "", 0

    monkeypatch.setattr(runner, "_docker", lambda args, timeout=15, **kw: (calls.append(args), Result())[1])
    assert runner.reap_orphans() == 0
    assert [c[0] for c in calls] == ["ps"]                  # nothing to remove, so nothing is removed


def test_a_docker_that_does_not_answer_does_not_stop_the_api(monkeypatch):
    """Housekeeping runs in a background thread at start-up: it may fail, the API still has to come up."""
    import subprocess

    from app.services import runner

    def boom(args, timeout=15, **kw):
        raise subprocess.TimeoutExpired("docker", 15)

    monkeypatch.setattr(runner, "_docker", boom)
    assert runner.reap_orphans() == 0


def test_a_reviewer_gets_his_own_throw_away_copy(tmp_path, monkeypatch):
    """A reviewer may run the project (npm install, npm run dev) without touching the submitted work."""
    from app.core.config import settings
    from app.services import runner, terminal_sync
    monkeypatch.setattr(settings, "RUNNER_WORK_DIR", str(tmp_path))
    owner = runner.terminal_dir(7)
    reviewer = runner.terminal_dir(7, 12)
    assert owner != reviewer and str(reviewer).endswith("ws-7-review-12")
    assert owner == runner.terminal_dir(7), "the owner's folder is the same one every time"
    # seeding puts the submitted files in the reviewer's copy ...
    seeded = terminal_sync.prepare(reviewer, [("main.py", "print(1)"), ("src/App.jsx", "<h1>hi</h1>")])
    assert (reviewer / "main.py").read_text() == "print(1)"
    # ... but nothing is ever written back, while the owner's sync is a real Syncer
    assert terminal_sync.syncer_for(reviewer, 7, 12, seeded, reviewer=True) is None
    assert terminal_sync.syncer_for(owner, 7, 5, seeded) is not None

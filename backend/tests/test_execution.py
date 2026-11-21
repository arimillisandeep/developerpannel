"""Languages list and the isolated runner. Docker is replaced by a fake here: the tests check
what would be sent to Docker and that nothing runs when Docker is missing."""
import subprocess
from types import SimpleNamespace

import pytest

from app.core.languages import BY_EXT, LANGUAGES
from app.services import runner
from tests.conftest import assign


def open_ws(actor, task_id, path="main.py", content="print(input())"):
    actor.post(f"/api/tasks/{task_id}/accept")
    wid = actor.get(f"/api/tasks/{task_id}/workspace").json()["id"]
    f = actor.put(f"/api/workspaces/{wid}/files", {"path": path, "content": content, "manual": True}).json()["file"]
    return wid, f["id"]


@pytest.fixture
def docker(monkeypatch, tmp_path):
    """Pretend Docker is installed; record every call.

    The three settings below decide *how* the project is mounted and which network a terminal gets, and the
    assertions here (and the fake that reads the `-v` argument) are written for running WORKCODE from a folder.
    When the backend itself runs in a container, docker-compose sets RUNNER_WORK_DIR=/runs, RUNNER_VOLUME and
    TERMINAL_NETWORK=bridge, which switches the mounts to a shared volume and gives the terminal internet - that
    is correct there, but it would fail these tests for the wrong reason. Both modes have their own tests below
    (test_terminal_publishes_ports..., test_code_mount_uses_volume_subpath...), so nothing is left unchecked."""
    from app.core.config import settings
    (tmp_path / "runs").mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "RUNNER_WORK_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(settings, "RUNNER_VOLUME", "")
    monkeypatch.setattr(settings, "TERMINAL_NETWORK", "none")
    calls = SimpleNamespace(run=[], cli=[], seen_files={}, timeout=False)
    monkeypatch.setattr(runner, "status", lambda force=False: {"available": True, "reason": None})
    monkeypatch.setattr(runner, "image_state", lambda image: "ready")
    monkeypatch.setattr(runner, "_docker", lambda args, timeout=15, **kw: calls.cli.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    real_run = subprocess.run

    def fake(cmd, **kw):
        if cmd[0] != "docker":
            return real_run(cmd, **kw)
        calls.run.append((cmd, kw))
        mount = cmd[cmd.index("-v") + 1].rsplit(":/code:ro", 1)[0]
        import os
        for root, _, names in os.walk(mount):
            for n in names:
                calls.seen_files[os.path.relpath(os.path.join(root, n), mount).replace("\\", "/")] = open(os.path.join(root, n)).read()
        if calls.timeout:
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])
        kw["stdout"].write(b"out:" + kw["input"])
        kw["stderr"].write(b"warn")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", fake)
    return calls


def test_language_registry_has_50_plus_languages(org):
    assert len(LANGUAGES) >= 50
    assert len({l["id"] for l in LANGUAGES}) == len(LANGUAGES)
    runnable = [l for l in LANGUAGES if l["kind"] == "run"]
    assert len(runnable) >= 30 and all(l["image"] and "{file}" in l["cmd"] for l in runnable)
    for required in ("html", "css", "javascript", "react", "typescript", "node", "express", "python", "java", "c", "cpp", "sql", "postgresql"):
        assert any(l["id"] == required for l in LANGUAGES), required
    assert BY_EXT["py"]["id"] == "python" and BY_EXT["kt"]["id"] == "kotlin"
    body = org.intern.get("/api/languages").json()
    assert len(body["languages"]) == len(LANGUAGES) and "cmd" not in body["languages"][0]
    assert org.intern.client.get("/api/languages").status_code == 401


def test_run_is_refused_without_docker_and_nothing_executes(org, monkeypatch):
    monkeypatch.setattr(runner, "status", lambda force=False: {"available": False, "reason": "Docker is not installed on the server."})
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("no process may start when Docker is missing"))
    t = assign(org.admin, org.intern).json()
    wid, fid = open_ws(org.intern, t["id"])
    r = org.intern.post(f"/api/workspaces/{wid}/run", {"file_id": fid})
    assert r.status_code == 503 and "Docker" in r.json()["detail"]


def test_run_uses_a_locked_down_container(org, docker):
    t = assign(org.admin, org.intern).json()
    wid, fid = open_ws(org.intern, t["id"])
    org.intern.put(f"/api/workspaces/{wid}/files", {"path": "lib/util.py", "content": "X = 1", "manual": True})
    r = org.intern.post(f"/api/workspaces/{wid}/run", {"file_id": fid, "stdin": "hello"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["stdout"], body["stderr"], body["language"]) == ("ok", "out:hello", "warn", "python")
    cmd, kw = docker.run[0]
    joined = " ".join(cmd)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--user 1000:1000",
                 "--memory 512m", "--pids-limit 256", "--rm", ":/code:ro", "--entrypoint sh python:3.12-alpine -c"):
        assert flag in joined, flag
    assert "--privileged" not in joined and "docker.sock" not in joined
    assert cmd[-1] == "python3 -u 'main.py'" and kw["timeout"] == 20
    docker.seen_files.pop("README.md", None)
    assert docker.seen_files == {"main.py": "print(input())", "lib/util.py": "X = 1"}   # whole project is mounted
    import os
    assert not os.path.exists(cmd[cmd.index("-v") + 1].rsplit(":/code:ro", 1)[0])       # temp folder removed afterwards
    assert runner._running == {}


def test_run_permissions_and_file_types(org, docker):
    t = assign(org.admin, org.intern).json()
    wid, fid = open_ws(org.intern, t["id"])
    # A reviewer (the team lead, the task's own reviewer, an Admin) may RUN the saved code - that is what a review
    # is for - and it writes nothing. A stranger still may not touch it.
    for reviewer in (org.dev, org.admin):
        r = reviewer.post(f"/api/workspaces/{wid}/run", {"file_id": fid})
        assert r.status_code == 200, r.text
        assert r.json()["stdout"] == "out:"                     # the program really ran (fake Docker)
    ws_now = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
    assert [f["content"] for f in ws_now["files"] if f["path"] == "main.py"] == ["print(input())"], \
        "a reviewer run must not change the owner's files"
    assert org.offroll.post(f"/api/workspaces/{wid}/run", {"file_id": fid}).status_code == 403
    ran = len(docker.run)
    for path in ("index.html", "App.jsx", "notes", "weird.zzz"):
        other = org.intern.put(f"/api/workspaces/{wid}/files", {"path": path, "content": "x", "manual": True}).json()["file"]["id"]
        assert org.intern.post(f"/api/workspaces/{wid}/run", {"file_id": other}).status_code == 422, path
    assert len(docker.run) == ran, "a file that cannot be run must not start a container"
    assert org.intern.post("/api/languages/python/pull").status_code == 403
    assert org.admin.post("/api/languages/python/pull").status_code == 202
    assert org.admin.post("/api/languages/html/pull").status_code == 404


def test_timeout_kills_the_container(org, docker):
    docker.timeout = True
    t = assign(org.admin, org.intern).json()
    wid, fid = open_ws(org.intern, t["id"], "Main.java", "class Main {}")
    body = org.intern.post(f"/api/workspaces/{wid}/run", {"file_id": fid}).json()
    assert body["status"] == "timeout" and body["time_limit_seconds"] == 40
    assert docker.cli[-1][0] == "kill" and docker.cli[-1][1].startswith(f"wc-run-{org.intern.id}-")
    assert runner._running == {}


class FakeShell:
    """Stands in for the pseudo terminal of `docker run -it ... sh`: echoes what it receives."""
    def __init__(self, cmd, cols=80, rows=24):
        import os
        FakeShell.cmd, FakeShell.size, FakeShell.resized = cmd, (cols, rows), None
        self._r, self._w = os.pipe()

    def read(self, size=4096):
        import os
        return os.read(self._r, size)

    def write(self, data):
        import os
        if data == b"exit\r":
            os.close(self._w)
        else:
            os.write(self._w, b"ran: " + data)

    def resize(self, cols, rows):
        FakeShell.resized = (cols, rows)

    def wait(self, timeout=None):
        return 0

    def close(self):
        pass


def test_terminal_runs_in_the_sandbox_for_the_owner_only(org, client, docker, monkeypatch, tmp_path):
    import time
    from app.core.config import settings
    monkeypatch.setattr(runner, "PtyShell", FakeShell)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    t = assign(org.admin, org.intern).json()
    wid, _ = open_ws(org.intern, t["id"])
    org.intern.put(f"/api/workspaces/{wid}/files", {"path": "main.py", "content": "print(1)\n", "manual": True})
    # bad token, a stranger to this task, a language that cannot run: refused before any container starts
    for url in (f"/ws/terminal?token=bad&workspace_id={wid}",
                f"/ws/terminal?token={org.offroll.token}&workspace_id={wid}",
                f"/ws/terminal?token={org.intern.token}&workspace_id={wid}&language=html"):
        with client.websocket_connect(url) as ws:
            assert ws.receive_json()["type"] == "error"
    with client.websocket_connect(f"/ws/terminal?token={org.offroll.token}&workspace_id={wid}") as ws:
        assert "only open a terminal in your own workspace" in ws.receive_json()["message"]
    assert not hasattr(FakeShell, "cmd")
    with client.websocket_connect(f"/ws/terminal?token={org.intern.token}&workspace_id={wid}&cols=120&rows=40") as ws:
        ws.send_json({"type": "input", "data": "ls\r"})                 # raw keys, exactly as typed
        assert ws.receive_json() == {"type": "output", "data": "ran: ls\r"}
        ws.send_json({"type": "input", "data": "\x03"})                 # Ctrl+C reaches the shell
        assert ws.receive_json() == {"type": "output", "data": "ran: \x03"}
        assert FakeShell.size == (120, 40)
        # a second terminal of the same workspace is a second shell in the same container
        with client.websocket_connect(f"/ws/terminal?token={org.intern.token}&workspace_id={wid}") as ws2:
            ws2.send_json({"type": "input", "data": "pwd\r"})
            assert ws2.receive_json() == {"type": "output", "data": "ran: pwd\r"}
            assert [c[0] for c in docker.cli].count("run") == 1 and runner._terminals[org.intern.id].shells == 2
            assert FakeShell.cmd[:3] == ["docker", "exec", "-it"] and FakeShell.cmd[-3:] == ["sh", "-c", runner.TERMINAL_SHELL]
            monkeypatch.setattr(settings, "TERMINAL_MAX_PER_USER", 2)            # the limit of open terminals
            with client.websocket_connect(f"/ws/terminal?token={org.intern.token}&workspace_id={wid}") as ws3:
                assert "already have 2 terminals" in ws3.receive_json()["message"]
            ws2.send_json({"type": "probe", "port": "5173"})
            assert ws2.receive_json() == {"type": "listening", "port": "5173", "listening": {}, "http": "unknown"}
            ws2.send_json({"type": "input", "data": "exit\r"})               # the second shell ends, the first one goes on
            assert ws2.receive_json() == {"type": "exit", "code": 0}
        for _ in range(100):                      # closing the second one stops only its own processes, the container stays
            if runner._terminals[org.intern.id].shells == 1:
                break
            time.sleep(0.1)
        assert runner._terminals[org.intern.id].shells == 1 and "kill" not in [c[0] for c in docker.cli]
        assert any(c[0] == "exec" and "WC_TERM=" in c[-1] for c in docker.cli)
        ws.send_json({"type": "resize", "cols": 9999, "rows": 50})
        ws.send_json({"type": "input", "data": "exit\r"})
        assert ws.receive_json() == {"type": "exit", "code": 0}
    joined = "docker " + " ".join(next(c for c in docker.cli if c[0] == "run"))
    folder = runner.terminal_dir(wid)
    for flag in ("docker run -d --rm --init", "--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--user 1000:1000",
                 "--pids-limit 512", f"-v {folder}:/workspace", "-w /workspace"):
        assert flag in joined, flag
    assert FakeShell.resized == (400, 50)                                           # size is passed on, and clamped
    assert (folder / "main.py").read_text() == "print(1)\n"                         # the project is in the shell's folder
    for _ in range(150):
        if not runner._terminals:
            break
        time.sleep(0.1)
    assert runner._terminals == {} and docker.cli[-1][0] == "kill"       # container killed, slot freed


def test_terminal_files_sync_both_ways(org, tmp_path):
    """What the shell does in its folder reaches the workspace, and what the editor saves reaches the folder."""
    from app.database.connection import SessionLocal
    from app.services import terminal_sync
    t = assign(org.admin, org.intern).json()
    wid, _ = open_ws(org.intern, t["id"])
    c = org.intern
    save = lambda path, content: c.put(f"/api/workspaces/{wid}/files", {"path": path, "content": content, "manual": True})
    listing = lambda: {f["path"]: f["content"] for f in c.get(f"/api/tasks/{t['id']}/workspace").json()["files"]}
    save("main.py", "print(1)\n"); save("old.txt", "old\n")
    base = tmp_path / "ws"
    (base / "node_modules" / "left").mkdir(parents=True)
    (base / "node_modules" / "left" / "index.js").write_text("kept")
    (base / "stale.txt").write_text("from an earlier terminal")
    start = listing()
    known = terminal_sync.prepare(base, list(start.items()))
    assert not (base / "stale.txt").exists() and (base / "node_modules/left/index.js").exists()   # folder = workspace, deps kept
    assert (base / "main.py").read_text() == "print(1)\n"
    intern_id = c.get("/api/auth/me").json()["id"]
    syncer = terminal_sync.Syncer(base, wid, intern_id, known)

    def tick():
        db = SessionLocal()
        try:
            return syncer.tick(db)
        finally:
            db.close()

    assert tick() is False                                              # nothing changed yet
    # the shell: creates, edits, deletes; plus things that must stay out of the workspace
    (base / "src").mkdir(); (base / "src" / "new.js").write_text("console.log(1)\n")
    (base / "main.py").write_text("print(2)\n")
    (base / "old.txt").unlink()
    (base / "node_modules" / "pkg").mkdir(); (base / "node_modules" / "pkg" / "a.js").write_text("x")
    (base / "photo.bin").write_bytes(b"\x00\x01\x02")
    (base / "bad;name.txt").write_text("x")
    assert tick() is True
    now = listing()
    assert now["src/new.js"] == "console.log(1)\n" and now["main.py"] == "print(2)\n" and "old.txt" not in now
    assert not any(p.startswith("node_modules") or p in ("photo.bin", "bad;name.txt") for p in now)
    assert "bad;name.txt was not copied" in syncer.note
    history = c.get(f"/api/workspaces/{wid}/history").json()
    assert any(e["path"] == "old.txt" and e["action"] == "deleted" for e in (history if isinstance(history, list) else history["events"]))
    assert tick() is False                                              # stable: no ping-pong
    # the editor: saves, creates, deletes
    save("main.py", "print(3)\n"); save("docs/readme.md", "# hi\n")
    new_id = next(f["id"] for f in c.get(f"/api/tasks/{t['id']}/workspace").json()["files"] if f["path"] == "src/new.js")
    c.delete(f"/api/workspaces/{wid}/files/{new_id}")
    assert tick() is False                                              # database unchanged by this pass
    assert (base / "main.py").read_text() == "print(3)\n" and (base / "docs/readme.md").read_text() == "# hi\n"
    assert not (base / "src").exists()                                  # file removed, empty folder removed
    # both sides changed the same file: the editor wins
    (base / "main.py").write_text("print('shell')\n"); save("main.py", "print('editor')\n")
    tick()
    assert (base / "main.py").read_text() == "print('editor')\n" and listing()["main.py"] == "print('editor')\n"
    # after the task is submitted the files are locked: the shell cannot change the workspace any more
    assert c.post(f"/api/workspaces/{wid}/submit", {"note": "done"}).status_code == 201
    (base / "main.py").write_text("print('after submit')\n"); (base / "late.txt").write_text("x")
    assert tick() is False
    assert listing()["main.py"] == "print('editor')\n" and "late.txt" not in listing()


def test_terminal_command_uses_the_shared_volume_and_network_setting(monkeypatch, tmp_path):
    from app.core.config import settings
    lang = {"image": "node:22-alpine", "name": "JavaScript"}
    monkeypatch.setattr(settings, "RUNNER_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RUNNER_VOLUME", "workcode_runs")
    monkeypatch.setattr(settings, "TERMINAL_NETWORK", "bridge")
    cmd = " ".join(runner.terminal_command(lang, "wc-term-1", runner.terminal_dir(7)))
    assert "--network bridge" in cmd and "type=volume,src=workcode_runs,dst=/workspace,volume-subpath=term/ws-7" in cmd
    # dev server preview: the listed container ports are published on free local ports
    monkeypatch.setattr(settings, "TERMINAL_PORTS", "5173, 3000,22,abc,5173")
    monkeypatch.setattr(settings, "TERMINAL_PORTS_BIND", "127.0.0.1")
    cmd = " ".join(runner.terminal_command(lang, "wc-term-1", runner.terminal_dir(7)))
    assert "-p 127.0.0.1::5173 -p 127.0.0.1::3000" in cmd and "::22" not in cmd and cmd.count("-p ") == 2
    monkeypatch.setattr(settings, "TERMINAL_NETWORK", "host")          # anything else falls back to no network
    cmd = " ".join(runner.terminal_command(lang, "wc-term-1", runner.terminal_dir(7)))
    assert "--network none" in cmd and "-p " not in cmd


def test_listening_table_tells_all_addresses_from_localhost_only():
    table = """  sl  local_address rem_address   st tx_queue
   0: 00000000:1435 00000000:0000 0A 00000000:00000000
   1: 0100007F:0BB8 00000000:0000 0A 00000000:00000000
   2: 0100007F:1F90 0100007F:D431 01 00000000:00000000
   3: 00000000000000000000000001000000:0BB8 00000000000000000000000000000000:0000 0A
   4: 00000000000000000000000000000000:1388 00000000000000000000000000000000:0000 0A
"""
    assert runner._listening(table) == {"5173": "all", "3000": "local", "5000": "all"}


def test_terminal_ports_reads_docker_port_output(monkeypatch):
    class R:
        returncode = 0
        stdout = "5173/tcp -> 127.0.0.1:49160\n3000/tcp -> 127.0.0.1:49001\n3000/tcp -> [::]:49002\n"
    monkeypatch.setattr(runner, "_docker", lambda args, **kw: R())
    assert runner.terminal_ports("wc-term-1") == {"5173": 49160, "3000": 49001}
    R.returncode = 1
    assert runner.terminal_ports("wc-term-1") == {}


def test_terminal_refused_without_docker(org, client, monkeypatch):
    monkeypatch.setattr(runner, "status", lambda force=False: {"available": False, "reason": "Docker is not installed on the server."})
    monkeypatch.setattr(runner, "PtyShell", lambda *a, **k: pytest.fail("no process may start"))
    t = assign(org.admin, org.intern).json()
    wid, _ = open_ws(org.intern, t["id"])
    with client.websocket_connect(f"/ws/terminal?token={org.intern.token}&workspace_id={wid}") as ws:
        assert "Docker" in ws.receive_json()["message"]


def test_code_mount_uses_volume_subpath_when_backend_is_in_a_container(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import runner
    monkeypatch.setattr(settings, "RUNNER_WORK_DIR", "")        # the plain-folder case: "docker" is on this PC
    monkeypatch.setattr(settings, "RUNNER_VOLUME", "")
    assert runner.code_mount("/tmp/wc-run-1/code") == ["-v", "/tmp/wc-run-1/code:/code:ro"]
    monkeypatch.setattr(settings, "RUNNER_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RUNNER_VOLUME", "workcode_runs")
    work, code = runner.write_project([("main.py", "print(1)")])
    assert work.startswith(str(tmp_path))
    name = work.rsplit("/", 1)[1]
    assert runner.code_mount(code) == ["--mount", f"type=volume,src=workcode_runs,dst=/code,volume-subpath={name}/code,readonly"]


def test_a_reviewer_terminal_stays_open_after_the_sync_loop_starts(org, client, docker, monkeypatch, tmp_path):
    """The reviewer's copy has no write-back sync. The sync loop must not fall over when there is none -
    it did once: the terminal printed its prompt and closed a second later."""
    import time
    from app.core.config import settings
    monkeypatch.setattr(runner, "PtyShell", FakeShell)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    t = assign(org.admin, org.intern).json()
    wid, _ = open_ws(org.intern, t["id"])
    with client.websocket_connect(f"/ws/terminal?token={org.dev.token}&workspace_id={wid}") as ws:
        time.sleep(2.2)                                  # longer than one tick of the sync loop
        ws.send_json({"type": "input", "data": "echo alive\r"})
        assert ws.receive_json() == {"type": "output", "data": "ran: echo alive\r"}
        ws.send_json({"type": "input", "data": "exit\r"})
        assert ws.receive_json() == {"type": "exit", "code": 0}


def test_a_reviewer_opens_a_terminal_in_a_copy_of_the_submitted_work(org, client, docker, monkeypatch, tmp_path):
    """The reviewer can npm install / npm run dev to see the app - and never touches the submitted files."""
    import time
    from app.core.config import settings
    monkeypatch.setattr(runner, "PtyShell", FakeShell)
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    t = assign(org.admin, org.intern).json()
    wid, _ = open_ws(org.intern, t["id"])
    org.intern.put(f"/api/workspaces/{wid}/files", {"path": "main.py", "content": "print(1)\n", "manual": True})
    with client.websocket_connect(f"/ws/terminal?token={org.dev.token}&workspace_id={wid}") as ws:
        ws.send_json({"type": "input", "data": "npm install\r"})
        assert ws.receive_json() == {"type": "output", "data": "ran: npm install\r"}
        started = " ".join(next(c for c in docker.cli if c[0] == "run"))
        mine, owners = runner.terminal_dir(wid, org.dev.id), runner.terminal_dir(wid)
        assert f"{mine}:/workspace" in started, "a reviewer gets his own folder"
        assert f"{owners}:/workspace" not in started, "and never the folder the owner's terminal uses"
        assert (mine / "main.py").read_text() == "print(1)\n", "the submitted file is there to run"
        assert runner._terminals[org.dev.id].syncer is None, "nothing a reviewer does may flow back"
        # the owner's workspace is exactly as it was
        ws_now = org.intern.get(f"/api/tasks/{t['id']}/workspace").json()
        assert [f["content"] for f in ws_now["files"] if f["path"] == "main.py"] == ["print(1)\n"]
        ws.send_json({"type": "input", "data": "exit\r"})
        assert ws.receive_json() == {"type": "exit", "code": 0}
    for _ in range(100):
        if not runner._terminals:
            break
        time.sleep(0.1)

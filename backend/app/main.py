import logging
import re
import threading

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database.connection import SessionLocal
from app.dependencies.auth import user_from_token
from app.websocket.manager import manager
from app.api import (ai, auth, chat, dashboard, execution, meetings, meeting_timer, notifications, org, recordings, reports, sessions,
                     submissions, tasks, timer_admin, users, workspaces)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="WORKCODE API", version="2.0.0",
              description="Company management and developer workspace platform.")

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "X-Workcode-Token"])


def _reap_terminal_containers():
    """Start-up housekeeping: terminals of a previous process cannot be reached any more, so remove them."""
    try:
        from app.services import runner
        removed = runner.reap_orphans()
        if removed:
            logging.getLogger("workcode.terminal").info(
                "removed %s terminal container(s) left over from a previous start", removed)
    except Exception:                       # housekeeping must never keep the API from starting
        logging.getLogger("workcode.terminal").exception("could not remove old terminal containers")


threading.Thread(target=_reap_terminal_containers, name="reap-terminals", daemon=True).start()


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


if settings.ALLOW_QUERY_TOKEN:
    # Hosted-preview workaround (never enable on your own server). Some preview gateways drop
    # request headers, so the client may put the JWT in the path: /api/_t/<jwt>/tasks.
    # It is moved into the normal header here and then validated like any other token.
    plog = logging.getLogger("workcode.preview")

    class PathTokenMiddleware:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"].startswith("/api/"):
                names = sorted(k.decode() for k, _ in scope["headers"])
                if scope["path"].startswith("/api/_t/"):
                    token, _, rest = scope["path"][len("/api/_t/"):].partition("/")
                    scope = dict(scope, path="/api/" + rest, raw_path=("/api/" + rest).encode(),
                                 headers=[(k, v) for k, v in scope["headers"] if k != b"x-workcode-token"]
                                 + [(b"x-workcode-token", token.encode())])
                    plog.info("path-token request %s", scope["path"])
                else:
                    plog.info("plain request %s ?%s headers=%s", scope["path"],
                              scope["query_string"].decode()[:60], names)
            await self.inner(scope, receive, send)

    app.add_middleware(PathTokenMiddleware)


if settings.JWT_SECRET == "dev-only-secret-change-me" or len(settings.JWT_SECRET) < 32:
    logging.getLogger("workcode").warning(
        "JWT_SECRET is the built-in default or shorter than 32 characters. Anyone who knows it can sign in as any user. "
        "Set a long random JWT_SECRET in backend/.env before real use.")

if settings.ALLOW_QUERY_TOKEN:      # hosted-preview helper only; on your own server this address does not exist
    @app.post("/api/debug/client", tags=["health"], include_in_schema=False)
    async def client_report(request: Request):
        """The browser reports its own state here when sign-in misbehaves (no secrets are sent)."""
        body = (await request.body())[:1500].decode(errors="replace")
        logging.getLogger("workcode.client").info("CLIENT REPORT %s", body)
        return {"ok": True}


for module in (auth, users, org, tasks, workspaces, submissions, notifications, sessions, dashboard,
               meetings, meeting_timer, chat, recordings, reports, execution, timer_admin, ai):
    app.include_router(module.router)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}


API_BUILD = "build 36.5"
API_FIXES = ("workspace-read-only-for-reviewers", "review-task-in-my-list")


@app.get("/api/health/version", tags=["health"])
def health_version():
    """Which code the backend is really running.

    After copying files into a running install it is normal to wonder whether they arrived; this answers it
    from the inside of the container, without a shell.
    """
    return {"build": API_BUILD, "fixes": list(API_FIXES)}


@app.get("/api/health/db", tags=["health"])
def health_db():
    """Is the database reachable, does it have the tables, and how many accounts are in it?

    Safe to open in a browser (also through the website address - /api is forwarded there). When every
    page says "Request failed (500)" this one answer says which layer is broken. No secrets are in it.
    """
    db = SessionLocal()
    try:
        db.execute(text("select 1"))
        users = db.execute(text("select count(*) from users")).scalar()
    except Exception as error:                      # noqa: BLE001 - the reason is the whole point here
        reason = " ".join(str(getattr(error, "orig", error)).split())[:300]
        reason = re.sub(r"://[^:/@\s]+:[^@/\s]+@", "://***:***@", reason)     # never echo a password
        raise HTTPException(503, f"Database problem: {reason}") from None
    finally:
        db.close()
    schema = None
    db = SessionLocal()
    try:
        schema = db.execute(text("select max(version_num) from alembic_version")).scalar()
    except Exception:                               # a database that was never migrated
        schema = None
    finally:
        db.close()
    return {"status": "ok", "users": users, "schema": schema}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    """Authenticated notification channel: /ws?token=<JWT>."""
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
    finally:
        db.close()
    if not user:
        await ws.close(code=4401)
        return
    await manager.connect(user.id, ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive pings from the client
    except WebSocketDisconnect:
        manager.disconnect(user.id, ws)


@app.websocket("/ws/terminal")
async def terminal_endpoint(ws: WebSocket, token: str = "", workspace_id: int = 0, language: str = "python",
                            cols: int = 80, rows: int = 24):
    """Interactive terminal for the owner of a workspace, inside an isolated container (never on this server).

    A user can open several terminals for one workspace: they are shells in the same container.
    Client sends {"type":"input","data":"<keys>"}, {"type":"resize","cols":..,"rows":..} and {"type":"probe","port":".."}
    (answered with {"type":"listening","listening":{port: "all"|"local"},"http":"ok"|"fail"|"unknown"}).
    Server sends {"type":"output","data":..}, {"type":"files"} (workspace files changed: reload them),
    {"type":"note","message":..}, {"type":"error","message":..}, {"type":"exit","code":..} and
    {"type":"ports","ports":{"5173":49160}} (container port -> port on this computer, for the dev server preview)."""
    import asyncio
    import codecs
    import threading
    import time as _time
    from app.core.languages import BY_ID
    from app.database.models import Workspace
    from app.api.workspaces import live_files
    from app.services import runner, terminal_sync
    from app.services.common import activity

    await ws.accept()

    async def refuse(message):
        await ws.send_json({"type": "error", "message": message})
        await ws.close(code=4403)

    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        if not user:
            return await refuse("Your session has expired. Sign in again.")
        wsp = db.get(Workspace, workspace_id)
        if not wsp:
            return await refuse("Workspace not found.")
        # The owner works in his own workspace. A reviewer (Admin, the team's On-Roll lead, the task's reviewer)
        # also gets a terminal, but in a copy of the submitted files: he can npm install and npm run dev without
        # reaching the owner's files.
        reviewer = wsp.user_id != user.id
        if reviewer:
            from app.core import permissions as P
            from app.database.models import Task
            if not P.can_read_workspace(db, user, wsp.user_id, db.get(Task, wsp.task_id)):
                return await refuse("You can only open a terminal in your own workspace.")
        lang = BY_ID.get(language)
        if not lang or lang["kind"] != "run":
            return await refuse("Choose a runnable language for the terminal.")
        files = [(f.path, f.content) for f in live_files(db, wsp.id)]
        user_id, ws_id = user.id, wsp.id
        activity(db, user_id, "terminal.open", {"workspace_id": wsp.id, "language": language,
                                               "as_reviewer": reviewer})
        db.commit()
    finally:
        db.close()

    loop = asyncio.get_running_loop()
    st = runner.status()
    if not st["available"]:
        return await refuse(st["reason"])
    work_dir = runner.terminal_dir(ws_id, user_id if reviewer else None)
    try:
        def prepare(sess):   # only for the first terminal of the workspace: later ones join its container and its syncer
            seeded = terminal_sync.prepare(work_dir, files)
            # A reviewer's copy is one-way: nothing he does is written back to the submitted work.
            sess.syncer = terminal_sync.syncer_for(work_dir, ws_id, user_id, seeded, reviewer=reviewer)

        shell, cleanup, sess = await loop.run_in_executor(
            None, lambda: runner.open_terminal(user_id, lang, ws_id, cols, rows, prepare, reviewer=reviewer))
    except runner.RunnerUnavailable as e:
        return await refuse(str(e))
    except OSError as e:
        return await refuse(f"The terminal folder could not be prepared: {e}")
    syncer = sess.syncer
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    def pump():   # thread: container output -> queue (blocks when the browser is slow, which throttles the program)
        try:
            while True:
                data = shell.read(4096)
                if not data:
                    break
                asyncio.run_coroutine_threadsafe(queue.put(data), loop).result()
        except Exception:
            pass
        try:
            code = shell.wait(timeout=5)
        except Exception:
            code = None
        try:
            asyncio.run_coroutine_threadsafe(queue.put(code), loop).result(timeout=5)
        except Exception:
            pass

    threading.Thread(target=pump, daemon=True).start()
    started = last_input = _time.time()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def sync_once(force=False) -> bool:
        if syncer is None:
            return False
        with sess.sync_lock:          # the terminals of a workspace share one syncer
            if not force and _time.time() - sess.last_sync < 1.2:
                return False
            sess.last_sync = _time.time()
            return _sync()

    def _sync() -> bool:
        session = SessionLocal()
        try:
            return syncer.tick(session)
        except Exception:
            logging.getLogger("workcode.terminal").exception("terminal file sync failed")
            session.rollback()
            return False
        finally:
            session.close()

    async def sender():
        while True:
            item = await queue.get()
            if isinstance(item, (bytes, bytearray)):
                text = decoder.decode(bytes(item))
                if text:
                    await ws.send_json({"type": "output", "data": text})
            else:
                await ws.send_json({"type": "exit", "code": item})
                return

    async def receiver():
        nonlocal last_input
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "input":
                data = str(msg.get("data", ""))[:20000].encode()
                last_input = sess.last_input = _time.time()
                await loop.run_in_executor(None, shell.write, data)
            elif kind == "resize":
                shell.resize(*runner.clamp_size(msg.get("cols"), msg.get("rows")))
            elif kind == "probe":      # is the dev server of the Preview tab really up inside the container?
                found = await loop.run_in_executor(None, runner.terminal_probe, shell.name, str(msg.get("port", "")))
                await ws.send_json({"type": "listening", "port": str(msg.get("port", "")), **found})

    async def syncing():   # files created / changed / deleted in the terminal appear in the editor, and the other way round
        if syncer is None:                 # a reviewer's copy is one-way: there is nothing to tell the browser
            await asyncio.Event().wait()
            return
        told = None
        while True:
            await asyncio.sleep(1.5)
            if await loop.run_in_executor(None, sync_once):
                await ws.send_json({"type": "files"})
            if syncer.note and syncer.note != told:
                told = syncer.note
                await ws.send_json({"type": "note", "message": told})

    async def ports():   # tells the browser where a dev server started in this terminal can be opened
        if runner.published_ports():
            for _ in range(20):
                await asyncio.sleep(0.5)
                found = await loop.run_in_executor(None, runner.terminal_ports, shell.name)
                if found:
                    await ws.send_json({"type": "ports", "ports": found})
                    break
        await asyncio.Event().wait()

    async def watchdog():
        while True:
            await asyncio.sleep(5)
            now = _time.time()
            if now - sess.last_input > settings.TERMINAL_IDLE_SECONDS:
                await ws.send_json({"type": "error", "message": "Terminal closed: no input for a long time."})
                return
            if now - started > settings.TERMINAL_MAX_SECONDS:
                await ws.send_json({"type": "error", "message": "Terminal closed: session time limit reached."})
                return

    def finish():   # always runs, also when the connection is torn down abruptly
        sync_once(force=True)   # what the last command wrote is not lost
        cleanup()               # container killed, slot freed

    tasks = [asyncio.create_task(c()) for c in (sender, receiver, syncing, watchdog, ports)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        threading.Thread(target=finish, daemon=True).start()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await ws.close()
        except Exception:
            pass

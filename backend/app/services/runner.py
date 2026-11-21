"""Isolated code execution.

User code NEVER runs in this process or directly on the server. Each run is one throw-away
Docker container with: no network, read-only root filesystem, the project mounted read-only,
a small writable /tmp, memory / CPU / process limits, all Linux capabilities dropped, a
non-root user, and a hard time limit. If Docker is not available the run is refused.
"""
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.core.config import settings

_status = {"at": 0.0, "value": None}
_images = {}                      # image -> (checked_at, present)
_pulls = {}                       # image -> "pulling" | "failed: ..."
_running = {}                     # user_id -> container name
_lock = threading.Lock()
_slots = threading.BoundedSemaphore(settings.RUNNER_MAX_PARALLEL)


class RunnerUnavailable(Exception):
    pass


def _docker(args, timeout=15, **kw):
    """The only place that starts a process. Always the docker CLI, never user code."""
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, **kw)


def status(force=False) -> dict:
    if not settings.RUNNER_ENABLED:
        return {"available": False, "reason": "Code execution is switched off (RUNNER_ENABLED=false)."}
    if not force and _status["value"] and time.time() - _status["at"] < 20:
        return _status["value"]
    if not shutil.which("docker"):
        value = {"available": False, "reason": "Docker is not installed on the server. Install Docker Desktop and start it."}
    else:
        try:
            r = _docker(["info", "--format", "{{.OSType}}"], timeout=10)
            if r.returncode != 0:
                value = {"available": False, "reason": "Docker is installed but not running. Start Docker Desktop."}
            elif r.stdout.strip() != "linux":
                value = {"available": False, "reason": "Docker must be in Linux containers mode."}
            else:
                value = {"available": True, "reason": None}
        except (subprocess.TimeoutExpired, OSError):
            value = {"available": False, "reason": "Docker did not answer. Start Docker Desktop."}
    _status.update(at=time.time(), value=value)
    return value


def image_state(image: str) -> str:
    """ready | missing | pulling | failed: <why>"""
    if _pulls.get(image) == "pulling":
        return "pulling"
    cached = _images.get(image)
    if cached and (cached[1] or time.time() - cached[0] < 15):
        return "ready" if cached[1] else _pulls.get(image, "missing")
    try:
        present = _docker(["image", "inspect", image], timeout=10).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        present = False
    _images[image] = (time.time(), present)
    return "ready" if present else _pulls.get(image, "missing")


def pull(image: str):
    """Download a language image in the background (admin action)."""
    with _lock:
        if _pulls.get(image) == "pulling":
            return
        _pulls[image] = "pulling"

    def work():
        try:
            r = _docker(["pull", image], timeout=1800)
            if r.returncode == 0:
                _pulls.pop(image, None)
                _images[image] = (time.time(), True)
            else:
                _pulls[image] = "failed: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1][:200]
        except (subprocess.TimeoutExpired, OSError) as e:
            _pulls[image] = f"failed: {e}"[:200]
    threading.Thread(target=work, daemon=True).start()


def code_mount(code_dir: str) -> list[str]:
    """Mount the project copy read-only on /code.

    Normally a plain folder mount. When the backend runs in a container, the Docker engine cannot see the
    backend's folders, so the copy is written to a shared volume and only that run's sub-folder is mounted."""
    if settings.RUNNER_VOLUME and settings.RUNNER_WORK_DIR:
        sub = Path(code_dir).resolve().relative_to(Path(settings.RUNNER_WORK_DIR).resolve()).as_posix()
        return ["--mount", f"type=volume,src={settings.RUNNER_VOLUME},dst=/code,volume-subpath={sub},readonly"]
    return ["-v", f"{code_dir}:/code:ro"]


def sandbox_flags(lang: dict, name: str, code_dir: str) -> list[str]:
    """Isolation flags shared by Run and the terminal."""
    return ["--rm", "-i", "--name", name,
            "--network", "none",
            "--read-only",
            "--tmpfs", f"/tmp:rw,exec,nosuid,size={settings.RUNNER_TMP_MB}m,mode=1777",
            "--memory", f"{settings.RUNNER_MEMORY_MB}m", "--memory-swap", f"{settings.RUNNER_MEMORY_MB}m",
            "--cpus", str(settings.RUNNER_CPUS), "--pids-limit", "256",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", lang.get("user") or "1000:1000",
            "-e", "HOME=/tmp", "-e", "GOCACHE=/tmp/go", "-e", "CRYSTAL_CACHE_DIR=/tmp/crystal", "-e", "XDG_CACHE_HOME=/tmp/cache",
            *code_mount(code_dir)]


def build_command(lang: dict, name: str, code_dir: str, entry: str) -> list[str]:
    cmd = lang["cmd"].replace("{file}", "'" + entry.replace("'", "") + "'")
    return ["run", *sandbox_flags(lang, name, code_dir), "-w", "/code", "--entrypoint", "sh", lang["image"], "-c", cmd]


def write_project(files: list[tuple[str, str]]) -> tuple[str, str]:
    """Copy the saved files to a temporary folder. Returns (folder to delete later, code folder)."""
    work = tempfile.mkdtemp(prefix="wc-run-", dir=settings.RUNNER_WORK_DIR or None)
    code = Path(work) / "code"
    code.mkdir()
    os.chmod(work, 0o755)
    os.chmod(code, 0o755)
    for path, content in files:
        target = (code / path).resolve()
        if code.resolve() not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(target.parent, 0o755)
        target.write_text(content or "", encoding="utf-8", newline="\n")
        os.chmod(target, 0o644)
    return work, str(code)


# ---- interactive terminal ----------------------------------------------------------------
_terminals = {}                   # user_id -> TerminalSession
# A real interactive shell (bash when the image has it) in the project folder.
TERMINAL_SHELL = ("cd /workspace 2>/dev/null; "
                  "if command -v bash >/dev/null 2>&1; then exec bash --norc --noprofile -i; else exec sh -i; fi")
TERMINAL_KEEPALIVE = "trap 'exit 0' TERM INT; while :; do sleep 3600 & wait $!; done"
TERMINAL_PROMPT = r"\[\e[1;32m\]workspace\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ "


def terminal_dir(workspace_id: int, reviewer_id: int | None = None) -> Path:
    """The folder a workspace's terminal works in. It is kept between terminals, so node_modules etc. survive.

    A reviewer (somebody reading the task) gets a folder of his own: ws-7-review-12, so his npm install and
    his experiments can never meet the owner's files.
    """
    base = Path(settings.RUNNER_WORK_DIR) if settings.RUNNER_WORK_DIR else Path(settings.STORAGE_DIR) / "terminal"
    name = f"ws-{workspace_id}" + (f"-review-{reviewer_id}" if reviewer_id else "")
    return base.resolve() / "term" / name


def workspace_mount(work_dir: Path) -> list[str]:
    """Mount the project folder writable on /workspace (see code_mount for the two cases)."""
    if settings.RUNNER_VOLUME and settings.RUNNER_WORK_DIR:
        sub = work_dir.resolve().relative_to(Path(settings.RUNNER_WORK_DIR).resolve()).as_posix()
        return ["--mount", f"type=volume,src={settings.RUNNER_VOLUME},dst=/workspace,volume-subpath={sub}"]
    return ["-v", f"{work_dir}:/workspace"]


def published_ports() -> list[int]:
    """Container ports that get a free port on this computer (dev server preview). None without a network."""
    if settings.TERMINAL_NETWORK != "bridge":
        return []
    ports = []
    for part in settings.TERMINAL_PORTS.split(","):
        part = part.strip()
        if part.isdigit() and 1024 <= int(part) <= 65535 and int(part) not in ports:
            ports.append(int(part))
    return ports[:12]


def terminal_ports(name: str) -> dict[str, int]:
    """{container port: port on this computer} of a running terminal container, read from `docker port`."""
    try:
        r = _docker(["port", name], timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return {}
    if r.returncode != 0:
        return {}
    out = r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, (bytes, bytearray)) else (r.stdout or "")
    found = {}
    for line in out.splitlines():           # "5173/tcp -> 127.0.0.1:49160"
        left, _, right = line.partition(" -> ")
        port, host_port = left.split("/")[0].strip(), right.rsplit(":", 1)[-1].strip()
        if port.isdigit() and host_port.isdigit():
            found.setdefault(port, int(host_port))
    return found


def terminal_command(lang: dict, name: str, work_dir: Path) -> list[str]:
    """`docker run` arguments of the container that holds all terminals of one workspace.
    It only waits; every terminal is a `docker exec` shell in it (terminal_shell_command),
    so the terminals share the files, the installed packages and localhost, like terminals on one PC."""
    network = settings.TERMINAL_NETWORK if settings.TERMINAL_NETWORK in ("none", "bridge") else "none"
    bind = settings.TERMINAL_PORTS_BIND.strip() or "127.0.0.1"
    publish = [x for port in published_ports() for x in ("-p", f"{bind}::{port}")]
    memory = f"{settings.TERMINAL_MEMORY_MB}m"
    return ["run", "-d", "--rm", "--init", "--name", name,
            "--network", network, *publish,
            "--read-only",
            "--tmpfs", f"/tmp:rw,exec,nosuid,size={settings.TERMINAL_TMP_MB}m,mode=1777",
            "--memory", memory, "--memory-swap", memory,
            "--cpus", str(settings.RUNNER_CPUS), "--pids-limit", "512",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", lang.get("user") or "1000:1000",
            "-e", "HOME=/tmp", "-e", "TERM=xterm-256color", "-e", f"PS1={TERMINAL_PROMPT}",
            "-e", "GOCACHE=/tmp/go", "-e", "XDG_CACHE_HOME=/tmp/cache", "-e", "npm_config_cache=/tmp/npm",
            "-e", "PIP_CACHE_DIR=/tmp/pip", "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", "-e", "npm_config_update_notifier=false",
            *workspace_mount(work_dir), "-w", "/workspace", "--entrypoint", "sh", lang["image"], "-c", TERMINAL_KEEPALIVE]


def terminal_shell_command(name: str, shell_id: str) -> list[str]:
    """One interactive shell inside the workspace's terminal container. WC_TERM marks its processes (see kill_shell)."""
    return ["docker", "exec", "-it", "-e", f"WC_TERM={shell_id}", "-w", "/workspace", name, "sh", "-c", TERMINAL_SHELL]


def reap_orphans() -> int:
    """Remove terminal containers left behind by an earlier backend process, and return how many.

    The shells inside a terminal container are `docker exec` processes owned by the backend that started them, so
    after a restart (or a rebuild) nothing can ever attach to those containers again. Left alone they keep running
    forever, hold the workspace folder and eat a runner slot of the machine. Called once at startup."""
    try:
        r = _docker(["ps", "-aq", "--filter", "name=wc-term-"], timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return 0
    ids = [x for x in (r.stdout or "").split() if x]
    if r.returncode != 0 or not ids:
        return 0
    try:
        _docker(["rm", "-f", *ids], timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return 0
    return len(ids)


def kill_shell(name: str, shell_id: str):
    """Stop one terminal and everything it started (a dev server keeps running after its shell is gone otherwise)."""
    script = ("for p in /proc/[0-9]*; do tr '\\0' '\\n' < $p/environ 2>/dev/null | grep -qx 'WC_TERM=%s' "
              "&& kill -9 ${p#/proc/} 2>/dev/null; done; true" % shell_id)
    try:
        _docker(["exec", name, "sh", "-c", script], timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _listening(text: str) -> dict[str, str]:
    """/proc/net/tcp + tcp6 -> {port: "all" | "local"} for listening sockets ("local" = reachable only inside)."""
    found = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[3] != "0A" or ":" not in parts[1]:
            continue
        addr, _, port = parts[1].rpartition(":")
        try:
            port = str(int(port, 16))
        except ValueError:
            continue
        local = addr in ("0100007F", "00000000000000000000000001000000")
        if not local or port not in found:
            found[port] = "local" if local else "all"
    return found


PROBE = ("cat /proc/net/tcp /proc/net/tcp6 2>/dev/null; echo ===WC===; "
         "if [ -n \"$1\" ]; then u=http://127.0.0.1:$1/; "
         "if command -v wget >/dev/null 2>&1; then wget -q -T 3 -O /dev/null $u 2>/dev/null && echo ok || echo fail; "
         "elif command -v curl >/dev/null 2>&1; then curl -s -m 3 -o /dev/null $u && echo ok || echo fail; "
         "else echo unknown; fi; fi")


def terminal_probe(name: str, port: str = "") -> dict:
    """What is listening inside the terminal container, and whether http://127.0.0.1:<port>/ answers there."""
    port = port if str(port).isdigit() else ""
    try:
        r = _docker(["exec", name, "sh", "-c", PROBE, "probe", port], timeout=12)
    except (subprocess.TimeoutExpired, OSError):
        return {"listening": {}, "http": "unknown"}
    table, _, http = (r.stdout or "").partition("===WC===")
    return {"listening": _listening(table), "http": http.strip() or "unknown"}


class PtyShell:
    """`docker run -it` attached to a pseudo terminal, so the shell behaves like a real one
    (line editing, Tab completion, Ctrl+C, colours, full-screen programs)."""

    def __init__(self, cmd: list[str], cols: int = 80, rows: int = 24):
        import pty
        self._master, slave = pty.openpty()
        self._set_size(cols, rows)
        try:
            self.proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, close_fds=True, start_new_session=True)
        finally:
            os.close(slave)

    def _set_size(self, cols: int, rows: int):
        import fcntl
        import struct
        import termios
        fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def read(self, size: int = 4096) -> bytes:
        try:
            return os.read(self._master, size)
        except OSError:              # the shell ended
            return b""

    def write(self, data: bytes):
        while data:
            data = data[os.write(self._master, data):]

    def resize(self, cols: int, rows: int):
        import signal
        try:
            self._set_size(cols, rows)
            self.proc.send_signal(signal.SIGWINCH)       # docker passes the new size on to the container
        except (OSError, ValueError):
            pass

    def wait(self, timeout=None):
        return self.proc.wait(timeout=timeout)

    def close(self):
        try:
            os.close(self._master)
        except OSError:
            pass


def clamp_size(cols, rows) -> tuple[int, int]:
    def num(value, default, low, high):
        try:
            return max(low, min(high, int(value)))
        except (TypeError, ValueError):
            return default
    return num(cols, 80, 20, 400), num(rows, 24, 5, 200)


class TerminalSession:
    """The terminal container of one user (one workspace at a time) and the terminals open in it."""

    def __init__(self, user_id: int, workspace_id: int, lang: dict, name: str):
        self.user_id, self.workspace_id, self.lang, self.name = user_id, workspace_id, lang, name
        self.shells = 0
        self.syncer = None                 # set by the caller that created the container
        self.sync_lock = threading.Lock()
        self.last_sync = 0.0
        self.last_input = time.time()      # any key in any of its terminals


_term_lock = threading.Lock()       # starting a container takes a moment: one at a time


def open_terminal(user_id: int, lang: dict, workspace_id: int, cols: int = 80, rows: int = 24, prepare=None,
                  reviewer: bool = False):
    """Start an interactive shell in the user's locked-down terminal container. Returns (shell, cleanup, session).
    The first terminal starts the container; `prepare(session)` is then called first to put the project files in
    terminal_dir(workspace_id). More terminals join the same container. The last one to close removes it."""
    st = status()
    if not st["available"]:
        raise RunnerUnavailable(st["reason"])
    try:
        import pty  # noqa: F401
    except ImportError:
        raise RunnerUnavailable("The terminal needs the backend to run on Linux or in Docker "
                                "(on Windows start WORKCODE with: docker compose up).")
    with _term_lock:
        session = _terminals.get(user_id)
        if session and session.workspace_id != workspace_id:
            raise RunnerUnavailable("You have a terminal open in another task. Close it first.")
        if session and session.shells >= settings.TERMINAL_MAX_PER_USER:
            raise RunnerUnavailable(f"You already have {session.shells} terminals open. Close one first.")
        if not session:
            state = image_state(lang["image"])
            if state != "ready":
                raise RunnerUnavailable(f"The {lang['name']} image ({lang['image']}) is {state} on the server. "
                                        f"An admin can install it on the Languages page.")
            if not _slots.acquire(blocking=False):
                raise RunnerUnavailable("The runner is busy. Try again in a few seconds.")
            session = TerminalSession(user_id, workspace_id, lang, f"wc-term-{user_id}-{int(time.time() * 1000)}")
            try:
                if prepare:
                    prepare(session)
                args = terminal_command(lang, session.name,
                                       terminal_dir(workspace_id, user_id if reviewer else None))
                r = _docker(args, timeout=60)
                if r.returncode != 0 and "init" in (r.stderr or ""):          # a Docker without docker-init
                    r = _docker([a for a in args if a != "--init"], timeout=60)
                if r.returncode != 0:
                    raise RunnerUnavailable("The terminal container could not start: " + ((r.stderr or "").strip()[-300:] or "unknown error"))
            except BaseException:
                _slots.release()
                raise
            _terminals[user_id] = session
        session.shells += 1
        session.last_input = time.time()
    shell = None
    shell_id = f"t{int(time.time() * 1000)}{session.shells}"
    done = threading.Event()

    def cleanup():
        if done.is_set():
            return
        done.set()
        with _term_lock:
            session.shells -= 1
            last = session.shells <= 0
            if last:
                _terminals.pop(user_id, None)
        try:
            if last:
                _docker(["kill", session.name], timeout=10)
            else:
                kill_shell(session.name, shell_id)
        except (subprocess.TimeoutExpired, OSError):
            pass
        if shell is not None:
            shell.close()
        if last:
            _slots.release()

    try:
        cols, rows = clamp_size(cols, rows)
        shell = PtyShell(terminal_shell_command(session.name, shell_id), cols, rows)
        shell.name = session.name
    except Exception:
        cleanup()
        raise
    return shell, cleanup, session


def _read(path: Path) -> tuple[str, bool]:
    limit = settings.RUNNER_MAX_OUTPUT
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    return data[:limit].decode("utf-8", "replace"), len(data) > limit


def stop(user_id: int) -> bool:
    name = _running.get(user_id)
    if not name:
        return False
    try:
        _docker(["kill", name], timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return True


def run(user_id: int, lang: dict, files: list[tuple[str, str]], entry: str, stdin: str = "") -> dict:
    st = status()
    if not st["available"]:
        raise RunnerUnavailable(st["reason"])
    state = image_state(lang["image"])
    if state != "ready":
        raise RunnerUnavailable(
            f"The {lang['name']} image ({lang['image']}) is {state} on the server. "
            f"An admin can download it on the Languages page, or run: docker pull {lang['image']}")
    with _lock:
        if user_id in _running:
            raise RunnerUnavailable("You already have a program running. Stop it first.")
        if not _slots.acquire(blocking=False):
            raise RunnerUnavailable("The runner is busy. Try again in a few seconds.")
        name = f"wc-run-{user_id}-{int(time.time() * 1000)}"
        _running[user_id] = name
    work, code = write_project(files)
    try:
        out_path, err_path = Path(work) / "stdout", Path(work) / "stderr"
        timeout = min(lang["timeout"], settings.RUNNER_MAX_SECONDS)
        started = time.time()
        timed_out = False
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            try:
                r = subprocess.run(["docker", *build_command(lang, name, str(code), entry)], input=(stdin or "").encode(),
                                   stdout=out, stderr=err, timeout=timeout)
                exit_code = r.returncode
            except subprocess.TimeoutExpired:
                timed_out, exit_code = True, None
                try:
                    _docker(["kill", name], timeout=10)
                except (subprocess.TimeoutExpired, OSError):
                    pass
        stdout, cut1 = _read(out_path)
        stderr, cut2 = _read(err_path)
        if timed_out:
            result = "timeout"
        elif exit_code == 0:
            result = "ok"
        elif exit_code == 137:
            result = "killed"          # stopped by the user or out of memory
        else:
            result = "error"
        return {"status": result, "exit_code": exit_code, "stdout": stdout, "stderr": stderr, "truncated": cut1 or cut2,
                "duration_ms": int((time.time() - started) * 1000), "time_limit_seconds": timeout,
                "language": lang["id"], "file": entry}
    finally:
        shutil.rmtree(work, ignore_errors=True)
        with _lock:
            _running.pop(user_id, None)
        _slots.release()

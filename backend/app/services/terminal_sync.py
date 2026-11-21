"""Two-way file sync between a workspace (database) and the folder its terminal works in.

The terminal container works in a real folder. While a terminal is open, `Syncer.tick()` runs every
second or two and compares three things per path: the database, the folder, and what both had the last
time they were equal. Whichever side changed since then is copied to the other side; when both changed,
the editor (database) wins. Dependency and build folders (node_modules, .git, ...) stay in the folder only.
"""
import hashlib
import os
import shutil
from pathlib import Path

from app.core.config import settings

IGNORE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", "target", ".next", ".cache",
               ".npm", ".gradle", ".dart_tool", "vendor", ".pytest_cache", ".mypy_cache"}
MAX_SCAN = 4000            # files looked at per tick
MAX_CHANGES = 200          # folder -> database changes applied per tick


def digest(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8", "surrogatepass")).hexdigest()


def _open_up(path: Path):
    """The container runs as another user: make what the backend writes changeable by it."""
    try:
        os.chmod(path, 0o777 if path.is_dir() else 0o666)
    except OSError:
        pass


def _target(base: Path, rel: str) -> Path | None:
    target = (base / rel).resolve()
    return target if base in target.parents else None


def write_file(base: Path, rel: str, content: str) -> bool:
    target = _target(base, rel)
    if target is None:
        return False
    try:
        parent = target.parent
        missing = []
        while parent != base and not parent.exists():
            missing.append(parent)
            parent = parent.parent
        target.parent.mkdir(parents=True, exist_ok=True)
        for folder in missing:
            _open_up(folder)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        target.write_text(content or "", encoding="utf-8", newline="\n")
        _open_up(target)
        return True
    except OSError:
        return False


def remove_file(base: Path, rel: str):
    target = _target(base, rel)
    if target is None:
        return
    try:
        target.unlink()
        parent = target.parent
        while parent != base and not any(parent.iterdir()):      # drop folders that became empty
            parent.rmdir()
            parent = parent.parent
    except OSError:
        pass


def scan(base: Path) -> dict[str, tuple[int, int]]:
    """path -> (modified time, size) of every regular file outside the ignored folders."""
    found = {}
    for root, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not os.path.islink(os.path.join(root, d))]
        for name in files:
            full = os.path.join(root, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            found[os.path.relpath(full, base).replace(os.sep, "/")] = (st.st_mtime_ns, st.st_size)
            if len(found) >= MAX_SCAN:
                return found
    return found


def read_text(base: Path, rel: str, size: int) -> str | None:
    """File content, or None when it is not a text file the workspace can hold (binary or too large)."""
    if size > settings.MAX_FILE_BYTES:
        return None
    try:
        data = (base / rel).read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def prepare(base: Path, files: list[tuple[str, str]]) -> dict[str, str]:
    """Make the folder equal to the workspace (ignored folders such as node_modules are kept). Returns path -> digest."""
    base.mkdir(parents=True, exist_ok=True)
    _open_up(base)
    wanted = {path: content or "" for path, content in files}
    for rel, (_, size) in scan(base).items():
        if rel not in wanted:
            remove_file(base, rel)
    known = {}
    for rel, content in wanted.items():
        target = _target(base, rel)
        if target is None:
            continue
        current = read_text(base, rel, target.stat().st_size) if target.is_file() else None
        if current == content or write_file(base, rel, content):
            known[rel] = digest(content)
    return known


def syncer_for(base: Path, workspace_id: int, user_id: int, known: dict[str, str], reviewer: bool = False):
    """The sync of a terminal's folder with the workspace - or None for a reviewer.

    A reviewer works in a copy of the submitted files, and that copy must never flow back: the review would
    change what is being reviewed. None switches the write-back off.
    """
    if reviewer:
        return None
    return Syncer(base, workspace_id, user_id, known)


class Syncer:
    def __init__(self, base: Path, workspace_id: int, user_id: int, known: dict[str, str]):
        self.base, self.workspace_id, self.user_id, self.known = base, workspace_id, user_id, dict(known)
        self._stat = {}            # path -> ((mtime, size), digest or None)
        self.note = None           # one message for the user, e.g. the storage limit was hit

    def _disk(self) -> tuple[dict[str, str], set[str]]:
        hashes, unreadable, stat = {}, set(), {}
        for rel, st in scan(self.base).items():
            cached = self._stat.get(rel)
            if cached and cached[0] == st:
                value = cached[1]
            else:
                text = read_text(self.base, rel, st[1])
                value = None if text is None else digest(text)
            stat[rel] = (st, value)
            if value is None:
                unreadable.add(rel)
            else:
                hashes[rel] = value
        self._stat = stat
        return hashes, unreadable

    def tick(self, db) -> bool:
        """One sync pass. Returns True when the workspace files in the database changed."""
        from fastapi import HTTPException
        from app.api.workspaces import _put, check_quota, clean_path, live_files, log_event
        from app.database.models import Task, Workspace, utcnow
        from app.services import workflow as W

        ws = db.get(Workspace, self.workspace_id)
        if ws is None:
            return False
        task = db.get(Task, ws.task_id)
        writable = task is not None and task.status in W.EDITABLE
        rows = {f.path: f for f in live_files(db, ws.id)}
        in_db = {path: digest(f.content) for path, f in rows.items()}
        on_disk, unreadable = self._disk()
        changed, applied = False, 0
        for path in sorted(set(in_db) | set(on_disk) | set(self.known)):
            if path in unreadable:
                continue                                   # binary / too large: lives in the folder only
            d, b, k = on_disk.get(path), in_db.get(path), self.known.get(path)
            if d == b:
                if d is None:
                    self.known.pop(path, None)
                else:
                    self.known[path] = d
                continue
            if b == k:                                     # only the folder changed -> database
                if not writable or applied >= MAX_CHANGES:
                    continue
                if d is None:
                    f = rows[path]
                    f.deleted_at = utcnow()
                    log_event(db, f, self.user_id, "deleted")
                    self.known.pop(path, None)
                else:
                    text = read_text(self.base, path, self._stat[path][0][1])
                    if text is None:
                        continue
                    try:
                        clean_path(path)
                        old = rows.get(path)
                        check_quota(db, ws.id, add_files=0 if old else 1,
                                    add_bytes=len(text.encode()) - (len((old.content or "").encode()) if old else 0))
                    except HTTPException as e:
                        self.note = f"{path} was not copied to the workspace: {e.detail}"
                        self.known[path] = d               # do not retry every second
                        continue
                    _put(db, ws, self.user_id, path, text, "terminal")
                    self.known[path] = d
                changed, applied = True, applied + 1
            else:                                          # the editor changed it (or both did) -> folder
                if b is None:
                    remove_file(self.base, path)
                    self.known.pop(path, None)
                elif write_file(self.base, path, rows[path].content):
                    self.known[path] = b
        if changed:
            ws.last_saved_at = utcnow()
            db.commit()
        return changed

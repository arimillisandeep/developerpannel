import io
import re
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.config import settings
from app.database.connection import get_db
from app.database.models import (FileEvent, FileVersion, Submission, Task, TaskAttachment, User, Workspace,
                                 WorkspaceFile, utcnow)
from app.dependencies.auth import client_ip, get_current_user
from app.schemas import FileRename, FileSave, PathMove, SubmitIn, TemplateApply
from app.services.common import activity, audit, commit, notify
from app.api.tasks import EDITABLE, begin_work, get_task
from app.services import workflow as W

router = APIRouter(prefix="/api", tags=["workspaces"])

PATH_RE = re.compile(r"^[A-Za-z0-9_\-. @+()\[\]]+(/[A-Za-z0-9_\-. @+()\[\]]+)*$")
AUTO_VERSION_SECONDS = 60


def clean_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    if not PATH_RE.match(path) or any(part in ("..", ".") for part in path.split("/")):
        raise HTTPException(422, "Invalid file path. Use letters, numbers, - _ . and / only.")
    return path


def file_dict(f: WorkspaceFile, with_content=True) -> dict:
    d = {"id": f.id, "path": f.path, "updated_at": f.updated_at, "size": len(f.content or "")}
    if with_content:
        d["content"] = f.content
    return d


def live_files(db: Session, ws_id: int):
    return (db.query(WorkspaceFile).filter(WorkspaceFile.workspace_id == ws_id,
                                           WorkspaceFile.deleted_at.is_(None))
            .order_by(WorkspaceFile.path).all())


def workspace_dict(db: Session, ws: Workspace, task: Task, read_only: bool) -> dict:
    subs = db.query(Submission).filter_by(workspace_id=ws.id).order_by(Submission.version_no.desc()).all()
    return {"id": ws.id, "task_id": ws.task_id, "user_id": ws.user_id, "project_id": ws.project_id,
            "last_saved_at": ws.last_saved_at, "read_only": read_only, "task_status": task.status,
            "task_code": task.code, "task_title": task.title, "usage": usage(db, ws.id),
            "files": [file_dict(f) for f in live_files(db, ws.id)],
            "task_requirements": task.requirements, "task_deliverables": task.deliverables,
            "submissions": [{"id": s.id, "version_no": s.version_no, "version": s.version_label, "status": s.status,
                             "submitted_at": s.submitted_at} for s in subs]}


def usage(db: Session, ws_id: int) -> dict:
    files = live_files(db, ws_id)
    return {"files": len(files), "bytes": sum(len((f.content or "").encode()) for f in files),
            "max_files": settings.MAX_FILES_PER_WORKSPACE, "max_bytes": settings.MAX_WORKSPACE_BYTES}


def check_quota(db: Session, ws_id: int, add_files: int = 0, add_bytes: int = 0):
    u = usage(db, ws_id)
    if add_files > 0 and u["files"] + add_files > u["max_files"]:
        raise HTTPException(409, f"File limit for this workspace reached ({u['max_files']} files)")
    if add_bytes > 0 and u["bytes"] + add_bytes > u["max_bytes"]:
        raise HTTPException(413, f"Workspace storage limit reached ({u['max_bytes'] // 1_000_000} MB)")


def _put(db: Session, ws: Workspace, user_id: int, path: str, content: str, kind: str) -> WorkspaceFile:
    """Create a file, or bring back / overwrite the row that already owns this path (history is kept)."""
    f = db.query(WorkspaceFile).filter_by(workspace_id=ws.id, path=path).first()
    if f is None:
        f = WorkspaceFile(workspace_id=ws.id, path=path, content=content)
        db.add(f)
        db.flush()
    else:
        f.content, f.deleted_at = content, None
    _add_version(db, f, user_id, kind)
    return f


def _under(files, path: str):
    """The file at `path`, or every file inside the folder `path`."""
    exact = [f for f in files if f.path == path]
    return exact or [f for f in files if f.path.startswith(path + "/")]


def log_event(db: Session, f: WorkspaceFile, user_id: int, action: str, **kw):
    db.add(FileEvent(workspace_id=f.workspace_id, file_id=f.id, path=f.path, action=action, user_id=user_id, **kw))


def _add_version(db: Session, f: WorkspaceFile, user_id: int, kind: str):
    """Store a new version of the file and write the matching entry of the file change log."""
    prev = db.query(FileVersion).filter_by(file_id=f.id).order_by(FileVersion.version_no.desc()).first()
    last = prev.version_no if prev else 0
    db.add(FileVersion(file_id=f.id, version_no=last + 1, content=f.content, saved_by=user_id, kind=kind))
    plus, minus = W.line_stat(prev.content if prev else "", f.content or "")
    action = "created" if prev is None else "restored" if kind == "restore" else "edited"
    log_event(db, f, user_id, action, prev_version_no=last or None, version_no=last + 1,
              summary=f"+{plus} -{minus} lines")


def owned_workspace(db: Session, actor: User, ws_id: int, for_write: bool) -> tuple[Workspace, Task]:
    """Workspaces are private: only the owner writes. Admin, and the Developer leading the
    owner's team, may read."""
    ws = db.get(Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    task = db.get(Task, ws.task_id)
    is_owner = ws.user_id == actor.id
    can_read = is_owner or P.can_read_workspace(db, actor, ws.user_id, task)
    if not can_read or (for_write and not is_owner):
        raise HTTPException(403, "You cannot access this workspace")
    if for_write and task.status == "assigned":
        raise HTTPException(409, "Accept the task first. Files can be changed after you accept it.")
    if for_write and task.status not in EDITABLE:
        raise HTTPException(409, f"The task is '{task.status}'. Files are locked.")
    return ws, task


@router.get("/tasks/{task_id}/workspace")
def open_workspace(task_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = get_task(db, actor, task_id)
    if task.assigned_to == actor.id:
        ws = db.query(Workspace).filter_by(task_id=task.id, user_id=actor.id).first()
        if not ws:
            ws = Workspace(task_id=task.id, user_id=actor.id, project_id=task.project_id)
            db.add(ws)
            db.flush()
            f = WorkspaceFile(workspace_id=ws.id, path="README.md",
                              content=f"# {task.code} - {task.title}\n\n{task.requirements or ''}\n")
            db.add(f)
            db.flush()
            _add_version(db, f, actor.id, "auto")
            activity(db, actor.id, "workspace.create", {"task_id": task.id})
            commit(db)
        return workspace_dict(db, ws, task, read_only=task.status not in EDITABLE)
    ws = db.query(Workspace).filter_by(task_id=task.id, user_id=task.assigned_to).first()
    if not ws:
        raise HTTPException(404, "The assignee has not opened a workspace for this task yet")
    owned_workspace(db, actor, ws.id, for_write=False)
    return workspace_dict(db, ws, task, read_only=True)


@router.put("/workspaces/{ws_id}/files")
def save_file(ws_id: int, body: FileSave, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create or update one file. Auto-saves are folded into one version per minute;
    a manual save always writes a new version."""
    ws, task = owned_workspace(db, actor, ws_id, for_write=True)
    path = clean_path(body.path)
    if len(body.content.encode()) > settings.MAX_FILE_BYTES:
        raise HTTPException(413, "File is larger than the 1 MB limit")
    now = utcnow()
    f = db.query(WorkspaceFile).filter_by(workspace_id=ws.id, path=path).first()
    if f is None:
        check_quota(db, ws.id, add_files=1, add_bytes=len(body.content.encode()))
        f = WorkspaceFile(workspace_id=ws.id, path=path, content=body.content)
        db.add(f)
        db.flush()
        _add_version(db, f, actor.id, "manual" if body.manual else "auto")
    else:
        restored = f.deleted_at is not None
        f.deleted_at = None
        if restored or f.content != body.content:
            check_quota(db, ws.id, add_files=1 if restored else 0,
                        add_bytes=len(body.content.encode()) - (0 if restored else len((f.content or "").encode())))
            f.content = body.content
            last = db.query(FileVersion).filter_by(file_id=f.id).order_by(FileVersion.version_no.desc()).first()
            fold = (not body.manual and last is not None and last.kind == "auto"
                    and (now - last.created_at).total_seconds() < AUTO_VERSION_SECONDS)
            if fold:
                last.content = body.content
            else:
                _add_version(db, f, actor.id, "manual" if body.manual else "auto")
        elif body.manual:
            last = db.query(FileVersion).filter_by(file_id=f.id).order_by(FileVersion.version_no.desc()).first()
            if last is not None and last.kind == "auto":
                last.kind = "manual"
    ws.last_saved_at = now
    begin_work(db, task, actor)
    commit(db)
    return {"file": file_dict(f), "last_saved_at": ws.last_saved_at, "task_status": task.status}


def _file(db: Session, ws_id: int, file_id: int) -> WorkspaceFile:
    f = db.get(WorkspaceFile, file_id)
    if not f or f.workspace_id != ws_id:
        raise HTTPException(404, "File not found")
    return f


@router.post("/workspaces/{ws_id}/files/{file_id}/rename")
def rename_file(ws_id: int, file_id: int, body: FileRename, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    ws, _ = owned_workspace(db, actor, ws_id, for_write=True)
    f = _file(db, ws.id, file_id)
    new_path = clean_path(body.new_path)
    clash = db.query(WorkspaceFile).filter_by(workspace_id=ws.id, path=new_path).first()
    if clash and clash.id != f.id:
        if clash.deleted_at is None:
            raise HTTPException(409, "A file with that name already exists")
        clash.path = f"{clash.path}.deleted-{clash.id}"  # free the name, keep its history
        db.flush()
    old_path, f.path = f.path, new_path
    if old_path != new_path:
        log_event(db, f, actor.id, "renamed", from_path=old_path, summary=f"{old_path} -> {new_path}")
    ws.last_saved_at = utcnow()
    commit(db)
    return file_dict(f)


@router.delete("/workspaces/{ws_id}/files/{file_id}")
def delete_file(ws_id: int, file_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws, _ = owned_workspace(db, actor, ws_id, for_write=True)
    f = _file(db, ws.id, file_id)
    f.deleted_at = utcnow()  # soft delete: versions stay recoverable
    log_event(db, f, actor.id, "deleted")
    ws.last_saved_at = utcnow()
    commit(db)
    return {"ok": True}


@router.get("/workspaces/{ws_id}/files/{file_id}/versions")
def versions(ws_id: int, file_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws, _ = owned_workspace(db, actor, ws_id, for_write=False)
    f = _file(db, ws.id, file_id)
    rows = db.query(FileVersion).filter_by(file_id=f.id).order_by(FileVersion.version_no.desc()).all()
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_({v.saved_by for v in rows} or {-1})).all())
    return [{"id": v.id, "version_no": v.version_no, "kind": v.kind, "created_at": v.created_at,
             "saved_by": v.saved_by, "saved_by_name": names.get(v.saved_by),
             "size": len(v.content), "content": v.content} for v in rows]


@router.get("/workspaces/{ws_id}/history")
def file_history(ws_id: int, path: str | None = None, limit: int = 300, actor: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """File change log of the workspace: created, edited, renamed, deleted, restored, submitted; newest first."""
    ws, _ = owned_workspace(db, actor, ws_id, for_write=False)
    q = db.query(FileEvent).filter_by(workspace_id=ws.id)
    if path:
        ids = {f.id for f in db.query(WorkspaceFile).filter_by(workspace_id=ws.id, path=path)}
        q = q.filter(FileEvent.file_id.in_(ids or {-1}))
    rows = q.order_by(FileEvent.id.desc()).limit(min(max(limit, 1), 1000)).all()
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_({e.user_id for e in rows} or {-1})).all())
    labels = dict(db.query(Submission.id, Submission.version_label).filter_by(workspace_id=ws.id).all())
    return [{"id": e.id, "file_id": e.file_id, "path": e.path, "action": e.action, "from_path": e.from_path,
             "previous_version": e.prev_version_no, "new_version": e.version_no, "modified_by": e.user_id,
             "modified_by_name": names.get(e.user_id), "at": e.created_at, "summary": e.summary,
             "submission_version": labels.get(e.submission_id)} for e in rows]


@router.post("/workspaces/{ws_id}/files/{file_id}/versions/{version_id}/restore")
def restore(ws_id: int, file_id: int, version_id: int, actor: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    ws, _ = owned_workspace(db, actor, ws_id, for_write=True)
    f = _file(db, ws.id, file_id)
    v = db.get(FileVersion, version_id)
    if not v or v.file_id != f.id:
        raise HTTPException(404, "Version not found")
    f.content, f.deleted_at = v.content, None
    _add_version(db, f, actor.id, "restore")
    ws.last_saved_at = utcnow()
    commit(db)
    return file_dict(f)


@router.post("/workspaces/{ws_id}/submit", status_code=201)
def submit(ws_id: int, request: Request, body: SubmitIn | None = None, actor: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """Freeze the whole project into a new immutable version and route it:
    Off-Roll / Intern -> On-Roll review -> Admin.   On-Roll -> Admin directly."""
    ws, task = owned_workspace(db, actor, ws_id, for_write=True)
    files = live_files(db, ws.id)
    if not any((f.content or "").strip() for f in files if f.path != "README.md"):
        raise HTTPException(422, "Add at least one non-empty file (other than README.md) before submitting")
    snapshot = [{"path": f.path, "content": f.content} for f in files]
    previous = db.query(Submission).filter_by(task_id=task.id).order_by(Submission.version_no.desc()).first()
    new_files = db.query(TaskAttachment).filter_by(task_id=task.id, kind="deliverable", submission_id=None,
                                                   deleted_at=None).all()
    if previous is not None and not new_files and W.as_map(previous.snapshot) == W.as_map(snapshot):
        raise HTTPException(409, f"Nothing changed since version {previous.version_label}. Change the project before "
                                 "submitting again.")
    now = utcnow()
    authors = {}
    for f in files:
        last = db.query(FileVersion).filter_by(file_id=f.id).order_by(FileVersion.version_no.desc()).first()
        if last is None or last.content != f.content:
            _add_version(db, f, actor.id, "submit")
            who, when = actor.id, now
        else:
            last.kind = "submit"
            who, when = last.saved_by, last.created_at
        authors[f.path] = {"user_id": who, "at": when.isoformat() if when else None}
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_({a["user_id"] for a in authors.values()} or {-1})).all())
    for a in authors.values():
        a["name"] = names.get(a["user_id"])
    version_no = (previous.version_no if previous else 0) + 1
    first_review = actor.role in P.ONROLL_REVIEW_FIRST
    sub = Submission(task_id=task.id, workspace_id=ws.id, submitted_by=actor.id, submitter_role=actor.role,
                     version_no=version_no, version_label=W.next_label(db, task), snapshot=snapshot,
                     note=(body.note or "").strip() or None if body else None,
                     changes=W.changes_between(previous.snapshot if previous else [], snapshot), authors=authors,
                     stage="onroll_review" if first_review else "admin_review",
                     status="pending_onroll_review" if first_review else "pending_admin_review",
                     submitted_at=now)
    db.add(sub)
    db.flush()
    for f in files:
        log_event(db, f, actor.id, "submitted", submission_id=sub.id, summary=f"version {sub.version_label}")
    for a in new_files:                       # deliverables uploaded for this version are frozen with it
        a.submission_id = sub.id
    task.submitted_at = now
    task.review_status = sub.status
    ws.last_saved_at = now
    begin_work(db, task, actor)               # submitted straight after accepting
    W.move(db, task, actor, "resubmitted" if previous else "submitted", "resubmitted" if previous else "submitted",
           sub.note, sub.id)
    W.record(db, task, actor, "version_created", task.status, task.status, f"Version {sub.version_label}", sub.id)
    W.move(db, task, None, "sent_to_onroll_review" if first_review else "sent_to_admin_review",
           "under_onroll_review" if first_review else "under_admin_review", None, sub.id)
    word = "resubmitted" if previous else "submitted"
    notify(db, P.reviewers_for(db, sub, task), "task_resubmitted" if previous else "task_submitted",
           f"{actor.full_name} {word} {task.code}",
           f"{task.title} (v{sub.version_label}) is waiting for your review", f"/reviews/{sub.id}")
    activity(db, actor.id, "submission.create", {"task_id": task.id, "submission_id": sub.id,
                                                  "version": sub.version_label}, ip=client_ip(request))
    audit(db, actor, "submission.create", "submissions", sub.id,
          new={"task_id": task.id, "stage": sub.stage, "version": sub.version_label}, ip=client_ip(request))
    commit(db)
    return {"id": sub.id, "version_no": version_no, "version": sub.version_label, "stage": sub.stage,
            "status": sub.status, "task_status": task.status}


# ---- explorer operations on files and folders ---------------------------------------------
@router.post("/workspaces/{ws_id}/move")
def move_path(ws_id: int, body: PathMove, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Rename or move a file or a whole folder. Rows keep their ids, so version history follows the file."""
    ws, _ = owned_workspace(db, actor, ws_id, for_write=True)
    src, dst = clean_path(body.from_path), clean_path(body.to_path)
    files = live_files(db, ws.id)
    moving = _under(files, src)
    if not moving:
        raise HTTPException(404, "Nothing found at that path")
    if dst == src or dst.startswith(src + "/"):
        raise HTTPException(422, "A folder cannot be moved into itself")
    targets = {f.id: dst + f.path[len(src):] for f in moving}
    if any(len(p) > 300 for p in targets.values()):
        raise HTTPException(422, "The new path is too long")
    ids = set(targets)
    taken = {f.path for f in files if f.id not in ids}
    clash = sorted(set(targets.values()) & taken)
    if clash:
        raise HTTPException(409, f"Already exists: {clash[0]}")
    for old in db.query(WorkspaceFile).filter(WorkspaceFile.workspace_id == ws.id, WorkspaceFile.deleted_at.isnot(None),
                                              WorkspaceFile.path.in_(list(targets.values()))):
        old.path = f"{old.path}.deleted-{old.id}"       # free the name, keep the old file's history
    db.flush()
    old_paths = {f.id: f.path for f in moving}
    for f in moving:
        f.path = f"__moving__{f.id}"
    db.flush()
    for f in moving:
        f.path = targets[f.id]
        log_event(db, f, actor.id, "renamed", from_path=old_paths[f.id], summary=f"{old_paths[f.id]} -> {f.path}")
    ws.last_saved_at = utcnow()
    commit(db)
    return {"files": [file_dict(f, with_content=False) for f in moving]}


@router.post("/workspaces/{ws_id}/copy", status_code=201)
def copy_path(ws_id: int, body: PathMove, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Copy a file or a whole folder."""
    ws, _ = owned_workspace(db, actor, ws_id, for_write=True)
    src, dst = clean_path(body.from_path), clean_path(body.to_path)
    files = live_files(db, ws.id)
    copying = _under(files, src)
    if not copying:
        raise HTTPException(404, "Nothing found at that path")
    if dst == src or dst.startswith(src + "/"):
        raise HTTPException(422, "Choose a different name for the copy")
    taken = {f.path for f in files}
    targets = [(dst + f.path[len(src):], f.content) for f in copying]
    clash = sorted({p for p, _ in targets} & taken)
    if clash:
        raise HTTPException(409, f"Already exists: {clash[0]}")
    check_quota(db, ws.id, add_files=len(targets), add_bytes=sum(len((c or "").encode()) for _, c in targets))
    made = [_put(db, ws, actor.id, clean_path(p), c, "manual") for p, c in targets]
    ws.last_saved_at = utcnow()
    commit(db)
    return {"files": [file_dict(f) for f in made]}


@router.delete("/workspaces/{ws_id}/folder")
def delete_folder(ws_id: int, path: str, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws, _ = owned_workspace(db, actor, ws_id, for_write=True)
    prefix = clean_path(path) + "/"
    gone = [f for f in live_files(db, ws.id) if f.path.startswith(prefix)]
    if not gone:
        raise HTTPException(404, "Folder not found")
    now = utcnow()
    for f in gone:
        f.deleted_at = now        # soft delete: versions stay recoverable
        log_event(db, f, actor.id, "deleted")
    ws.last_saved_at = now
    commit(db)
    return {"deleted": [f.id for f in gone]}


@router.get("/workspaces/{ws_id}/download")
def download_project(ws_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The whole project as a zip. Owner, their team's Developer and Admins."""
    ws, task = owned_workspace(db, actor, ws_id, for_write=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in live_files(db, ws.id):
            z.writestr(f.path, f.content or "")
    if actor.id != ws.user_id:
        audit(db, actor, "workspace.download", "workspaces", ws.id, ip=client_ip(request))
        commit(db)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{task.code}.zip"'})


# ---- project templates --------------------------------------------------------------------
@router.get("/templates")
def list_templates(actor: User = Depends(get_current_user)):
    from app.core.project_templates import TEMPLATES
    return [{"id": t["id"], "name": t["name"], "group": t["group"], "verified": t["verified"], "needs": t["needs"],
             "open": t["open"], "files": sorted(t["files"])} for t in TEMPLATES]


@router.post("/workspaces/{ws_id}/template", status_code=201)
def apply_template(ws_id: int, body: TemplateApply, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add a template's files to the workspace. Existing files are only replaced when overwrite=true
    (their previous content stays in the version history)."""
    from app.core.project_templates import BY_ID
    ws, task = owned_workspace(db, actor, ws_id, for_write=True)
    t = BY_ID.get(body.template_id)
    if not t:
        raise HTTPException(404, "Unknown template")
    existing = {f.path: f for f in live_files(db, ws.id)}
    # the task README that every workspace starts with is kept, it does not count as a conflict
    keep = {"README.md"} & set(existing) if not body.overwrite else set()
    clash = sorted((set(t["files"]) & set(existing)) - keep)
    if clash and not body.overwrite:
        raise HTTPException(409, {"message": "These files already exist", "files": clash})
    new = [p for p in t["files"] if p not in existing]
    check_quota(db, ws.id, add_files=len(new), add_bytes=sum(len(c.encode()) for c in t["files"].values()))
    for path, content in t["files"].items():
        if path in keep or (path in existing and existing[path].content == content):
            continue
        _put(db, ws, actor.id, clean_path(path), content, "manual")
    ws.last_saved_at = utcnow()
    begin_work(db, task, actor)
    activity(db, actor.id, "workspace.template", {"workspace_id": ws.id, "template": t["id"]})
    commit(db)
    return {"template": t["id"], "open": t["open"], "replaced": clash, "files": [file_dict(f) for f in live_files(db, ws.id)],
            "task_status": task.status, "last_saved_at": ws.last_saved_at}

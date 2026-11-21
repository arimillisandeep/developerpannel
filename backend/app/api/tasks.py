import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.config import settings
from app.database.connection import get_db
from app.database.models import (Project, Review, Submission, Task, TaskAssignment, TaskAttachment, TaskTime, User,
                                 utcnow)
from app.dependencies.auth import client_ip, get_current_user
from app.schemas import NoteIn, TaskCreate, TaskUpdate
from app.services import workflow as W
from app.services.common import activity, audit, commit, notify

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

STATUSES = W.STATUSES
EDITABLE = W.EDITABLE
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
BLOCKED_EXTENSIONS = {"exe", "msi", "bat", "cmd", "com", "scr", "ps1", "vbs", "jar", "dll", "sh", "apk", "app", "dmg"}


def task_code(task_id: int) -> str:
    return f"WC-{task_id:04d}"


def can_see_task(db: Session, actor: User, t: Task) -> bool:
    if actor.role == P.ADMIN or actor.id in (t.assigned_to, t.assigned_by, t.reviewer_id):
        return True
    if actor.role not in P.LEADS:
        return False
    if t.assigned_to in P.team_member_ids(db, actor.id):
        return True
    for s in db.query(Submission).filter_by(task_id=t.id):       # a reviewer of one of its versions
        if P.can_review(db, actor, s, t) or db.query(Review.id).filter_by(submission_id=s.id, reviewer_id=actor.id).first():
            return True
    return False


def can_manage_task(actor: User, t: Task) -> bool:
    return actor.role == P.ADMIN or (actor.id == t.assigned_by and bool(P.ASSIGN_MATRIX.get(actor.role)))


def task_dict(db: Session, t: Task, names: dict | None = None) -> dict:
    def name(uid):
        if uid is None:
            return None
        if names is not None and uid in names:
            return names[uid]
        u = db.get(User, uid)
        return u.full_name if u else None
    proj = db.get(Project, t.project_id) if t.project_id else None
    return {"id": t.id, "code": t.code, "title": t.title, "description": t.description,
            "requirements": t.requirements, "deliverables": t.deliverables,
            "project_id": t.project_id, "project": proj.name if proj else None,
            "assigned_by": t.assigned_by, "assigned_by_name": name(t.assigned_by),
            "assigned_to": t.assigned_to, "assigned_to_name": name(t.assigned_to),
            "reviewer_id": t.reviewer_id, "reviewer_name": name(t.reviewer_id), "group_code": t.group_code,
            "priority": t.priority, "start_date": t.start_date, "deadline": t.deadline,
            "estimated_hours": float(t.estimated_hours) if t.estimated_hours is not None else None,
            "status": t.status, "review_status": t.review_status, "submitted_at": t.submitted_at,
            "accepted_at": t.accepted_at, "started_at": t.started_at, "completed_at": t.completed_at,
            "cancelled_at": t.cancelled_at, "archived_at": t.archived_at,
            "created_at": t.created_at, "updated_at": t.updated_at}


def get_task(db: Session, actor: User, task_id: int) -> Task:
    t = db.get(Task, task_id)
    if not t or t.deleted_at is not None:
        raise HTTPException(404, "Task not found")
    if not can_see_task(db, actor, t):
        raise HTTPException(403, "You cannot access this task")
    return t


def reviewable_task_ids(db: Session, actor: User) -> set[int]:
    """Tasks this person has to review (or already reviewed) but does not own.

    The review queue accepts more people than the team rule does - the On-Roll reviewer named on the task, and,
    for a submitter without a team, any On-Roll employee. Those people must also find the task in their own task
    list, otherwise the queue shows work they cannot open.
    """
    if actor.role != P.ONROLL:
        return set()
    ids = {s.task_id for s in db.query(Submission).filter(Submission.stage == "onroll_review").all()
           if P.can_review(db, actor, s)}
    mine = (db.query(Submission.task_id).join(Review, Review.submission_id == Submission.id)
            .filter(Review.reviewer_id == actor.id).all())
    ids |= {r[0] for r in mine}
    return {i for i in ids if i is not None}


def visible_tasks(db: Session, actor: User):
    q = db.query(Task).filter(Task.deleted_at.is_(None))
    if actor.role == P.ADMIN:
        return q
    conds = [Task.assigned_to == actor.id, Task.assigned_by == actor.id, Task.reviewer_id == actor.id]
    if actor.role in P.LEADS:
        ids = P.team_member_ids(db, actor.id)
        if ids:
            conds.append(Task.assigned_to.in_(ids))
    reviewable = reviewable_task_ids(db, actor)
    if reviewable:
        conds.append(Task.id.in_(reviewable))
    return q.filter(or_(*conds))


@router.get("")
def list_tasks(scope: str = Query("all", pattern="^(all|mine|assigned_by_me)$"), status: str | None = None,
               assigned_to: int | None = None, project_id: int | None = None, archived: bool = False,
               actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if W.send_deadline_reminders(db):
        commit(db)
    q = visible_tasks(db, actor)
    if scope == "mine":
        q = q.filter(Task.assigned_to == actor.id)
    elif scope == "assigned_by_me":
        q = q.filter(Task.assigned_by == actor.id)
    if status:
        q = q.filter(Task.status.in_(status.split(",")))
    elif not archived:
        q = q.filter(Task.status != "archived")
    if assigned_to:
        q = q.filter(Task.assigned_to == assigned_to)
    if project_id:
        q = q.filter(Task.project_id == project_id)
    rows = q.order_by(Task.id.desc()).all()
    ids = {t.assigned_to for t in rows} | {t.assigned_by for t in rows} | {t.reviewer_id for t in rows if t.reviewer_id}
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_(ids or {-1})).all())
    return [task_dict(db, t, names) for t in rows]


def _assignee(db: Session, actor: User, user_id: int) -> User:
    target = db.get(User, user_id)
    if not target or target.deleted_at is not None:
        raise HTTPException(404, "Assignee not found")
    if not P.can_assign(db, actor, target):
        raise HTTPException(403, f"A {actor.role} user cannot assign tasks to this person")
    return target


def _reviewer(db: Session, reviewer_id: int | None, assignee_ids) -> None:
    if reviewer_id is None:
        return
    if not P.can_be_reviewer(db.get(User, reviewer_id)):
        raise HTTPException(422, "The reviewer must be an active On-Roll employee")
    if reviewer_id in assignee_ids:
        raise HTTPException(422, "The reviewer cannot be the person doing the task")


@router.post("", status_code=201)
def create_task(body: TaskCreate, request: Request, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """One task per assignee. Several assignees get separate tasks (own Task ID, workspace and review) that share
    a group code."""
    if not P.ASSIGN_MATRIX.get(actor.role):
        raise HTTPException(403, f"{actor.role} users cannot assign tasks")
    ids = list(dict.fromkeys(([body.assigned_to] if body.assigned_to else []) + (body.assigned_to_ids or [])))
    if not ids:
        raise HTTPException(422, "Choose at least one person to assign the task to")
    targets = [_assignee(db, actor, i) for i in ids]
    _reviewer(db, body.reviewer_id, ids)
    if body.project_id and not db.get(Project, body.project_id):
        raise HTTPException(422, "Project does not exist")
    if body.start_date and body.deadline and body.deadline < body.start_date:
        raise HTTPException(422, "Deadline cannot be before the start date")
    data = body.model_dump(exclude={"assigned_to", "assigned_to_ids"})
    created = []
    for target in targets:
        t = Task(**data, assigned_to=target.id, assigned_by=actor.id, status="created", review_status="none")
        db.add(t)
        db.flush()
        t.code = task_code(t.id)
        created.append(t)
    group = f"G-{created[0].id:04d}" if len(created) > 1 else None
    for t, target in zip(created, targets):
        t.group_code = group
        db.add(TaskAssignment(task_id=t.id, assigned_by=actor.id, assigned_to=target.id))
        W.record(db, t, actor, "created", None, "created")
        W.move(db, t, actor, "assigned", "assigned", f"Assigned to {target.full_name}")
        audit(db, actor, "task.create", "tasks", t.id, new={"title": t.title, "assigned_to": target.id},
              ip=client_ip(request))
        notify(db, [target.id], "task_assigned", f"New task: {t.title}", f"Assigned by {actor.full_name}",
               f"/tasks/{t.id}")
        if t.reviewer_id:
            notify(db, [t.reviewer_id], "review_assigned", f"You are the reviewer of {t.code}", t.title, f"/tasks/{t.id}")
    commit(db)
    d = task_dict(db, created[0])
    d["created"] = [{"id": t.id, "code": t.code, "assigned_to": t.assigned_to} for t in created]
    return d


def _time(db: Session, t: Task) -> dict:
    row = db.query(TaskTime).filter_by(task_id=t.id, user_id=t.assigned_to).first()
    subs = db.query(Submission).filter_by(task_id=t.id).all()
    review = sum(int((s.decided_at - s.submitted_at).total_seconds()) for s in subs if s.decided_at)
    return {"active_seconds": row.active_seconds if row else 0, "paused_seconds": row.paused_seconds if row else 0,
            "total_seconds": (row.active_seconds + row.paused_seconds) if row else 0,
            "first_work_at": row.first_at if row else None, "last_work_at": row.last_at if row else None,
            "started_at": t.started_at, "submitted_at": t.submitted_at, "completed_at": t.completed_at,
            "review_seconds": review}


OPEN_IN_EDITOR = {"py", "js", "jsx", "ts", "tsx", "html", "htm", "css", "scss", "json", "md", "txt", "csv",
                  "yml", "yaml", "sql", "java", "c", "h", "cpp", "cs", "php", "rb", "go", "rs", "kt", "swift",
                  "sh", "xml", "log", "ipynb", "env", "ini", "conf", "vue", "svelte"}
OPEN_IN_PREVIEW = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"}


def open_mode(name: str) -> str:
    """editor = copy into the workspace; preview = show here; download = Download only."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in OPEN_IN_EDITOR:
        return "editor"
    if ext in OPEN_IN_PREVIEW:
        return "preview"
    return "download"


def attachment_dict(a: TaskAttachment, names: dict) -> dict:
    return {"id": a.id, "kind": a.kind, "filename": a.filename, "size_bytes": a.size_bytes,
            "uploaded_by": a.uploaded_by, "uploaded_by_name": names.get(a.uploaded_by), "created_at": a.created_at,
            "submission_id": a.submission_id,
            # lets the screen know which button to draw without keeping its own list of extensions
            "open_mode": open_mode(a.filename)}


def attachments(db: Session, task_id: int) -> list[dict]:
    rows = db.query(TaskAttachment).filter_by(task_id=task_id, deleted_at=None).order_by(TaskAttachment.id).all()
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_({a.uploaded_by for a in rows} or {-1})).all())
    return [attachment_dict(a, names) for a in rows]


@router.get("/{task_id}")
def read_task(task_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    d = task_dict(db, t)
    d["can_manage"] = can_manage_task(actor, t)
    d["is_assignee"] = t.assigned_to == actor.id
    hist = db.query(TaskAssignment).filter_by(task_id=t.id).order_by(TaskAssignment.id).all()
    d["assignment_history"] = [{"assigned_by": h.assigned_by, "assigned_to": h.assigned_to,
                                "at": h.created_at} for h in hist]
    d["time"] = _time(db, t)
    d["attachments"] = attachments(db, t.id)
    if t.group_code:
        d["group"] = [{"id": g.id, "code": g.code, "assigned_to": g.assigned_to, "status": g.status}
                      for g in db.query(Task).filter_by(group_code=t.group_code, deleted_at=None).order_by(Task.id)
                      if can_see_task(db, actor, g)]
    return d


@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskUpdate, request: Request, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    if not can_manage_task(actor, t):
        raise HTTPException(403, "Only the assigner or an admin can edit this task")
    if t.status in W.CLOSED:
        raise HTTPException(409, f"A {t.status} task cannot be edited")
    data = body.model_dump(exclude_unset=True)
    prev, new = {}, {}
    reassigned = "assigned_to" in data and data["assigned_to"] != t.assigned_to
    if reassigned:
        if t.status not in W.REASSIGNABLE:
            raise HTTPException(409, "A task that has been submitted cannot be re-assigned")
        target = _assignee(db, actor, data["assigned_to"])
        db.add(TaskAssignment(task_id=t.id, assigned_by=actor.id, assigned_to=target.id))
        notify(db, [target.id], "task_assigned", f"New task: {t.title}", f"Assigned by {actor.full_name}",
               f"/tasks/{t.id}")
        notify(db, [t.assigned_to], "task_updated", f"{t.code} was re-assigned to someone else", t.title, "/tasks")
    if "reviewer_id" in data and data["reviewer_id"] != t.reviewer_id:
        _reviewer(db, data["reviewer_id"], {data.get("assigned_to", t.assigned_to)})
        if data["reviewer_id"]:
            notify(db, [data["reviewer_id"]], "review_assigned", f"You are the reviewer of {t.code}", t.title, f"/tasks/{t.id}")
    if data.get("project_id") and not db.get(Project, data["project_id"]):
        raise HTTPException(422, "Project does not exist")
    for k, v in data.items():
        if getattr(t, k) != v:
            prev[k], new[k] = getattr(t, k), v
            setattr(t, k, v)
    if reassigned:
        t.accepted_at = t.started_at = None
        W.move(db, t, actor, "reassigned", "assigned", f"Re-assigned to {target.full_name}")
    if new:
        if not reassigned:
            W.record(db, t, actor, "edited", t.status, t.status, ", ".join(sorted(new)))
        audit(db, actor, "task.update", "tasks", t.id, previous=prev, new=new, ip=client_ip(request))
        if not reassigned:
            notify(db, [t.assigned_to], "task_updated", f"Task updated: {t.title}", None, f"/tasks/{t.id}")
        commit(db)
    return task_dict(db, t)


def _own(db: Session, actor: User, task_id: int) -> Task:
    t = get_task(db, actor, task_id)
    if t.assigned_to != actor.id:
        raise HTTPException(403, "Only the assignee can do this")
    return t


@router.post("/{task_id}/accept")
def accept_task(task_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _own(db, actor, task_id)
    if t.status != "assigned":
        raise HTTPException(409, f"The task is already '{t.status}'")
    t.accepted_at = utcnow()
    W.move(db, t, actor, "accepted", "accepted")
    notify(db, [t.assigned_by], "task_accepted", f"{actor.full_name} accepted {t.code}", t.title, f"/tasks/{t.id}")
    commit(db)
    return task_dict(db, t)


def begin_work(db: Session, t: Task, actor: User):
    """accepted -> in_progress, once."""
    if t.status == "accepted":
        t.started_at = t.started_at or utcnow()
        W.move(db, t, actor, "work_started", "in_progress")
        activity(db, actor.id, "task.start", {"task_id": t.id})


@router.post("/{task_id}/start")
def start_task(task_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _own(db, actor, task_id)
    if t.status == "assigned":
        raise HTTPException(409, "Accept the task before starting it")
    if t.status == "accepted":
        begin_work(db, t, actor)
        commit(db)
    return task_dict(db, t)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: int, body: NoteIn, request: Request, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    if not can_manage_task(actor, t):
        raise HTTPException(403, "Only the assigner or an admin can cancel this task")
    if t.status in W.CLOSED:
        raise HTTPException(409, f"The task is already '{t.status}'")
    if t.status in W.IN_REVIEW and actor.role != P.ADMIN:
        raise HTTPException(409, "A task that is under review can only be cancelled by an admin")
    if not (body.comment or "").strip():
        raise HTTPException(422, "Give a reason for cancelling")
    for s in db.query(Submission).filter(Submission.task_id == t.id, Submission.stage != "closed"):
        s.stage, s.status, s.decided_at = "closed", "cancelled", utcnow()
    t.cancelled_at, t.review_status = utcnow(), "none"
    W.move(db, t, actor, "cancelled", "cancelled", body.comment)
    audit(db, actor, "task.cancel", "tasks", t.id, new={"reason": body.comment}, ip=client_ip(request))
    notify(db, [t.assigned_to], "task_cancelled", f"{t.code} was cancelled", body.comment, f"/tasks/{t.id}")
    commit(db)
    return task_dict(db, t)


@router.post("/{task_id}/archive")
def archive_task(task_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    if actor.role != P.ADMIN:
        raise HTTPException(403, "Only an admin can archive tasks")
    if t.status not in ("completed", "cancelled"):
        raise HTTPException(409, "Only completed or cancelled tasks can be archived")
    t.archived_at = utcnow()
    W.move(db, t, actor, "archived", "archived")
    audit(db, actor, "task.archive", "tasks", t.id, ip=client_ip(request))
    commit(db)
    return task_dict(db, t)


@router.post("/{task_id}/reopen")
def reopen_task(task_id: int, body: NoteIn, request: Request, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Admin asks for a new major revision of a completed task. The next submission becomes version N+1.0."""
    t = get_task(db, actor, task_id)
    if actor.role != P.ADMIN:
        raise HTTPException(403, "Only an admin can reopen a completed task")
    if t.status != "completed":
        raise HTTPException(409, "Only a completed task can be reopened")
    if not (body.comment or "").strip():
        raise HTTPException(422, "Describe what the new revision must contain")
    t.completed_at, t.review_status = None, "changes_requested"
    W.move(db, t, actor, "reopened", "rework_required", body.comment)
    audit(db, actor, "task.reopen", "tasks", t.id, new={"reason": body.comment}, ip=client_ip(request))
    notify(db, [t.assigned_to], "changes_requested", f"New revision requested: {t.code}", body.comment, f"/tasks/{t.id}")
    commit(db)
    return task_dict(db, t)


@router.delete("/{task_id}")
def delete_task(task_id: int, request: Request, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Retention rule: a task is never erased. Delete hides it; its workspace, versions, reviews and history stay
    in the database. A task that already has submissions can only be removed by an admin."""
    t = get_task(db, actor, task_id)
    if not can_manage_task(actor, t):
        raise HTTPException(403, "Only the assigner or an admin can delete this task")
    has_versions = db.query(Submission.id).filter_by(task_id=t.id).first() is not None
    if has_versions and actor.role != P.ADMIN:
        raise HTTPException(409, "A submitted task can only be removed by an admin")
    if t.status in W.IN_REVIEW:
        raise HTTPException(409, "Decide or cancel the pending review before removing this task")
    t.deleted_at = utcnow()
    W.record(db, t, actor, "deleted", t.status, t.status)
    audit(db, actor, "task.delete", "tasks", t.id, previous={"title": t.title}, ip=client_ip(request))
    commit(db)
    return {"ok": True}


@router.get("/{task_id}/history")
def task_history(task_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    return W.history(db, t.id)


# ---- versions ---------------------------------------------------------------------------
def version_dict(db: Session, s: Submission, names: dict) -> dict:
    reviews = (db.query(Review, User.full_name).join(User, User.id == Review.reviewer_id)
               .filter(Review.submission_id == s.id).order_by(Review.id).all())
    return {"id": s.id, "version_no": s.version_no, "version": s.version_label, "task_id": s.task_id,
            "submitted_by": s.submitted_by, "submitted_by_name": names.get(s.submitted_by),
            "submitter_role": s.submitter_role, "submitted_at": s.submitted_at, "decided_at": s.decided_at,
            "note": s.note, "stage": s.stage, "status": s.status, "file_count": len(s.snapshot or []),
            "changes": s.changes or {"added": [], "modified": [], "deleted": []}, "authors": s.authors or {},
            "reviews": [{"reviewer": n, "stage": r.stage, "decision": r.decision, "comment": r.comment,
                         "created_at": r.created_at} for r, n in reviews]}


@router.get("/{task_id}/versions")
def task_versions(task_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every submitted version of the task, newest first. Versions are never changed or removed."""
    t = get_task(db, actor, task_id)
    rows = db.query(Submission).filter_by(task_id=t.id).order_by(Submission.version_no.desc()).all()
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_({s.submitted_by for s in rows} or {-1})).all())
    return [version_dict(db, s, names) for s in rows]


@router.get("/{task_id}/compare")
def compare_versions(task_id: int, a: int = Query(..., description="older submission id"),
                     b: int = Query(..., description="newer submission id"),
                     actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    one, two = db.get(Submission, a), db.get(Submission, b)
    if not one or not two or one.task_id != t.id or two.task_id != t.id:
        raise HTTPException(404, "Both versions must belong to this task")
    return W.compare(one, two)


# ---- attachments ------------------------------------------------------------------------
def _attachment_root() -> Path:
    return Path(settings.STORAGE_DIR).resolve() / "attachments"


def safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ ()\-]", "_", Path(name or "file").name).strip(" .") or "file"
    return name[:150]


@router.post("/{task_id}/attachments", status_code=201)
async def upload_attachment(task_id: int, file: UploadFile = File(...), actor: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """The assigner / admin uploads reference files; the assignee uploads deliverables while the task is editable."""
    t = get_task(db, actor, task_id)
    if can_manage_task(actor, t) and t.assigned_to != actor.id:
        kind = "reference"
        if t.status in W.CLOSED:
            raise HTTPException(409, f"A {t.status} task cannot get new files")
    elif t.assigned_to == actor.id:
        kind = "deliverable"
        if t.status not in EDITABLE:
            raise HTTPException(409, f"The task is '{t.status}'. Deliverables can be added only while you work on it.")
    else:
        raise HTTPException(403, "You cannot add files to this task")
    name = safe_name(file.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(422, f".{ext} files are not allowed")
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "File is larger than the 10 MB limit")
    if not data:
        raise HTTPException(422, "The file is empty")
    a = TaskAttachment(task_id=t.id, kind=kind, filename=name, content_type=(file.content_type or "")[:100],
                       size_bytes=len(data), storage_path="database", data=data, uploaded_by=actor.id)
    db.add(a)
    db.flush()
    W.record(db, t, actor, f"{kind}_uploaded", t.status, t.status, name)
    commit(db)
    return attachment_dict(a, {actor.id: actor.full_name})


def _attachment(db: Session, t: Task, attachment_id: int) -> TaskAttachment:
    a = db.get(TaskAttachment, attachment_id)
    if not a or a.task_id != t.id or a.deleted_at is not None:
        raise HTTPException(404, "File not found")
    return a


@router.get("/{task_id}/attachments/{attachment_id}")
def download_attachment(task_id: int, attachment_id: int, actor: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    a = _attachment(db, t, attachment_id)
    if a.data is not None:                              # stored in the database (build 20 and later)
        name = a.filename.replace('"', "")
        return Response(a.data, media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Content-Disposition": f"attachment; filename=\"{name}\""})
    path = Path(a.storage_path).resolve()               # older upload, still a file on disk
    if _attachment_root() not in path.parents or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=a.filename, media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff"})


# ---- open a reference file inside the coding workspace ------------------------------------------
# What the editor can show. Everything else (docx, xlsx, zip) keeps Download only.
def attachment_bytes(a: TaskAttachment) -> bytes | None:
    """The bytes of an attachment: the database column, or an older upload still on disk."""
    if a.data is not None:
        return a.data
    path = Path(a.storage_path or "").resolve()
    if _attachment_root() in path.parents and path.is_file():
        return path.read_bytes()
    return None


@router.post("/{task_id}/attachments/{attachment_id}/open")
def open_attachment(task_id: int, attachment_id: int, request: Request,
                    actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Open a reference file where the work happens.

    A text or code file is copied into the assignee's workspace as a normal file, so it can be edited, saved
    (with version history) and submitted. The attachment itself never changes: the assigner keeps the
    original. A PDF or an image opens in the browser. Everything else keeps Download only.
    """
    from app.api.workspaces import _put, check_quota, clean_path
    from app.database.models import Workspace, WorkspaceFile

    t = get_task(db, actor, task_id)
    a = _attachment(db, t, attachment_id)
    mode = open_mode(a.filename)
    if mode == "download":
        ext = a.filename.rsplit(".", 1)[-1] if "." in a.filename else "this file"
        return {"mode": "download", "filename": a.filename, "task_id": t.id, "attachment_id": a.id,
                "detail": f".{ext} cannot be edited in the browser. Use Download."}

    if mode == "preview":
        return {"mode": "preview", "filename": a.filename, "task_id": t.id, "attachment_id": a.id,
                "content_type": a.content_type, "url": f"/api/tasks/{t.id}/attachments/{a.id}"}

    data = attachment_bytes(a)
    if data is None:
        raise HTTPException(404, "The file is listed but its content cannot be found.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "This file is not plain text, so it cannot be opened in the editor. "
                                 "Use Download instead.")

    # Only the assignee may edit; everyone else who can see the task gets the text as it is.
    if t.assigned_to != actor.id:
        return {"mode": "read_only", "filename": a.filename, "task_id": t.id, "attachment_id": a.id,
                "content": text, "detail": "Only the person the task is assigned to can edit this file."}
    if t.status not in EDITABLE:
        raise HTTPException(409, f"The task is '{t.status}'. Files can be changed only while you work on it.")

    ws = db.query(Workspace).filter_by(task_id=t.id, user_id=actor.id).first()
    if not ws:
        ws = Workspace(task_id=t.id, user_id=actor.id, project_id=t.project_id)
        db.add(ws)
        db.flush()

    wanted = clean_path(safe_name(a.filename))
    taken = {f.path for f in db.query(WorkspaceFile).filter_by(workspace_id=ws.id, deleted_at=None)}
    path, n = wanted, 1
    while path in taken:                        # never overwrite work already in the workspace
        stem, dot, ext = wanted.rpartition(".")
        path = f"ref-{n}-{stem}.{ext}" if dot else f"ref-{n}-{wanted}"
        n += 1
    check_quota(db, ws.id, add_files=1, add_bytes=len(text.encode()))
    f = _put(db, ws, actor.id, path, text, "manual")
    begin_work(db, t, actor)
    audit(db, actor, "attachment.open", "task_attachments", a.id, new={"path": path}, ip=client_ip(request))
    commit(db)
    return {"mode": "editor", "filename": a.filename, "task_id": t.id, "attachment_id": a.id,
            "path": path, "file_id": f.id, "url": f"/workspace/{t.id}?file={path}"}


@router.delete("/{task_id}/attachments/{attachment_id}")
def delete_attachment(task_id: int, attachment_id: int, actor: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    t = get_task(db, actor, task_id)
    a = _attachment(db, t, attachment_id)
    if a.submission_id is not None:
        raise HTTPException(409, "This file is part of a submitted version and cannot be removed")
    if a.uploaded_by != actor.id and actor.role != P.ADMIN:
        raise HTTPException(403, "Only the uploader or an admin can remove this file")
    a.deleted_at = utcnow()
    W.record(db, t, actor, f"{a.kind}_removed", t.status, t.status, a.filename)
    commit(db)
    return {"ok": True}

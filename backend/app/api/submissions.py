import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.languages import for_path
from app.database.connection import get_db
from app.database.models import (FileVersion, Review, ReviewComment, Submission, Task, TaskAttachment, User, Workspace,
                                 WorkspaceFile, utcnow)
from app.dependencies.auth import client_ip, get_current_user
from app.schemas import CommentIn, ReviewIn
from app.services import runner
from app.services import workflow as W
from app.services.common import activity, audit, commit, notify

router = APIRouter(prefix="/api/submissions", tags=["submissions & reviews"])


class SnapshotRun(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    stdin: str = Field(default="", max_length=20000)


def can_see_submission(db: Session, actor: User, s: Submission) -> bool:
    if actor.role == P.ADMIN or s.submitted_by == actor.id:
        return True
    if actor.role in P.LEADS:
        task = db.get(Task, s.task_id)
        if task.reviewer_id == actor.id or P.can_review(db, actor, s, task):
            return True
        if s.submitted_by in P.team_member_ids(db, actor.id):
            return True
        return db.query(Review.id).filter_by(submission_id=s.id, reviewer_id=actor.id).first() is not None
    return False


def sub_dict(db: Session, s: Submission, full: bool = False, actor: User | None = None) -> dict:
    task = db.get(Task, s.task_id)
    submitter = db.get(User, s.submitted_by)
    d = {"id": s.id, "task_id": s.task_id, "task_code": task.code, "task_title": task.title,
         "submitted_by": s.submitted_by, "submitted_by_name": submitter.full_name,
         "submitter_role": s.submitter_role, "version_no": s.version_no, "version": s.version_label,
         "stage": s.stage, "status": s.status, "submitted_at": s.submitted_at, "decided_at": s.decided_at,
         "note": s.note, "file_count": len(s.snapshot or []),
         "changes": s.changes or {"added": [], "modified": [], "deleted": []}}
    if full:
        reviews = (db.query(Review, User.full_name).join(User, User.id == Review.reviewer_id)
                   .filter(Review.submission_id == s.id).order_by(Review.id).all())
        comments = (db.query(ReviewComment, User.full_name).join(User, User.id == ReviewComment.author_id)
                    .filter(ReviewComment.submission_id == s.id).order_by(ReviewComment.id).all())
        others = db.query(Submission).filter_by(task_id=s.task_id).order_by(Submission.version_no).all()
        files = db.query(TaskAttachment).filter_by(task_id=s.task_id, deleted_at=None).order_by(TaskAttachment.id).all()
        d.update({"files": s.snapshot, "authors": s.authors or {}, "task_requirements": task.requirements,
                  "task_deliverables": task.deliverables, "task_status": task.status,
                  "can_review": bool(actor and s.stage != "closed" and P.can_review(db, actor, s, task)),
                  "can_restore": bool(actor and actor.id == s.submitted_by and task.assigned_to == actor.id
                                      and task.status in W.EDITABLE),
                  "versions": [{"id": o.id, "version": o.version_label, "status": o.status,
                                "submitted_at": o.submitted_at} for o in others],
                  "attachments": [{"id": a.id, "kind": a.kind, "filename": a.filename, "size_bytes": a.size_bytes,
                                   "submission_id": a.submission_id} for a in files
                                  if a.kind == "reference" or a.submission_id is None or a.submission_id <= s.id],
                  "reviews": [{"id": r.id, "reviewer_id": r.reviewer_id, "reviewer": n, "stage": r.stage,
                               "decision": r.decision, "comment": r.comment, "created_at": r.created_at}
                              for r, n in reviews],
                  "comments": [{"id": c.id, "author": n, "author_id": c.author_id, "file_path": c.file_path,
                                "line_no": c.line_no, "body": c.body, "created_at": c.created_at}
                               for c, n in comments]})
    return d


def _get(db: Session, actor: User, sub_id: int) -> Submission:
    s = db.get(Submission, sub_id)
    if not s:
        raise HTTPException(404, "Submission not found")
    if not can_see_submission(db, actor, s):
        raise HTTPException(403, "You cannot access this submission")
    return s


@router.get("")
def list_submissions(view: str = Query("queue", pattern="^(queue|mine|all|reviewed)$"),
                     actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """queue = waiting for *my* review; mine = what I submitted; reviewed = what I decided;
    all = everything I may see."""
    q = db.query(Submission).order_by(Submission.id.desc())
    if view == "mine":
        return [sub_dict(db, s) for s in q.filter(Submission.submitted_by == actor.id)]
    if view == "reviewed":
        ids = {r[0] for r in db.query(Review.submission_id).filter_by(reviewer_id=actor.id)}
        rows = q.filter(Submission.id.in_(ids or {-1})).all()
        out = []
        for s in rows:
            mine = db.query(Review).filter_by(submission_id=s.id, reviewer_id=actor.id).order_by(Review.id.desc()).first()
            out.append({**sub_dict(db, s), "my_decision": mine.decision, "my_decision_at": mine.created_at})
        return out
    if view == "queue":
        if actor.role == P.ADMIN:
            rows = q.filter(Submission.stage == "admin_review").all()
        elif actor.role == P.ONROLL:
            rows = [s for s in q.filter(Submission.stage == "onroll_review") if P.can_review(db, actor, s)]
        else:
            rows = []
        return [sub_dict(db, s) for s in rows]
    return [sub_dict(db, s) for s in q.limit(500) if can_see_submission(db, actor, s)]


@router.get("/{sub_id}")
def read_submission(sub_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sub_dict(db, _get(db, actor, sub_id), full=True, actor=actor)


@router.get("/{sub_id}/download")
def download_version(sub_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Exactly the files of this submitted version, as a zip."""
    s = _get(db, actor, sub_id)
    task = db.get(Task, s.task_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in s.snapshot or []:
            z.writestr(f["path"], f.get("content") or "")
    if actor.id != s.submitted_by:
        audit(db, actor, "submission.download", "submissions", s.id, ip=client_ip(request))
        commit(db)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{task.code}-v{s.version_label}.zip"'})


@router.post("/{sub_id}/run")
def run_version(sub_id: int, body: SnapshotRun, request: Request, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Run one file of the submitted version in an isolated container (reviewers test what was submitted,
    not the employee's later edits)."""
    from app.api.execution import run_limiter
    s = _get(db, actor, sub_id)
    files = [(f["path"], f.get("content") or "") for f in s.snapshot or []]
    if body.path not in {p for p, _ in files}:
        raise HTTPException(404, "That file is not part of this version")
    lang = for_path(body.path)
    if not lang:
        raise HTTPException(422, "Unknown file type.")
    if lang["kind"] != "run":
        raise HTTPException(422, lang["note"] or f"{lang['name']} files cannot be run.")
    if not run_limiter.allow(str(actor.id)):
        raise HTTPException(429, "Too many runs. Wait a minute.")
    db.commit()
    try:
        result = runner.run(actor.id, lang, files, body.path, body.stdin)
    except runner.RunnerUnavailable as e:
        raise HTTPException(503, str(e))
    activity(db, actor.id, "code.run", {"submission_id": s.id, "file": body.path, "language": lang["id"],
                                        "status": result["status"]}, ip=client_ip(request))
    commit(db)
    return result


@router.post("/{sub_id}/restore")
def restore_version(sub_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Bring the files of an earlier version back into the workspace. Only the assignee, and only while the task is
    editable. The version itself is not touched; the current files are kept in each file's history."""
    s = _get(db, actor, sub_id)
    task = db.get(Task, s.task_id)
    if task.assigned_to != actor.id or s.submitted_by != actor.id:
        raise HTTPException(403, "Only the person doing the task can restore a version into the workspace")
    if task.status not in W.EDITABLE:
        raise HTTPException(409, f"The task is '{task.status}'. Files are locked.")
    from app.api.workspaces import _add_version, log_event
    ws = db.get(Workspace, s.workspace_id)
    wanted = W.as_map(s.snapshot)
    now = utcnow()
    for f in db.query(WorkspaceFile).filter_by(workspace_id=ws.id).all():
        if f.deleted_at is None and f.path not in wanted:
            f.deleted_at = now
            log_event(db, f, actor.id, "deleted", summary=f"not part of version {s.version_label}")
    for path, content in wanted.items():
        f = db.query(WorkspaceFile).filter_by(workspace_id=ws.id, path=path).first()
        if f is None:
            f = WorkspaceFile(workspace_id=ws.id, path=path, content=content)
            db.add(f)
            db.flush()
            _add_version(db, f, actor.id, "restore")
        elif f.deleted_at is not None or f.content != content:
            f.content, f.deleted_at = content, None
            db.flush()
            last = db.query(FileVersion).filter_by(file_id=f.id).count()
            _add_version(db, f, actor.id, "restore" if last else "manual")
    ws.last_saved_at = now
    W.record(db, task, actor, "version_restored", task.status, task.status, f"Workspace reset to version {s.version_label}", s.id)
    audit(db, actor, "submission.restore", "submissions", s.id, ip=client_ip(request))
    commit(db)
    return {"ok": True, "version": s.version_label, "files": len(wanted)}


@router.post("/{sub_id}/comments", status_code=201)
def add_comment(sub_id: int, body: CommentIn, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    s = _get(db, actor, sub_id)
    c = ReviewComment(submission_id=s.id, author_id=actor.id, file_path=body.file_path, line_no=body.line_no,
                      body=body.body)
    db.add(c)
    if actor.id != s.submitted_by:
        notify(db, [s.submitted_by], "review_comment", f"{actor.full_name} commented on your submission",
               body.body[:140], f"/reviews/{s.id}")
    commit(db)
    return {"id": c.id}


@router.post("/{sub_id}/review")
def review(sub_id: int, body: ReviewIn, request: Request, actor: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """approved | changes_requested (rework) | rejected. One transaction: review row, submission state, task status,
    history, audit and notifications are saved together or not at all."""
    s = db.query(Submission).filter_by(id=sub_id).with_for_update().first()
    if not s:
        raise HTTPException(404, "Submission not found")
    if not can_see_submission(db, actor, s):
        raise HTTPException(403, "You cannot access this submission")
    if s.stage == "closed":
        raise HTTPException(409, "This submission has already been decided")
    task = db.get(Task, s.task_id)
    if not P.can_review(db, actor, s, task):
        raise HTTPException(403, "You are not an authorised reviewer for this submission at this stage")
    comment = (body.comment or "").strip()
    if body.decision != "approved" and not comment:
        raise HTTPException(422, "A comment is required when requesting rework or rejecting")
    stage = s.stage
    who = "On-Roll" if stage == "onroll_review" else "Admin"
    prefix = "onroll" if stage == "onroll_review" else "admin"
    db.add(Review(submission_id=s.id, reviewer_id=actor.id, stage=stage, decision=body.decision,
                  comment=comment or None))
    link = f"/reviews/{s.id}"
    now = utcnow()
    if body.decision == "approved" and stage == "onroll_review":
        # On-Roll approval is never final: it forwards the same version to Admin.
        s.stage, s.status = "admin_review", "pending_admin_review"
        task.review_status = s.status
        W.move(db, task, actor, "onroll_approved", "onroll_approved", comment or None, s.id)
        W.move(db, task, None, "sent_to_admin_review", "under_admin_review", None, s.id)
        notify(db, P.reviewers_for(db, s, task), "admin_pending", f"{task.code} approved by On-Roll review",
               f"{task.title} (v{s.version_label}) needs final Admin approval", link)
        notify(db, [s.submitted_by], "review_approved", f"{task.code} passed On-Roll review",
               "Now waiting for final Admin approval", link)
    elif body.decision == "approved":
        s.stage, s.status, s.decided_at = "closed", "approved", now
        task.review_status, task.completed_at = "approved", now
        W.move(db, task, actor, "admin_approved", "admin_approved", comment or None, s.id)
        W.move(db, task, None, "completed", "completed", None, s.id)
        notify(db, [s.submitted_by], "admin_approved", f"{task.code} approved and completed", comment or None, link)
    else:
        s.stage, s.status, s.decided_at = "closed", body.decision, now
        task.review_status = body.decision
        if body.decision == "rejected":
            W.move(db, task, actor, f"{prefix}_rejected", f"{prefix}_rejected", comment, s.id)
            title = f"Rejected by {who}"
        else:
            W.move(db, task, actor, f"{prefix}_rework_requested", "rework_required", comment, s.id)
            title = f"Rework requested by {who}"
        notify(db, [s.submitted_by], body.decision, f"{title}: {task.code}", comment, link)
    audit(db, actor, f"review.{body.decision}", "submissions", s.id, previous={"stage": stage},
          new={"stage": s.stage, "status": s.status, "task_status": task.status}, ip=client_ip(request))
    commit(db)
    return sub_dict(db, s, full=True, actor=actor)

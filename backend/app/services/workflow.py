"""Task life-cycle: the status list, the append-only task history, and version comparison.

Every status change goes through `move()`, so each one is recorded with who, when, from, to and why.
"""
import difflib
from datetime import timedelta

from sqlalchemy.orm import Session

from app.database.models import Submission, Task, TaskHistory, User, utcnow
from app.services.common import local_day, notify

STATUSES = ["created", "assigned", "accepted", "in_progress", "submitted", "under_onroll_review", "onroll_approved",
            "onroll_rejected", "under_admin_review", "admin_approved", "admin_rejected", "rework_required",
            "resubmitted", "completed", "cancelled", "archived"]
# the assignee may change files only in these
EDITABLE = {"accepted", "in_progress", "rework_required", "onroll_rejected", "admin_rejected"}
OPEN = ("assigned", "accepted", "in_progress", "rework_required", "onroll_rejected", "admin_rejected")
IN_REVIEW = ("submitted", "resubmitted", "under_onroll_review", "onroll_approved", "under_admin_review", "admin_approved")
REASSIGNABLE = {"assigned", "accepted", "in_progress"}
CLOSED = {"completed", "cancelled", "archived"}


def record(db: Session, task: Task, actor: User | None, action: str, from_status: str | None = None,
           to_status: str | None = None, comment: str | None = None, submission_id: int | None = None):
    db.add(TaskHistory(task_id=task.id, user_id=actor.id if actor else None, user_role=actor.role if actor else None,
                       action=action, from_status=from_status, to_status=to_status, comment=comment,
                       submission_id=submission_id))


def move(db: Session, task: Task, actor: User | None, action: str, to_status: str, comment: str | None = None,
         submission_id: int | None = None):
    """Change the status and write the history row in the same transaction."""
    assert to_status in STATUSES, to_status
    record(db, task, actor, action, task.status, to_status, comment, submission_id)
    task.status = to_status


def history(db: Session, task_id: int) -> list[dict]:
    rows = (db.query(TaskHistory, User.full_name).outerjoin(User, User.id == TaskHistory.user_id)
            .filter(TaskHistory.task_id == task_id).order_by(TaskHistory.id).all())
    labels = dict(db.query(Submission.id, Submission.version_label).filter(Submission.task_id == task_id).all())
    return [{"id": h.id, "task_id": h.task_id, "user_id": h.user_id, "user": name, "user_role": h.user_role,
             "action": h.action, "from_status": h.from_status, "to_status": h.to_status, "comment": h.comment,
             "submission_id": h.submission_id, "version": labels.get(h.submission_id), "at": h.created_at}
            for h, name in rows]


# ---- versions ---------------------------------------------------------------------------
def next_label(db: Session, task: Task) -> str:
    """1.0 first; 1.1, 1.2 for corrections; after a version was finally approved the next one starts 2.0."""
    subs = db.query(Submission).filter_by(task_id=task.id).order_by(Submission.version_no).all()
    if not subs:
        return "1.0"
    major, minor = (int(x) for x in (subs[-1].version_label or f"1.{subs[-1].version_no - 1}").split("."))
    return f"{major + 1}.0" if subs[-1].status == "approved" else f"{major}.{minor + 1}"


def as_map(snapshot) -> dict:
    return {f["path"]: f.get("content") or "" for f in (snapshot or [])}


def changes_between(old_snapshot, new_snapshot) -> dict:
    old, new = as_map(old_snapshot), as_map(new_snapshot)
    return {"added": sorted(p for p in new if p not in old),
            "deleted": sorted(p for p in old if p not in new),
            "modified": sorted(p for p in new if p in old and old[p] != new[p])}


def line_stat(old: str, new: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def compare(a: Submission, b: Submission) -> dict:
    """Real file differences between two submitted versions (a = older side, b = newer side)."""
    old, new = as_map(a.snapshot), as_map(b.snapshot)
    files = []
    for path in sorted(set(old) | set(new)):
        before, after = old.get(path), new.get(path)
        if before == after:
            continue
        status = "added" if before is None else "deleted" if after is None else "modified"
        plus, minus = line_stat(before or "", after or "")
        diff = "\n".join(difflib.unified_diff((before or "").splitlines(), (after or "").splitlines(),
                                              f"v{a.version_label}/{path}", f"v{b.version_label}/{path}", lineterm="", n=3))
        files.append({"path": path, "status": status, "lines_added": plus, "lines_removed": minus, "diff": diff})
    return {"from": {"id": a.id, "version": a.version_label, "submitted_at": a.submitted_at},
            "to": {"id": b.id, "version": b.version_label, "submitted_at": b.submitted_at},
            "unchanged": sum(1 for p in new if old.get(p) == new[p]),
            "summary": {k: sum(1 for f in files if f["status"] == k) for k in ("added", "modified", "deleted")},
            "files": files}


# ---- deadline reminders -----------------------------------------------------------------
_last_run = {"at": None}


def send_deadline_reminders(db: Session, force: bool = False) -> int:
    """One reminder per task per day for open tasks that are due tomorrow, today, or overdue.
    Called when people use the app (at most every 10 minutes), so no separate worker is needed."""
    now = utcnow()
    if not force and _last_run["at"] and (now - _last_run["at"]) < timedelta(minutes=10):
        return 0
    _last_run["at"] = now
    today = local_day(now)
    rows = (db.query(Task).filter(Task.deleted_at.is_(None), Task.status.in_(OPEN), Task.deadline.isnot(None),
                                  Task.deadline <= today + timedelta(days=1)).all())
    n = 0
    for t in rows:
        if t.reminded_on == today:
            continue
        days = (t.deadline - today).days
        when = "is due tomorrow" if days == 1 else "is due today" if days == 0 else f"is overdue by {-days} day(s)"
        notify(db, [t.assigned_to], "task_deadline", f"{t.code} {when}", t.title, f"/tasks/{t.id}")
        t.reminded_on = today
        n += 1
    return n

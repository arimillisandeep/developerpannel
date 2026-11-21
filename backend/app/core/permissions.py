"""Single source of truth for role rules. Every API calls into this module."""
from sqlalchemy.orm import Session

from app.database.models import Submission, Team, TeamMember, User

ADMIN, DEVELOPER, ONROLL, OFFROLL, INTERN = "admin", "developer", "onroll", "offroll", "intern"
ROLES = [ADMIN, DEVELOPER, ONROLL, OFFROLL, INTERN]
EMPLOYEE_ROLES = [ONROLL, OFFROLL, INTERN]

# The separate Developer role was retired in build 16: the panels are Admin, On-Roll, Off-Roll, Intern.
# On-Roll employees lead teams and do the first review. "developer" stays readable for old rows only.
ACTIVE_ROLES = [ADMIN, ONROLL, OFFROLL, INTERN]
LEADS = {ONROLL, DEVELOPER}

# who -> which roles they may assign tasks to
ASSIGN_MATRIX = {
    ADMIN: {ONROLL, OFFROLL, INTERN},
    DEVELOPER: {ONROLL, OFFROLL, INTERN},
    ONROLL: {ONROLL, OFFROLL, INTERN},
    OFFROLL: set(),
    INTERN: set(),
}
# roles whose submissions need an On-Roll review before Admin
ONROLL_REVIEW_FIRST = {OFFROLL, INTERN}


def team_member_ids(db: Session, developer_id: int) -> set[int]:
    """Users in any team led by this developer."""
    rows = (db.query(TeamMember.user_id).join(Team, Team.id == TeamMember.team_id)
            .filter(Team.lead_developer_id == developer_id).all())
    return {r[0] for r in rows}


def has_team(db: Session, user_id: int) -> bool:
    return (db.query(TeamMember.id).join(Team, Team.id == TeamMember.team_id)
            .filter(TeamMember.user_id == user_id, Team.lead_developer_id.isnot(None)).first()) is not None


def can_assign(db: Session, actor: User, target: User) -> bool:
    if not target.is_active or target.deleted_at is not None:
        return False
    return target.role in ASSIGN_MATRIX.get(actor.role, set())


def can_view_user(db: Session, actor: User, target_id: int) -> bool:
    if actor.role == ADMIN or actor.id == target_id:
        return True
    if actor.role in LEADS:
        return target_id in team_member_ids(db, actor.id)
    return False


def can_be_reviewer(user: User | None) -> bool:
    return bool(user and user.role == ONROLL and user.is_active and user.deleted_at is None)


def can_review(db: Session, actor: User, submission, task=None) -> bool:
    """On-Roll stage: the On-Roll reviewer named on the task; if none is named, the On-Roll lead of the
    submitter's team; if there is no team either, any On-Roll employee.
    Admin stage: Admin only. Nobody reviews their own work."""
    if submission.submitted_by == actor.id:
        return False
    if submission.stage == "admin_review":
        return actor.role == ADMIN
    if submission.stage == "onroll_review":
        if actor.role != ONROLL:
            return False
        if task is None:
            from app.database.models import Task
            task = db.get(Task, submission.task_id)
        if task is not None and task.reviewer_id:
            return task.reviewer_id == actor.id
        if submission.submitted_by in team_member_ids(db, actor.id):
            return True
        return not has_team(db, submission.submitted_by)
    return False


def can_read_workspace(db: Session, actor: User, owner_id: int, task) -> bool:
    """Who may look at the files of somebody else's task (read-only).

    The owner always can (that is checked by the caller), and so can an Admin, the On-Roll lead of the owner's
    team, and anybody who may review a submission of that task. The last part matters: a task can name its own
    On-Roll reviewer (task.reviewer_id), and a submitter without a team may be reviewed by any On-Roll employee -
    in both cases the reviewer must be able to open the workspace he is reviewing, even when he does not lead
    the owner's team.
    """
    if actor.id == owner_id or actor.role == ADMIN:
        return True
    if actor.role in LEADS and owner_id in team_member_ids(db, actor.id):
        return True
    if task is None:
        return False
    if task.reviewer_id and task.reviewer_id == actor.id:
        return True
    latest = (db.query(Submission).filter(Submission.task_id == task.id)
              .order_by(Submission.id.desc()).first())
    return bool(latest and can_review(db, actor, latest, task))


def reviewers_for(db: Session, submission, task) -> list[int]:
    """User ids to notify about a submission waiting at its current stage."""
    if submission.stage == "admin_review":
        return [r[0] for r in db.query(User.id).filter(User.role == ADMIN, User.is_active.is_(True))]
    people = db.query(User).filter(User.role == ONROLL, User.is_active.is_(True), User.deleted_at.is_(None))
    return [u.id for u in people if can_review(db, u, submission, task)]

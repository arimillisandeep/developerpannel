from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.database.connection import get_db
from app.database.models import AuditLog, Department, InternVacancy, Project, Team, TeamMember, User
from app.dependencies.auth import admin_only, client_ip, get_current_user, require_roles
from app.schemas import MemberIn, NameIn, TeamIn, TeamUpdate, VacancyIn
from app.services.common import audit, commit
from app.api.users import intern_headcount

router = APIRouter(prefix="/api", tags=["organisation"])


# ----- departments -----
@router.get("/departments")
def departments(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name} for d in db.query(Department).order_by(Department.name)]


@router.post("/departments", status_code=201)
def create_department(body: NameIn, request: Request, actor: User = Depends(admin_only),
                      db: Session = Depends(get_db)):
    if db.query(Department.id).filter(Department.name == body.name.strip()).first():
        raise HTTPException(409, "Department already exists")
    d = Department(name=body.name.strip())
    db.add(d)
    db.flush()
    audit(db, actor, "department.create", "departments", d.id, new={"name": d.name}, ip=client_ip(request))
    commit(db)
    return {"id": d.id, "name": d.name}


# ----- projects -----
@router.get("/projects")
def projects(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "description": p.description, "status": p.status}
            for p in db.query(Project).order_by(Project.name)]


@router.post("/projects", status_code=201)
def create_project(body: NameIn, request: Request, actor: User = Depends(require_roles(P.ADMIN, P.DEVELOPER, P.ONROLL)),
                   db: Session = Depends(get_db)):
    if db.query(Project.id).filter(Project.name == body.name.strip()).first():
        raise HTTPException(409, "Project already exists")
    p = Project(name=body.name.strip(), description=body.description, created_by=actor.id)
    db.add(p)
    db.flush()
    audit(db, actor, "project.create", "projects", p.id, new={"name": p.name}, ip=client_ip(request))
    commit(db)
    return {"id": p.id, "name": p.name, "description": p.description, "status": p.status}


# ----- teams -----
def team_dict(db: Session, t: Team) -> dict:
    lead = db.get(User, t.lead_developer_id) if t.lead_developer_id else None
    members = (db.query(User).join(TeamMember, TeamMember.user_id == User.id)
               .filter(TeamMember.team_id == t.id).order_by(User.full_name).all())
    return {"id": t.id, "name": t.name, "lead_developer_id": t.lead_developer_id,
            "lead_developer": lead.full_name if lead else None,
            "members": [{"id": m.id, "full_name": m.full_name, "role": m.role, "is_active": m.is_active}
                        for m in members]}


def _lead(db: Session, lead_id):
    if lead_id is None:
        return
    u = db.get(User, lead_id)
    if not u or u.role != P.ONROLL or not u.is_active:
        raise HTTPException(422, "Team lead must be an active On-Roll employee")


@router.get("/teams")
def teams(actor: User = Depends(require_roles(P.ADMIN, P.DEVELOPER, P.ONROLL)), db: Session = Depends(get_db)):
    q = db.query(Team)
    if actor.role in P.LEADS:
        q = q.filter(Team.lead_developer_id == actor.id)
    return [team_dict(db, t) for t in q.order_by(Team.name)]


@router.post("/teams", status_code=201)
def create_team(body: TeamIn, request: Request, actor: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.query(Team.id).filter(Team.name == body.name.strip()).first():
        raise HTTPException(409, "Team already exists")
    _lead(db, body.lead_developer_id)
    t = Team(name=body.name.strip(), lead_developer_id=body.lead_developer_id)
    db.add(t)
    db.flush()
    audit(db, actor, "team.create", "teams", t.id, new=body.model_dump(), ip=client_ip(request))
    commit(db)
    return team_dict(db, t)


@router.patch("/teams/{team_id}")
def update_team(team_id: int, body: TeamUpdate, request: Request, actor: User = Depends(admin_only),
                db: Session = Depends(get_db)):
    t = db.get(Team, team_id)
    if not t:
        raise HTTPException(404, "Team not found")
    data = body.model_dump(exclude_unset=True)
    prev = {"name": t.name, "lead_developer_id": t.lead_developer_id}
    if "lead_developer_id" in data:
        _lead(db, data["lead_developer_id"])
        t.lead_developer_id = data["lead_developer_id"]
    if data.get("name"):
        t.name = data["name"].strip()
    audit(db, actor, "team.update", "teams", t.id, previous=prev, new=data, ip=client_ip(request))
    try:
        commit(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Team name already exists")
    return team_dict(db, t)


@router.post("/teams/{team_id}/members", status_code=201)
def add_member(team_id: int, body: MemberIn, request: Request, actor: User = Depends(admin_only),
               db: Session = Depends(get_db)):
    t = db.get(Team, team_id)
    u = db.get(User, body.user_id)
    if not t or not u:
        raise HTTPException(404, "Team or user not found")
    if u.role not in P.EMPLOYEE_ROLES:
        raise HTTPException(422, "Only On-Roll, Off-Roll and Intern employees can be team members")
    if not db.query(TeamMember.id).filter_by(team_id=team_id, user_id=u.id).first():
        db.add(TeamMember(team_id=team_id, user_id=u.id))
        audit(db, actor, "team.member_add", "teams", team_id, new={"user_id": u.id}, ip=client_ip(request))
        commit(db)
    return team_dict(db, t)


@router.delete("/teams/{team_id}/members/{user_id}")
def remove_member(team_id: int, user_id: int, request: Request, actor: User = Depends(admin_only),
                  db: Session = Depends(get_db)):
    t = db.get(Team, team_id)
    if not t:
        raise HTTPException(404, "Team not found")
    m = db.query(TeamMember).filter_by(team_id=team_id, user_id=user_id).first()
    if m:
        db.delete(m)
        audit(db, actor, "team.member_remove", "teams", team_id, previous={"user_id": user_id},
              ip=client_ip(request))
        commit(db)
    return team_dict(db, t)


# ----- intern vacancy -----
@router.put("/intern-vacancy")
def set_vacancy(body: VacancyIn, request: Request, actor: User = Depends(admin_only),
                db: Session = Depends(get_db)):
    row = db.query(InternVacancy).first()
    prev = row.target_headcount if row else None
    if not row:
        row = InternVacancy(target_headcount=body.target_headcount)
        db.add(row)
    row.target_headcount, row.updated_by = body.target_headcount, actor.id
    audit(db, actor, "intern_vacancy.update", "intern_vacancies", 1, previous={"target": prev},
          new={"target": body.target_headcount}, ip=client_ip(request))
    commit(db)
    return intern_headcount(db)


# ----- audit log -----
@router.get("/audit-logs")
def audit_logs(action: str | None = None, actor_id: int | None = None, limit: int = Query(200, le=1000),
               actor: User = Depends(admin_only), db: Session = Depends(get_db)):
    q = db.query(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.actor_id)
    if action:
        q = q.filter(AuditLog.action.like(f"{action}%"))
    if actor_id:
        q = q.filter(AuditLog.actor_id == actor_id)
    return [{"id": a.id, "actor_id": a.actor_id, "actor": name, "action": a.action, "entity": a.entity,
             "record_id": a.record_id, "previous_value": a.previous_value, "new_value": a.new_value,
             "ip_address": a.ip_address, "created_at": a.created_at}
            for a, name in q.order_by(AuditLog.id.desc()).limit(limit)]

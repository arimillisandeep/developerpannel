import calendar
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.config import settings
from app.core.security import hash_password
from app.database.connection import get_db
from app.database.models import (ActivityLog, AdminProfile, Department, DeveloperProfile, EmployeeProfile,
                                 EmploymentHistory, InternVacancy, Team, TeamMember, User, utcnow)
from app.dependencies.auth import admin_only, client_ip, get_current_user, require_roles
from app.schemas import ConvertIn, DeactivateIn, UserCreate, UserUpdate
from app.services import timer
from app.services.common import audit, commit, local_day, notify

router = APIRouter(prefix="/api/users", tags=["users"])

PROFILE_FIELDS = ["phone", "department_id", "reporting_manager_id", "joining_date", "contract_start",
                  "contract_end", "compensation", "performance_note"]


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def employee_code(user_id: int) -> str:
    return f"WC-E{user_id:04d}"


def get_profile(db: Session, user: User):
    if user.role == P.ADMIN:
        return db.query(AdminProfile).filter_by(user_id=user.id).first()
    if user.role == P.DEVELOPER:
        return db.query(DeveloperProfile).filter_by(user_id=user.id).first()
    return db.query(EmployeeProfile).filter_by(user_id=user.id).first()


def user_dict(db: Session, u: User, private: bool = False) -> dict:
    """private=True adds contact, contract and compensation data (admin or the owner only)."""
    p = get_profile(db, u)
    d = {"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role, "is_active": u.is_active,
         "employee_code": getattr(p, "employee_code", None),
         "joining_date": getattr(p, "joining_date", None),
         "employment_status": getattr(p, "employment_status", "active" if u.is_active else "inactive"),
         "department_id": getattr(p, "department_id", None),
         "contract_end": getattr(p, "contract_end", None)}
    if d["department_id"]:
        dep = db.get(Department, d["department_id"])
        d["department"] = dep.name if dep else None
    teams = (db.query(Team.id, Team.name).join(TeamMember, TeamMember.team_id == Team.id)
             .filter(TeamMember.user_id == u.id).all())
    d["teams"] = [{"id": t.id, "name": t.name} for t in teams]
    if private:
        comp = getattr(p, "compensation", None)
        d.update({"phone": getattr(p, "phone", None),
                  "reporting_manager_id": getattr(p, "reporting_manager_id", None),
                  "contract_start": getattr(p, "contract_start", None),
                  "conversion_status": getattr(p, "conversion_status", None),
                  "performance_note": getattr(p, "performance_note", None),
                  "responsibilities": getattr(p, "responsibilities", None),
                  "compensation": float(comp) if comp is not None else None,
                  "last_login_at": u.last_login_at, "created_at": u.created_at})
    return d


def intern_headcount(db: Session) -> dict:
    row = db.query(InternVacancy).first()
    target = row.target_headcount if row else settings.INTERN_TARGET_HEADCOUNT
    filled = db.query(func.count(User.id)).filter(User.role == P.INTERN, User.is_active.is_(True),
                                                  User.deleted_at.is_(None)).scalar()
    return {"target": target, "filled": filled, "vacant": max(0, target - filled)}


def _target(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if not u or u.deleted_at is not None:
        raise HTTPException(404, "User not found")
    return u


def _active_admins(db: Session) -> int:
    return db.query(func.count(User.id)).filter(User.role == P.ADMIN, User.is_active.is_(True),
                                                User.deleted_at.is_(None)).scalar()


def _check_refs(db: Session, data: dict):
    if data.get("department_id") and not db.get(Department, data["department_id"]):
        raise HTTPException(422, "Department does not exist")
    if data.get("reporting_manager_id") and not db.get(User, data["reporting_manager_id"]):
        raise HTTPException(422, "Reporting manager does not exist")


@router.get("")
def list_users(role: str | None = None, active: bool | None = None, q: str | None = Query(None, max_length=100),
               actor: User = Depends(require_roles(P.ADMIN, P.DEVELOPER, P.ONROLL)), db: Session = Depends(get_db)):
    """Admin: everyone. Developer: members of their own teams only."""
    query = db.query(User).filter(User.deleted_at.is_(None))
    if actor.role in P.LEADS:
        ids = P.team_member_ids(db, actor.id)
        query = query.filter(User.id.in_(ids or {-1}))
    if role:
        query = query.filter(User.role == role)
    if active is not None:
        query = query.filter(User.is_active.is_(active))
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    return [user_dict(db, u, private=actor.role == P.ADMIN) for u in query.order_by(User.id).all()]


@router.get("/assignable")
def assignable(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """People the caller may assign tasks to (names only)."""
    roles = P.ASSIGN_MATRIX.get(actor.role, set())
    if not roles:
        return []
    query = db.query(User).filter(User.role.in_(roles), User.is_active.is_(True), User.deleted_at.is_(None))
    return [{"id": u.id, "full_name": u.full_name, "role": u.role} for u in query.order_by(User.full_name)]


@router.get("/reviewers")
def reviewers(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Active On-Roll employees who can be named as the reviewer of a task."""
    if not P.ASSIGN_MATRIX.get(actor.role):
        return []
    query = db.query(User).filter(User.role == P.ONROLL, User.is_active.is_(True), User.deleted_at.is_(None))
    return [{"id": u.id, "full_name": u.full_name, "role": u.role} for u in query.order_by(User.full_name)]


@router.get("/intern-headcount")
def headcount(actor: User = Depends(admin_only), db: Session = Depends(get_db)):
    return intern_headcount(db)


@router.post("", status_code=201)
def create_user(body: UserCreate, request: Request, actor: User = Depends(admin_only),
                db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.query(User.id).filter(User.email == email).first():
        raise HTTPException(409, "A user with this email already exists")
    if body.role == P.DEVELOPER:
        raise HTTPException(422, "The Developer role is retired. Use On-Roll: On-Roll employees lead teams and review work.")
    if body.role == P.ADMIN and _active_admins(db) >= settings.MAX_ADMINS:
        raise HTTPException(409, f"Only {settings.MAX_ADMINS} admin accounts are allowed")
    if body.role == P.INTERN and intern_headcount(db)["vacant"] <= 0:
        raise HTTPException(409, "No intern vacancy is available. Raise the target headcount first.")
    data = body.model_dump()
    _check_refs(db, data)
    u = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name.strip(),
             role=body.role, is_active=True)
    db.add(u)
    db.flush()
    joining = body.joining_date or local_day(utcnow())
    if body.role == P.ADMIN:
        db.add(AdminProfile(user_id=u.id, phone=body.phone))
    elif body.role == P.DEVELOPER:
        db.add(DeveloperProfile(user_id=u.id, employee_code=employee_code(u.id), joining_date=joining,
                                responsibilities=body.responsibilities, phone=body.phone,
                                compensation=body.compensation))
    else:
        start = body.contract_start or joining
        end = body.contract_end
        if end is None and body.role in (P.OFFROLL, P.INTERN):
            end = add_months(start, settings.OFFROLL_TRAINING_MONTHS)
        db.add(EmployeeProfile(user_id=u.id, employee_code=employee_code(u.id), category=body.role,
                               department_id=body.department_id, reporting_manager_id=body.reporting_manager_id,
                               phone=body.phone, joining_date=joining, contract_start=start, contract_end=end,
                               compensation=body.compensation, employment_status="active",
                               conversion_status="none"))
    db.add(EmploymentHistory(user_id=u.id, event="joined", to_role=body.role, changed_by=actor.id,
                             effective_date=joining))
    audit(db, actor, "user.create", "users", u.id, new={"email": email, "role": body.role,
                                                        "full_name": u.full_name}, ip=client_ip(request))
    commit(db)
    return user_dict(db, u, private=True)


@router.get("/{user_id}")
def get_user(user_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not P.can_view_user(db, actor, user_id):
        raise HTTPException(403, "You cannot view this profile")
    u = _target(db, user_id)
    return user_dict(db, u, private=actor.role == P.ADMIN or actor.id == user_id)


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, actor: User = Depends(admin_only),
                db: Session = Depends(get_db)):
    u = _target(db, user_id)
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, data)
    prev, new = {}, {}
    if "email" in data and data["email"]:
        email = data["email"].strip().lower()
        if email != u.email:
            if db.query(User.id).filter(User.email == email).first():
                raise HTTPException(409, "A user with this email already exists")
            prev["email"], new["email"], u.email = u.email, email, email
    if data.get("full_name") and data["full_name"] != u.full_name:
        prev["full_name"], new["full_name"], u.full_name = u.full_name, data["full_name"], data["full_name"]
    if data.get("new_password"):
        u.password_hash = hash_password(data["new_password"])
        u.token_version = (u.token_version or 0) + 1     # an admin reset signs the person out everywhere
        new["password"] = "reset"
    p = get_profile(db, u)
    for f in PROFILE_FIELDS + ["responsibilities"]:
        if f in data and p is not None and hasattr(p, f) and getattr(p, f) != data[f]:
            prev[f], new[f] = getattr(p, f), data[f]
            setattr(p, f, data[f])
    if new:
        audit(db, actor, "user.update", "users", u.id, previous=prev, new=new, ip=client_ip(request))
        commit(db)
    return user_dict(db, u, private=True)


def _set_active(db, actor, u, active: bool, status: str, reason, ip):
    if not active:
        if u.id == actor.id:
            raise HTTPException(409, "You cannot deactivate your own account")
        if u.role == P.ADMIN and _active_admins(db) <= 1:
            raise HTTPException(409, "The last active admin cannot be deactivated")
        s = timer.current(db, u.id)
        if s:
            timer.end(db, s, "deactivated")
    elif u.role == P.INTERN and not u.is_active and intern_headcount(db)["vacant"] <= 0:
        raise HTTPException(409, "No intern vacancy is available")
    elif u.role == P.ADMIN and not u.is_active and _active_admins(db) >= settings.MAX_ADMINS:
        raise HTTPException(409, f"Only {settings.MAX_ADMINS} admin accounts are allowed")
    prev = {"is_active": u.is_active}
    u.is_active = active
    p = get_profile(db, u)
    if p is not None and hasattr(p, "employment_status"):
        prev["employment_status"] = p.employment_status
        p.employment_status = status
    db.add(EmploymentHistory(user_id=u.id, event="activated" if active else status, from_role=u.role,
                             to_role=u.role, reason=reason, changed_by=actor.id,
                             effective_date=local_day(utcnow())))
    audit(db, actor, "user.activate" if active else "user.deactivate", "users", u.id, previous=prev,
          new={"is_active": active, "employment_status": status}, ip=ip)


@router.post("/{user_id}/deactivate")
def deactivate(user_id: int, body: DeactivateIn, request: Request, actor: User = Depends(admin_only),
               db: Session = Depends(get_db)):
    u = _target(db, user_id)
    _set_active(db, actor, u, False, body.status, body.reason, client_ip(request))
    commit(db)
    return user_dict(db, u, private=True)


@router.post("/{user_id}/activate")
def activate(user_id: int, request: Request, actor: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = _target(db, user_id)
    _set_active(db, actor, u, True, "active", None, client_ip(request))
    commit(db)
    return user_dict(db, u, private=True)


@router.delete("/{user_id}")
def soft_delete(user_id: int, request: Request, actor: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Soft delete: the login is disabled and hidden, all history stays in the database."""
    u = _target(db, user_id)
    if u.is_active:
        _set_active(db, actor, u, False, "left", "account deleted", client_ip(request))
    u.deleted_at = utcnow()
    audit(db, actor, "user.delete", "users", u.id, ip=client_ip(request))
    commit(db)
    return {"ok": True}


ORDER = {P.INTERN: 0, P.OFFROLL: 1, P.ONROLL: 2, P.DEVELOPER: 3}
MIN_TENURE_DAYS = 60


@router.post("/{user_id}/convert")
def convert(user_id: int, body: ConvertIn, request: Request, actor: User = Depends(admin_only),
            db: Session = Depends(get_db)):
    """Change role upwards (intern -> offroll -> onroll -> developer). Nothing is deleted:
    tasks, workspaces, submissions, recordings and attendance all stay linked to the same user id."""
    if body.to_role == P.DEVELOPER:
        raise HTTPException(422, "The Developer role is retired. On-Roll is the highest employee role.")
    u = _target(db, user_id)
    if u.role not in ORDER or ORDER[body.to_role] <= ORDER[u.role]:
        raise HTTPException(409, f"Cannot convert {u.role} to {body.to_role}")
    if not u.is_active:
        raise HTTPException(409, "Activate the account before converting it")
    emp = db.query(EmployeeProfile).filter_by(user_id=u.id).first()
    today = local_day(utcnow())
    if emp and emp.joining_date and (today - emp.joining_date).days < MIN_TENURE_DAYS and not body.confirm_early:
        raise HTTPException(409, f"Joined less than {MIN_TENURE_DAYS} days ago. "
                                 "Send confirm_early=true to convert anyway.")
    old = u.role
    u.role = body.to_role
    if emp:
        emp.conversion_status = f"converted_to_{body.to_role}"
        if body.to_role in P.EMPLOYEE_ROLES:
            emp.category = body.to_role
        if body.to_role == P.ONROLL:
            emp.contract_end = None
        elif body.to_role == P.OFFROLL:
            emp.contract_start = today
            emp.contract_end = add_months(today, settings.OFFROLL_TRAINING_MONTHS)
    if body.to_role == P.DEVELOPER and not db.query(DeveloperProfile).filter_by(user_id=u.id).first():
        db.add(DeveloperProfile(user_id=u.id, employee_code=employee_code(u.id),
                                joining_date=emp.joining_date if emp else today,
                                phone=emp.phone if emp else None,
                                compensation=emp.compensation if emp else None))
    db.add(EmploymentHistory(user_id=u.id, event="converted", from_role=old, to_role=body.to_role,
                             reason=body.reason, changed_by=actor.id, effective_date=today))
    audit(db, actor, "user.convert", "users", u.id, previous={"role": old}, new={"role": body.to_role},
          ip=client_ip(request))
    notify(db, [u.id], "employee_status", f"Your role changed to {body.to_role}",
           "Sign in again to load your new workspace.", "/profile")
    commit(db)
    return user_dict(db, u, private=True)


@router.get("/{user_id}/history")
def history(user_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not (actor.role == P.ADMIN or actor.id == user_id):
        raise HTTPException(403, "You cannot view this history")
    _target(db, user_id)
    rows = db.query(EmploymentHistory).filter_by(user_id=user_id).order_by(EmploymentHistory.id).all()
    return [{"id": r.id, "event": r.event, "from_role": r.from_role, "to_role": r.to_role, "reason": r.reason,
             "effective_date": r.effective_date, "changed_by": r.changed_by, "created_at": r.created_at}
            for r in rows]


@router.get("/{user_id}/activity")
def user_activity(user_id: int, limit: int = Query(100, le=500), actor: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    if not P.can_view_user(db, actor, user_id):
        raise HTTPException(403, "You cannot view this activity")
    if not db.get(User, user_id):
        raise HTTPException(404, "User not found")
    rows = (db.query(ActivityLog).filter_by(user_id=user_id).order_by(ActivityLog.id.desc()).limit(limit).all())
    return [{"id": r.id, "kind": r.kind, "detail": r.detail, "created_at": r.created_at,
             "ip_address": r.ip_address if actor.role == P.ADMIN else None} for r in rows]

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.database.connection import get_db
from app.database.models import Meeting, MeetingParticipant, User, utcnow
from app.dependencies.auth import client_ip, get_current_user
from app.schemas import MeetingIn
from app.services.common import audit, commit, notify

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
CAN_SCHEDULE = {P.ADMIN, P.DEVELOPER, P.ONROLL}


def meeting_dict(db: Session, m: Meeting, actor: User) -> dict:
    people = (db.query(User.id, User.full_name, User.role).join(MeetingParticipant, MeetingParticipant.user_id == User.id)
              .filter(MeetingParticipant.meeting_id == m.id).order_by(User.full_name).all())
    creator = db.get(User, m.created_by)
    return {"id": m.id, "title": m.title, "agenda": m.agenda, "starts_at": m.starts_at,
            "duration_minutes": m.duration_minutes, "link": m.link, "created_by": m.created_by,
            "created_by_name": creator.full_name if creator else None, "cancelled": m.cancelled_at is not None,
            "can_cancel": m.cancelled_at is None and (actor.role == P.ADMIN or actor.id == m.created_by),
            "participants": [{"id": p.id, "full_name": p.full_name, "role": p.role} for p in people]}


@router.get("/invitable")
def invitable(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if actor.role not in CAN_SCHEDULE:
        return []
    q = db.query(User).filter(User.is_active.is_(True), User.deleted_at.is_(None), User.id != actor.id)
    if actor.role == P.DEVELOPER:  # legacy role
        ids = P.team_member_ids(db, actor.id)
        q = q.filter((User.id.in_(ids or {-1})) | (User.role.in_([P.ADMIN, P.DEVELOPER])))
    elif actor.role == P.ONROLL:
        q = q.filter(User.role != P.ADMIN)
    return [{"id": u.id, "full_name": u.full_name, "role": u.role} for u in q.order_by(User.full_name)]


@router.get("")
def list_meetings(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Admin sees all meetings; everyone else only those they created or are invited to."""
    q = db.query(Meeting)
    if actor.role != P.ADMIN:
        mine = db.query(MeetingParticipant.meeting_id).filter_by(user_id=actor.id)
        q = q.filter((Meeting.created_by == actor.id) | (Meeting.id.in_(mine)))
    return [meeting_dict(db, m, actor) for m in q.order_by(Meeting.starts_at.desc()).limit(300)]


@router.post("", status_code=201)
def create_meeting(body: MeetingIn, request: Request, actor: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    if actor.role not in CAN_SCHEDULE:
        raise HTTPException(403, f"{actor.role} users cannot schedule meetings")
    allowed = {u["id"] for u in invitable(actor, db)}
    ids = set(body.participant_ids) - {actor.id}
    if not ids or not ids <= allowed:
        raise HTTPException(403, "You cannot invite one or more of these people")
    if body.starts_at.tzinfo is None:
        raise HTTPException(422, "starts_at must include a time zone")
    m = Meeting(title=body.title, agenda=body.agenda, starts_at=body.starts_at,
                duration_minutes=body.duration_minutes, link=body.link, created_by=actor.id)
    db.add(m)
    db.flush()
    for uid in ids | {actor.id}:
        db.add(MeetingParticipant(meeting_id=m.id, user_id=uid))
    notify(db, ids, "meeting_scheduled", f"Meeting: {m.title}", f"Scheduled by {actor.full_name}", "/meetings")
    audit(db, actor, "meeting.create", "meetings", m.id, new={"title": m.title, "participants": sorted(ids)},
          ip=client_ip(request))
    commit(db)
    return meeting_dict(db, m, actor)


@router.delete("/{meeting_id}")
def cancel_meeting(meeting_id: int, request: Request, actor: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    m = db.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "Meeting not found")
    if not (actor.role == P.ADMIN or actor.id == m.created_by):
        raise HTTPException(403, "Only the organiser or an admin can cancel this meeting")
    if m.cancelled_at is None:
        m.cancelled_at = utcnow()  # kept for meeting history
        ids = [r[0] for r in db.query(MeetingParticipant.user_id).filter_by(meeting_id=m.id) if r[0] != actor.id]
        notify(db, ids, "meeting_cancelled", f"Meeting cancelled: {m.title}", None, "/meetings")
        audit(db, actor, "meeting.cancel", "meetings", m.id, ip=client_ip(request))
        commit(db)
    return {"ok": True}

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import ActivityLog, AuditLog, Notification, User
from app.websocket.manager import manager

TZ = ZoneInfo(settings.TIMEZONE)


def local_day(dt: datetime) -> date:
    return dt.astimezone(TZ).date()


def jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    return v


def audit(db: Session, actor: User | None, action: str, entity: str, record_id=None,
          previous=None, new=None, ip: str | None = None):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity=entity,
                    record_id=str(record_id) if record_id is not None else None,
                    previous_value=jsonable(previous), new_value=jsonable(new), ip_address=ip))


def activity(db: Session, user_id: int, kind: str, detail: dict | None = None, ip: str | None = None,
             session_id: int | None = None):
    db.add(ActivityLog(user_id=user_id, kind=kind, detail=jsonable(detail), ip_address=ip,
                       session_id=session_id))


def notification_dict(n: Notification) -> dict:
    return {"id": n.id, "type": n.type, "title": n.title, "body": n.body, "link": n.link,
            "is_read": n.is_read, "created_at": n.created_at.isoformat() if n.created_at else None}


def notify(db: Session, user_ids, type_: str, title: str, body: str | None = None, link: str | None = None):
    """Store notifications; call push_pending(db) after commit to deliver them live."""
    pending = db.info.setdefault("pending_notifications", [])
    for uid in set(user_ids):
        n = Notification(user_id=uid, type=type_, title=title, body=body, link=link)
        db.add(n)
        pending.append(n)


def commit(db: Session):
    """Commit, then push any queued notifications over WebSocket."""
    db.commit()
    for n in db.info.pop("pending_notifications", []):
        manager.send_from_thread(n.user_id, {"event": "notification", "data": notification_dict(n)})

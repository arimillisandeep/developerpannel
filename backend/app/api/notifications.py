from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import Notification, User
from app.dependencies.auth import get_current_user
from app.services.common import notification_dict

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(limit: int = Query(50, le=200), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    rows = (db.query(Notification).filter_by(user_id=user.id).order_by(Notification.id.desc()).limit(limit).all())
    unread = db.query(func.count(Notification.id)).filter_by(user_id=user.id, is_read=False).scalar()
    return {"unread": unread, "items": [notification_dict(n) for n in rows]}


@router.post("/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.commit()
    return {"unread": 0}


@router.post("/{notification_id}/read")
def read_one(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.is_read = True
    db.commit()
    return notification_dict(n)

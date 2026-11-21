from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.database.connection import get_db
from app.database.models import ChatConversation, ChatMember, ChatMessage, User
from app.dependencies.auth import get_current_user
from app.schemas import ConversationIn, MessageIn
from app.services.common import commit, jsonable
from app.websocket.manager import manager

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _active_users(db: Session):
    return db.query(User).filter(User.is_active.is_(True), User.deleted_at.is_(None))


def _membership(db: Session, actor: User, conv_id: int) -> tuple[ChatConversation, ChatMember]:
    conv = db.get(ChatConversation, conv_id)
    member = db.query(ChatMember).filter_by(conversation_id=conv_id, user_id=actor.id).first()
    if not conv or not member:  # same answer for "missing" and "not yours": do not leak existence
        raise HTTPException(404, "Conversation not found")
    return conv, member


def _msg(m: ChatMessage, names: dict) -> dict:
    return {"id": m.id, "conversation_id": m.conversation_id, "sender_id": m.sender_id,
            "sender": names.get(m.sender_id), "body": m.body, "created_at": m.created_at}


def conv_dict(db: Session, conv: ChatConversation, actor: User) -> dict:
    members = (db.query(User.id, User.full_name, User.role).join(ChatMember, ChatMember.user_id == User.id)
               .filter(ChatMember.conversation_id == conv.id).all())
    me = db.query(ChatMember).filter_by(conversation_id=conv.id, user_id=actor.id).first()
    last = (db.query(ChatMessage).filter_by(conversation_id=conv.id).order_by(ChatMessage.id.desc()).first())
    unread = (db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.conversation_id == conv.id, ChatMessage.sender_id != actor.id,
        ChatMessage.id > (me.last_read_message_id or 0)).scalar())
    others = [m for m in members if m.id != actor.id]
    title = conv.title or (others[0].full_name if others else "Me")
    return {"id": conv.id, "kind": conv.kind, "title": title, "unread": unread,
            "can_post": conv.kind != "announcement" or actor.role == P.ADMIN,
            "members": [{"id": m.id, "full_name": m.full_name, "role": m.role} for m in members],
            "last_message": last.body[:120] if last else None, "last_at": last.created_at if last else conv.created_at}


@router.get("/contacts")
def contacts(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": u.id, "full_name": u.full_name, "role": u.role}
            for u in _active_users(db).filter(User.id != actor.id).order_by(User.full_name)]


@router.get("/conversations")
def conversations(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(ChatConversation).join(ChatMember, ChatMember.conversation_id == ChatConversation.id)
            .filter(ChatMember.user_id == actor.id).all())
    out = [conv_dict(db, c, actor) for c in rows]
    return sorted(out, key=lambda c: c["last_at"], reverse=True)


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationIn, actor: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """direct: anyone, with one other person. group: Admin, Developer, On-Roll.
    announcement: Admin only, sent to everyone, only admins can post."""
    active = {u.id for u in _active_users(db)}
    ids = (set(body.user_ids) & active) - {actor.id}
    if body.kind == "announcement":
        if actor.role != P.ADMIN:
            raise HTTPException(403, "Only admins can create announcement channels")
        ids = active - {actor.id}
    elif body.kind == "group":
        if actor.role not in (P.ADMIN, P.DEVELOPER, P.ONROLL):
            raise HTTPException(403, f"{actor.role} users cannot create group chats")
        if len(ids) < 2 or not (body.title or "").strip():
            raise HTTPException(422, "A group needs a title and at least two other people")
    else:
        if len(ids) != 1:
            raise HTTPException(422, "A direct chat needs exactly one other person")
        other = next(iter(ids))
        mine = db.query(ChatMember.conversation_id).filter_by(user_id=actor.id)
        existing = (db.query(ChatConversation).join(ChatMember, ChatMember.conversation_id == ChatConversation.id)
                    .filter(ChatConversation.kind == "direct", ChatMember.user_id == other,
                            ChatConversation.id.in_(mine)).first())
        if existing:
            return conv_dict(db, existing, actor)
    conv = ChatConversation(kind=body.kind, title=(body.title or "").strip() or None, created_by=actor.id)
    db.add(conv)
    db.flush()
    for uid in ids | {actor.id}:
        db.add(ChatMember(conversation_id=conv.id, user_id=uid))
    commit(db)
    return conv_dict(db, conv, actor)


@router.get("/conversations/{conv_id}/messages")
def messages(conv_id: int, limit: int = Query(200, le=500), actor: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    _, me = _membership(db, actor, conv_id)
    rows = (db.query(ChatMessage).filter_by(conversation_id=conv_id).order_by(ChatMessage.id.desc())
            .limit(limit).all())[::-1]
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_({m.sender_id for m in rows} or {-1})).all())
    if rows and (me.last_read_message_id or 0) < rows[-1].id:   # opening the chat marks it read
        me.last_read_message_id = rows[-1].id
        db.commit()
    others_read = min([m.last_read_message_id or 0 for m in
                       db.query(ChatMember).filter(ChatMember.conversation_id == conv_id,
                                                   ChatMember.user_id != actor.id)] or [0])
    return {"messages": [_msg(m, names) for m in rows], "read_by_all_up_to": others_read}


@router.post("/conversations/{conv_id}/messages", status_code=201)
def send(conv_id: int, body: MessageIn, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv, me = _membership(db, actor, conv_id)
    if conv.kind == "announcement" and actor.role != P.ADMIN:
        raise HTTPException(403, "Only admins can post in an announcement channel")
    m = ChatMessage(conversation_id=conv_id, sender_id=actor.id, body=body.body.strip())
    db.add(m)
    db.flush()
    me.last_read_message_id = m.id
    commit(db)
    out = _msg(m, {actor.id: actor.full_name})
    for (uid,) in db.query(ChatMember.user_id).filter(ChatMember.conversation_id == conv_id,
                                                      ChatMember.user_id != actor.id):
        manager.send_from_thread(uid, {"event": "chat", "data": jsonable(out)})
    return out

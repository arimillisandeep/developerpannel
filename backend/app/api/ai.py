"""AI coding assistant: private conversations, streaming answers, project context, patch preview / apply,
and the admin's provider settings and usage figures. API keys stay on the server."""
import json
import threading
from datetime import datetime, time, timedelta
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.security import RateLimiter
from app.database.connection import SessionLocal, get_db
from app.database.models import (AIConversation, AIMessage, AIProvider, AISetting, Task, User, WorkspaceFile, utcnow)
from app.dependencies.auth import client_ip, get_current_user, require_roles
from app.services import ai_context, ai_provider
from app.services.ai_provider import AIError
from app.services.common import TZ, activity, audit, commit

router = APIRouter(prefix="/api/ai", tags=["ai"])
ai_limiter = RateLimiter(15, 60)          # 15 questions per minute per user
ROLES = ("admin", "onroll", "offroll", "intern")
DEFAULT_LIMITS = {"admin": 0, "onroll": 200, "offroll": 150, "intern": 100}
_stops: set[int] = set()                  # assistant message ids the user asked to stop
_stops_lock = threading.Lock()


# ---- schemas -----------------------------------------------------------------------------
class ProviderIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["openai"] = "openai"
    base_url: str = Field(min_length=8, max_length=300)
    api_key: Optional[str] = Field(None, max_length=500)       # write-only
    models: list[str] = Field(default_factory=list, max_length=50)
    default_model: Optional[str] = Field(None, max_length=120)
    is_enabled: bool = True


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    base_url: Optional[str] = Field(None, min_length=8, max_length=300)
    api_key: Optional[str] = Field(None, max_length=500)       # omit = keep, "" = remove
    models: Optional[list[str]] = Field(None, max_length=50)
    default_model: Optional[str] = Field(None, max_length=120)
    is_enabled: Optional[bool] = None


class SettingsIn(BaseModel):
    enabled: Optional[bool] = None
    role_enabled: Optional[dict[str, bool]] = None
    daily_limits: Optional[dict[str, int]] = None
    max_context_chars: Optional[int] = Field(None, ge=2000, le=400000)
    max_output_tokens: Optional[int] = Field(None, ge=200, le=32000)
    extra_instructions: Optional[str] = Field(None, max_length=4000)


class ConversationIn(BaseModel):
    title: Optional[str] = Field(None, max_length=160)
    task_id: Optional[int] = None
    workspace_id: Optional[int] = None


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class Attachment(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=200000)


class ContextIn(BaseModel):
    active_path: Optional[str] = Field(None, max_length=300)
    active_content: Optional[str] = Field(None, max_length=1_000_000)
    selection: Optional[str] = Field(None, max_length=200000)
    files: list[str] = Field(default_factory=list, max_length=30)
    tree: bool = False
    project: bool = False
    terminal: Optional[str] = Field(None, max_length=60000)
    run_output: Optional[str] = Field(None, max_length=110000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=5)


class AskIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    model: Optional[str] = Field(None, max_length=160)          # "<provider id>:<model>"
    workspace_id: Optional[int] = None
    context: ContextIn = Field(default_factory=ContextIn)


class RegenerateIn(BaseModel):
    model: Optional[str] = Field(None, max_length=160)


class SavedIn(BaseModel):
    saved: bool


class Change(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=1_000_000)


class PatchIn(BaseModel):
    workspace_id: int
    changes: list[Change] = Field(min_length=1, max_length=60)


# ---- settings and providers --------------------------------------------------------------
def get_settings_row(db: Session) -> AISetting:
    s = db.get(AISetting, 1)
    if s is None:
        s = AISetting(id=1, enabled=True, role_enabled={r: True for r in ROLES}, daily_limits=dict(DEFAULT_LIMITS),
                      max_context_chars=60000, max_output_tokens=4000)
        db.add(s)
        db.flush()
    return s


def settings_dict(s: AISetting) -> dict:
    return {"enabled": s.enabled, "role_enabled": {r: bool((s.role_enabled or {}).get(r, True)) for r in ROLES},
            "daily_limits": {r: int((s.daily_limits or {}).get(r, DEFAULT_LIMITS[r])) for r in ROLES},
            "max_context_chars": s.max_context_chars, "max_output_tokens": s.max_output_tokens,
            "extra_instructions": s.extra_instructions or ""}


def provider_dict(p: AIProvider) -> dict:
    """Never contains the key: only whether one is stored."""
    return {"id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "models": p.models or [],
            "default_model": p.default_model, "is_enabled": p.is_enabled, "key_set": bool(p.api_key_enc),
            "updated_at": p.updated_at}


def _check_url(url: str) -> str:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise HTTPException(422, "The address must start with http:// or https://")
    return url.strip().rstrip("/")


def _clean_models(models: list[str]) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in models if m and m.strip()))[:50]


def live_providers(db: Session):
    return (db.query(AIProvider).filter(AIProvider.deleted_at.is_(None), AIProvider.is_enabled.is_(True))
            .order_by(AIProvider.id).all())


def model_choices(db: Session) -> list[dict]:
    out = []
    for p in live_providers(db):
        if not p.models:
            continue
        for m in p.models:
            out.append({"id": f"{p.id}:{m}", "provider": p.name, "model": m, "default": m == (p.default_model or p.models[0])})
    return out


def _day_start() -> datetime:
    return datetime.combine(datetime.now(TZ).date(), time.min, tzinfo=TZ)


def used_today(db: Session, user_id: int) -> int:
    return (db.query(func.count(AIMessage.id)).filter(AIMessage.user_id == user_id, AIMessage.role == "user",
                                                      AIMessage.created_at >= _day_start()).scalar() or 0)


def access(db: Session, actor: User) -> dict:
    s = get_settings_row(db)
    cfg = settings_dict(s)
    role = "onroll" if actor.role == "developer" else actor.role
    choices = model_choices(db)
    limit = cfg["daily_limits"].get(role, 0)
    used = used_today(db, actor.id)
    reason = None
    if not cfg["enabled"]:
        reason = "The AI assistant is switched off by the administrator."
    elif not cfg["role_enabled"].get(role, False):
        reason = "The AI assistant is not enabled for your role."
    elif not choices:
        reason = ("No AI provider is configured yet. Add one in AI settings." if actor.role == P.ADMIN
                  else "The AI assistant is not set up yet. Ask an administrator to add an AI provider.")
    elif limit and used >= limit:
        reason = f"You used today's {limit} AI messages. The limit resets at midnight."
    return {"can_use": reason is None, "reason": reason, "models": choices, "used_today": used, "daily_limit": limit,
            "configured": bool(choices), "max_context_chars": cfg["max_context_chars"], "settings": s}


@router.get("/status")
def status(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = access(db, actor)
    db.commit()
    a.pop("settings")
    return a


@router.get("/settings")
def read_settings(actor: User = Depends(require_roles(P.ADMIN)), db: Session = Depends(get_db)):
    s = settings_dict(get_settings_row(db))
    db.commit()
    return s


@router.put("/settings")
def write_settings(body: SettingsIn, request: Request, actor: User = Depends(require_roles(P.ADMIN)),
                   db: Session = Depends(get_db)):
    s = get_settings_row(db)
    before = settings_dict(s)
    data = body.model_dump(exclude_unset=True)
    if "role_enabled" in data:
        s.role_enabled = {r: bool(data["role_enabled"].get(r, before["role_enabled"][r])) for r in ROLES}
    if "daily_limits" in data:
        if any(v < 0 or v > 100000 for v in data["daily_limits"].values()):
            raise HTTPException(422, "A daily limit must be between 0 (no limit) and 100000")
        s.daily_limits = {r: int(data["daily_limits"].get(r, before["daily_limits"][r])) for r in ROLES}
    for k in ("enabled", "max_context_chars", "max_output_tokens", "extra_instructions"):
        if k in data and data[k] is not None:
            setattr(s, k, data[k])
    audit(db, actor, "ai.settings", "ai_settings", 1, previous=before, new=settings_dict(s), ip=client_ip(request))
    commit(db)
    return settings_dict(s)


@router.get("/providers")
def list_providers(actor: User = Depends(require_roles(P.ADMIN)), db: Session = Depends(get_db)):
    rows = db.query(AIProvider).filter(AIProvider.deleted_at.is_(None)).order_by(AIProvider.id).all()
    return [provider_dict(p) for p in rows]


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn, request: Request, actor: User = Depends(require_roles(P.ADMIN)),
                    db: Session = Depends(get_db)):
    models = _clean_models(body.models)
    p = AIProvider(name=body.name.strip(), kind=body.kind, base_url=_check_url(body.base_url), models=models,
                   default_model=body.default_model if body.default_model in models else (models[0] if models else None),
                   is_enabled=body.is_enabled, api_key_enc=ai_provider.encrypt_key(body.api_key.strip()) if body.api_key else None)
    db.add(p)
    db.flush()
    audit(db, actor, "ai.provider.create", "ai_providers", p.id, new={"name": p.name, "base_url": p.base_url,
                                                                      "models": models}, ip=client_ip(request))
    commit(db)
    return provider_dict(p)


def _provider(db: Session, provider_id: int) -> AIProvider:
    p = db.get(AIProvider, provider_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(404, "Provider not found")
    return p


@router.patch("/providers/{provider_id}")
def update_provider(provider_id: int, body: ProviderUpdate, request: Request,
                    actor: User = Depends(require_roles(P.ADMIN)), db: Session = Depends(get_db)):
    p = _provider(db, provider_id)
    data = body.model_dump(exclude_unset=True)
    changed = sorted(k for k in data if k != "api_key")
    if "name" in data and data["name"]:
        p.name = data["name"].strip()
    if "base_url" in data and data["base_url"]:
        p.base_url = _check_url(data["base_url"])
    if "models" in data and data["models"] is not None:
        p.models = _clean_models(data["models"])
    if "default_model" in data:
        p.default_model = data["default_model"]
    if p.default_model not in (p.models or []):
        p.default_model = p.models[0] if p.models else None
    if "is_enabled" in data and data["is_enabled"] is not None:
        p.is_enabled = data["is_enabled"]
    if "api_key" in data and data["api_key"] is not None:
        p.api_key_enc = ai_provider.encrypt_key(data["api_key"].strip()) if data["api_key"].strip() else None
        changed.append("api_key (value not logged)")
    audit(db, actor, "ai.provider.update", "ai_providers", p.id, new={"changed": changed}, ip=client_ip(request))
    commit(db)
    return provider_dict(p)


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: int, request: Request, actor: User = Depends(require_roles(P.ADMIN)),
                    db: Session = Depends(get_db)):
    p = _provider(db, provider_id)
    p.deleted_at, p.is_enabled, p.api_key_enc = utcnow(), False, None     # the key is wiped, not kept
    audit(db, actor, "ai.provider.delete", "ai_providers", p.id, previous={"name": p.name}, ip=client_ip(request))
    commit(db)
    return {"ok": True}


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int, actor: User = Depends(require_roles(P.ADMIN)), db: Session = Depends(get_db)):
    """Asks the provider for its model list with the stored key. Proves address and key; costs nothing."""
    p = _provider(db, provider_id)
    try:
        found = ai_provider.list_models(p.kind, p.base_url, ai_provider.decrypt_key(p.api_key_enc))
    except AIError as e:
        return {"ok": False, "message": e.message, "models": []}
    return {"ok": True, "message": f"Connected. The provider offers {len(found)} models.", "models": found[:300]}


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), actor: User = Depends(require_roles(P.ADMIN)),
          db: Session = Depends(get_db)):
    """Numbers only. Conversations are private: their text is never shown here."""
    since = utcnow() - timedelta(days=days)
    rows = (db.query(AIMessage.user_id, User.full_name, User.role,
                     func.sum(func.coalesce(AIMessage.prompt_tokens, 0)), func.sum(func.coalesce(AIMessage.completion_tokens, 0)),
                     func.max(AIMessage.created_at))
            .join(User, User.id == AIMessage.user_id).filter(AIMessage.created_at >= since)
            .group_by(AIMessage.user_id, User.full_name, User.role).all())
    asked = dict(db.query(AIMessage.user_id, func.count(AIMessage.id))
                 .filter(AIMessage.created_at >= since, AIMessage.role == "user").group_by(AIMessage.user_id).all())
    failed = dict(db.query(AIMessage.user_id, func.count(AIMessage.id))
                  .filter(AIMessage.created_at >= since, AIMessage.status == "error").group_by(AIMessage.user_id).all())
    by_model = (db.query(AIMessage.model, func.count(AIMessage.id)).filter(AIMessage.created_at >= since,
                                                                          AIMessage.role == "assistant")
                .group_by(AIMessage.model).all())
    out = [{"user_id": uid, "full_name": name, "role": role, "messages": asked.get(uid, 0), "errors": failed.get(uid, 0),
            "prompt_tokens": int(pt or 0), "completion_tokens": int(ct or 0), "today": used_today(db, uid),
            "last_used_at": last} for uid, name, role, pt, ct, last in rows]
    out.sort(key=lambda r: -r["messages"])
    return {"days": days, "rows": out,
            "totals": {"messages": sum(r["messages"] for r in out), "prompt_tokens": sum(r["prompt_tokens"] for r in out),
                       "completion_tokens": sum(r["completion_tokens"] for r in out), "users": len(out)},
            "by_model": [{"model": m or "—", "answers": n} for m, n in by_model]}


# ---- conversations (private) -------------------------------------------------------------
def conv_dict(c: AIConversation, task: Task | None = None) -> dict:
    return {"id": c.id, "title": c.title, "task_id": c.task_id, "task_code": task.code if task else None,
            "workspace_id": c.workspace_id, "model": c.model, "created_at": c.created_at, "updated_at": c.updated_at}


def msg_dict(m: AIMessage) -> dict:
    meta = (m.context or {}).get("meta") if m.context else None
    return {"id": m.id, "role": m.role, "content": m.content, "status": m.status, "error": m.error, "model": m.model,
            "saved": m.saved, "created_at": m.created_at, "context": meta,
            "tokens": {"prompt": m.prompt_tokens, "completion": m.completion_tokens}}


def own_conversation(db: Session, actor: User, conv_id: int) -> AIConversation:
    c = db.get(AIConversation, conv_id)
    if not c or c.deleted_at is not None or c.user_id != actor.id:     # same answer for "not yours" and "missing"
        raise HTTPException(404, "Conversation not found")
    return c


def readable_workspace(db: Session, actor: User, ws_id: int | None, for_write: bool = False):
    if ws_id is None:
        return None, None
    from app.api.workspaces import owned_workspace
    return owned_workspace(db, actor, ws_id, for_write=for_write)


@router.get("/conversations")
def list_conversations(q: str | None = Query(None, max_length=100), task_id: int | None = None,
                       actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(AIConversation).filter(AIConversation.user_id == actor.id, AIConversation.deleted_at.is_(None))
    if task_id:
        query = query.filter(AIConversation.task_id == task_id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        hits = db.query(AIMessage.conversation_id).filter(AIMessage.user_id == actor.id,
                                                          func.lower(AIMessage.content).like(like))
        query = query.filter(or_(func.lower(AIConversation.title).like(like), AIConversation.id.in_(hits)))
    rows = query.order_by(AIConversation.updated_at.desc(), AIConversation.id.desc()).limit(200).all()
    tasks = {t.id: t for t in db.query(Task).filter(Task.id.in_({c.task_id for c in rows if c.task_id} or {-1}))}
    return [conv_dict(c, tasks.get(c.task_id)) for c in rows]


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationIn, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task_id = body.task_id
    if body.workspace_id is not None:
        ws, task = readable_workspace(db, actor, body.workspace_id)
        task_id = task.id
    elif task_id is not None:
        from app.api.tasks import get_task
        get_task(db, actor, task_id)
    c = AIConversation(user_id=actor.id, title=(body.title or "New chat").strip()[:160] or "New chat", task_id=task_id,
                       workspace_id=body.workspace_id)
    db.add(c)
    commit(db)
    return conv_dict(c, db.get(Task, task_id) if task_id else None)


@router.get("/conversations/{conv_id}")
def read_conversation(conv_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = own_conversation(db, actor, conv_id)
    msgs = db.query(AIMessage).filter_by(conversation_id=c.id).order_by(AIMessage.id).all()
    return {**conv_dict(c, db.get(Task, c.task_id) if c.task_id else None), "messages": [msg_dict(m) for m in msgs]}


@router.patch("/conversations/{conv_id}")
def rename_conversation(conv_id: int, body: TitleIn, actor: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    c = own_conversation(db, actor, conv_id)
    c.title = body.title.strip()[:160] or c.title
    commit(db)
    return conv_dict(c)


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = own_conversation(db, actor, conv_id)
    # the text is removed for real; only the usage numbers (tokens, counts) stay for the admin statistics
    for m in db.query(AIMessage).filter_by(conversation_id=c.id):
        m.content, m.context, m.saved = "", None, False
    c.deleted_at, c.title = utcnow(), "deleted"
    commit(db)
    return {"ok": True}


@router.post("/conversations/{conv_id}/clear")
def clear_conversation(conv_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Empties the chat but keeps it in the list. Usage numbers stay (moved to a hidden, deleted conversation)."""
    c = own_conversation(db, actor, conv_id)
    if db.query(AIMessage).filter_by(conversation_id=c.id).count():
        bin_ = AIConversation(user_id=actor.id, title="deleted", deleted_at=utcnow())
        db.add(bin_)
        db.flush()
        for m in db.query(AIMessage).filter_by(conversation_id=c.id):
            m.conversation_id, m.content, m.context, m.saved = bin_.id, "", None, False
    commit(db)
    return {"ok": True}


@router.get("/saved")
def saved_messages(actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(AIMessage, AIConversation.title).join(AIConversation, AIConversation.id == AIMessage.conversation_id)
            .filter(AIMessage.user_id == actor.id, AIMessage.saved.is_(True), AIConversation.deleted_at.is_(None))
            .order_by(AIMessage.id.desc()).limit(200).all())
    return [{**msg_dict(m), "conversation_id": m.conversation_id, "conversation": title} for m, title in rows]


def own_message(db: Session, actor: User, message_id: int) -> AIMessage:
    m = db.get(AIMessage, message_id)
    if not m or m.user_id != actor.id:
        raise HTTPException(404, "Message not found")
    return m


@router.patch("/messages/{message_id}")
def save_message(message_id: int, body: SavedIn, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = own_message(db, actor, message_id)
    m.saved = body.saved
    commit(db)
    return msg_dict(m)


@router.post("/messages/{message_id}/stop")
def stop_message(message_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = own_message(db, actor, message_id)
    if m.status == "streaming":
        with _stops_lock:
            _stops.add(m.id)
    return {"ok": True}


# ---- asking ------------------------------------------------------------------------------
def _pick_model(db: Session, wanted: str | None, fallback: str | None) -> tuple[AIProvider, str]:
    choices = model_choices(db)
    ids = {c["id"] for c in choices}
    chosen = wanted if wanted in ids else fallback if fallback in ids else None
    if chosen is None:
        if wanted:
            raise HTTPException(422, "That model is not available. Choose another one.")
        chosen = next((c["id"] for c in choices if c["default"]), choices[0]["id"])
    pid, model = chosen.split(":", 1)
    return db.get(AIProvider, int(pid)), model


def _history(db: Session, conv: AIConversation, upto_id: int, budget: int) -> list[dict]:
    """Earlier turns, newest kept first, inside the size budget. Old project context is not resent."""
    rows = (db.query(AIMessage).filter(AIMessage.conversation_id == conv.id, AIMessage.id < upto_id,
                                       AIMessage.status.in_(("ok", "stopped"))).order_by(AIMessage.id.desc()).limit(24).all())
    out, used = [], 0
    for m in rows:
        if not m.content:
            continue
        used += len(m.content)
        if used > budget:
            break
        out.append({"role": m.role, "content": m.content})
    return list(reversed(out))


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


def _answer(db: Session, actor: User, conv: AIConversation, user_msg: AIMessage, wanted_model: str | None,
            request: Request, cfg: AISetting) -> StreamingResponse:
    provider, model = _pick_model(db, wanted_model, conv.model)
    key = ai_provider.decrypt_key(provider.api_key_enc)
    ctx_text = (user_msg.context or {}).get("text") or ""
    system = ai_context.system_prompt(actor, cfg.extra_instructions)
    question = user_msg.content if not ctx_text else f"{user_msg.content}\n\n--- Project context from WORKCODE ---\n{ctx_text}"
    messages = ([{"role": "system", "content": system}]
                + _history(db, conv, user_msg.id, max(4000, cfg.max_context_chars // 2))
                + [{"role": "user", "content": question}])
    reply = AIMessage(conversation_id=conv.id, user_id=actor.id, role="assistant", content="", status="streaming",
                      provider_id=provider.id, model=model)
    db.add(reply)
    conv.model, conv.updated_at = f"{provider.id}:{model}", utcnow()
    activity(db, actor.id, "ai.ask", {"conversation_id": conv.id, "model": model,
                                      "context": [m["kind"] for m in (user_msg.context or {}).get("meta", [])]},
             ip=client_ip(request))
    commit(db)
    reply_id, user_msg_id, conv_id, conv_title = reply.id, user_msg.id, conv.id, conv.title
    kind, base_url, max_out = provider.kind, provider.base_url, cfg.max_output_tokens
    meta = (user_msg.context or {}).get("meta") or []
    prompt_chars = sum(len(m["content"]) for m in messages)

    def run():
        text, usage_, state, error = [], None, "ok", None
        yield _sse({"type": "start", "message_id": reply_id, "user_message_id": user_msg_id, "conversation_id": conv_id,
                    "title": conv_title, "model": model, "context": meta})
        try:
            for what, value in ai_provider.stream_chat(kind, base_url, key, model, messages, max_out):
                if what == "delta":
                    text.append(value)
                    yield _sse({"type": "delta", "text": value})
                elif what == "usage":
                    usage_ = value
                if reply_id in _stops:
                    state = "stopped"
                    break
        except AIError as e:
            state, error = "error", e.message
        except GeneratorExit:                 # the browser went away: keep what was written so far
            state = "stopped"
            raise
        except Exception:
            state, error = "error", "The AI answer failed unexpectedly. Try again."
        finally:
            with _stops_lock:
                _stops.discard(reply_id)
            own = SessionLocal()
            try:
                m = own.get(AIMessage, reply_id)
                if m is not None:
                    body = "".join(text)
                    m.content, m.status, m.error = body, state, error
                    # the provider's own numbers when it reports them, otherwise an estimate (about 4 characters per token)
                    m.prompt_tokens = (usage_ or {}).get("prompt") or prompt_chars // 4
                    m.completion_tokens = (usage_ or {}).get("completion") or len(body) // 4
                    own.commit()
                    final = msg_dict(m)
                else:
                    final = None
            finally:
                own.close()
        if state == "error":
            yield _sse({"type": "error", "message": error, "message_obj": final})
        else:
            yield _sse({"type": "done", "status": state, "message": final})

    return StreamingResponse(run(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


def _gate(db: Session, actor: User) -> AISetting:
    a = access(db, actor)
    if not a["can_use"]:
        raise HTTPException(429 if a["configured"] and a["daily_limit"] and a["used_today"] >= a["daily_limit"] else 403
                            if a["configured"] else 503, a["reason"])
    if not ai_limiter.allow(str(actor.id)):
        raise HTTPException(429, "Too many questions in one minute. Wait a moment.")
    return a["settings"]


@router.post("/conversations/{conv_id}/messages")
def ask(conv_id: int, body: AskIn, request: Request, actor: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    """Stores the question, then streams the answer as server-sent events: start, delta…, done | error."""
    conv = own_conversation(db, actor, conv_id)
    cfg = _gate(db, actor)
    ws_id = body.workspace_id if body.workspace_id is not None else None
    ws, task = readable_workspace(db, actor, ws_id)          # 403 if this user may not read that project
    opts = body.context.model_dump()
    if ws is None:                                            # no project: only what the user typed or attached
        opts.update(files=[], tree=False, project=False)
    text, meta = ai_context.build(db, actor, ws, opts, cfg.max_context_chars)
    if ws is not None:
        conv.workspace_id, conv.task_id = ws.id, task.id
    if not db.query(AIMessage.id).filter_by(conversation_id=conv.id).first() and conv.title in ("New chat", ""):
        conv.title = " ".join(body.content.split())[:60] or "New chat"
    user_msg = AIMessage(conversation_id=conv.id, user_id=actor.id, role="user", content=body.content,
                         context={"meta": meta, "text": text})
    db.add(user_msg)
    db.flush()
    try:
        return _answer(db, actor, conv, user_msg, body.model, request, cfg)
    except AIError as e:
        db.rollback()
        raise HTTPException(e.status, e.message)


@router.post("/conversations/{conv_id}/regenerate")
def regenerate(conv_id: int, body: RegenerateIn, request: Request, actor: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Answers the last question again (same project context as when it was asked). The old answer is replaced."""
    conv = own_conversation(db, actor, conv_id)
    cfg = _gate(db, actor)
    last_user = (db.query(AIMessage).filter_by(conversation_id=conv.id, role="user").order_by(AIMessage.id.desc()).first())
    if last_user is None:
        raise HTTPException(409, "There is no question to answer again")
    for m in db.query(AIMessage).filter(AIMessage.conversation_id == conv.id, AIMessage.id > last_user.id):
        if m.status == "streaming":
            raise HTTPException(409, "An answer is still being written")
        m.conversation_id = _bin(db, actor).id                 # keep the usage numbers, drop the text
        m.content, m.saved = "", False
    try:
        return _answer(db, actor, conv, last_user, body.model, request, cfg)
    except AIError as e:
        db.rollback()
        raise HTTPException(e.status, e.message)


def _bin(db: Session, actor: User) -> AIConversation:
    b = AIConversation(user_id=actor.id, title="deleted", deleted_at=utcnow())
    db.add(b)
    db.flush()
    return b


# ---- applying proposed code to the real project -------------------------------------------
def _existing(db: Session, ws_id: int) -> dict[str, str]:
    return {f.path: f.content or "" for f in db.query(WorkspaceFile).filter(
        WorkspaceFile.workspace_id == ws_id, WorkspaceFile.deleted_at.is_(None))}


def _clean_changes(changes: list[Change]) -> list[tuple[str, str]]:
    from app.api.workspaces import clean_path
    out = {}
    for c in changes:
        ai_context.check_size(c.content)
        out[clean_path(c.path)] = c.content                    # the same path twice: the last block wins
    return list(out.items())


@router.post("/patch/preview")
def patch_preview(body: PatchIn, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Shows what would change, file by file. Nothing is written."""
    ws, task = readable_workspace(db, actor, body.workspace_id)
    from app.api.tasks import EDITABLE
    have = _existing(db, ws.id)
    files = [ai_context.preview_change(have.get(path), path, content) for path, content in _clean_changes(body.changes)]
    can_apply = ws.user_id == actor.id and task.status in EDITABLE
    return {"files": files, "can_apply": can_apply,
            "reason": None if can_apply else "Read-only: this project cannot be changed right now."}


@router.post("/patch/apply")
def patch_apply(body: PatchIn, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Writes the files the user accepted. Each one gets a new saved version (kind "ai"), so it can be restored."""
    from app.api.tasks import begin_work
    from app.api.workspaces import _put, check_quota, file_dict
    ws, task = readable_workspace(db, actor, body.workspace_id, for_write=True)
    have = _existing(db, ws.id)
    todo = [(p, c) for p, c in _clean_changes(body.changes) if have.get(p) != c]
    check_quota(db, ws.id, add_files=sum(1 for p, _ in todo if p not in have),
                add_bytes=sum(len(c.encode()) - len(have.get(p, "").encode()) for p, c in todo))
    written = [_put(db, ws, actor.id, path, content, "ai") for path, content in todo]
    if written:
        ws.last_saved_at = utcnow()
        begin_work(db, task, actor)
        activity(db, actor.id, "ai.apply", {"task_id": task.id, "files": [f.path for f in written]}, ip=client_ip(request))
    commit(db)
    return {"applied": [file_dict(f) for f in written], "unchanged": len(body.changes) - len(written),
            "last_saved_at": ws.last_saved_at, "task_status": task.status}

"""Screen recordings. The browser records with the user's explicit permission and uploads
the video in chunks. The chunks are stored in the database (table recording_chunks) and are only
served through the permission-checked endpoint below. Recordings made before build 20 may still be
a file in STORAGE_DIR; those are read from there.
Build 29: the workspace opens a recording automatically (after consent), and every finished video
carries a retention date after which it and its chunks are deleted automatically."""
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import permissions as P
from app.core.config import settings
from app.database.connection import SessionLocal, get_db
from app.database.models import RecordingChunk, ScreenRecording, Task, User, utcnow
from app.dependencies.auth import client_ip, get_current_user
from app.schemas import RecordingStart
from app.services import timer
from app.services.common import activity, audit, commit

router = APIRouter(prefix="/api/recordings", tags=["recordings"])
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
STALE_SECONDS = 120


def _path(rec: ScreenRecording) -> Path:
    return Path(settings.STORAGE_DIR).resolve() / "recordings" / str(rec.user_id) / f"{rec.id}.webm"


def _close_stale(db: Session, user_id: int | None = None):
    """A recording that stopped sending chunks (tab closed, refresh, network loss) is marked
    interrupted, so the system never claims to be recording when it is not.
    Finished recordings past their retention date are then deleted — video chunks included."""
    q = db.query(ScreenRecording).filter(ScreenRecording.status == "recording")
    if user_id:
        q = q.filter(ScreenRecording.user_id == user_id)
    now, changed = utcnow(), False
    for r in q:
        if (now - r.updated_at).total_seconds() > STALE_SECONDS:
            r.status, r.ended_at, changed = "interrupted", r.updated_at, True
    expired = (db.query(ScreenRecording)
               .filter(ScreenRecording.status != "recording",
                       ScreenRecording.retention_until.isnot(None),
                       ScreenRecording.retention_until < now).all())
    if expired:
        ids = [r.id for r in expired]
        db.query(RecordingChunk).filter(RecordingChunk.recording_id.in_(ids)).delete(synchronize_session=False)
        for r in expired:
            db.delete(r)
        changed = True
    if changed:
        db.commit()


def rec_dict(db: Session, r: ScreenRecording, names: dict) -> dict:
    task = db.get(Task, r.task_id) if r.task_id else None
    end = r.ended_at or r.updated_at
    return {"id": r.id, "user_id": r.user_id, "user": names.get(r.user_id), "status": r.status,
            "started_at": r.started_at, "ended_at": r.ended_at, "size_bytes": r.size_bytes,
            "duration_seconds": int((end - r.started_at).total_seconds()), "retention_until": r.retention_until,
            "storage": "company server, private (database chunks)" if r.storage_path == "database" else r.storage_path,
            "session_id": r.session_id, "task": f"{task.code} · {task.title}" if task else None}


def _can_view(db: Session, actor: User, r: ScreenRecording) -> bool:
    return P.can_view_user(db, actor, r.user_id)


def _mine(db: Session, actor: User, rec_id: int) -> ScreenRecording:
    r = db.get(ScreenRecording, rec_id)
    if not r or r.user_id != actor.id:
        raise HTTPException(404, "Recording not found")
    return r


@router.get("")
def list_recordings(user_id: int | None = None, day: str | None = None, actor: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Own recordings; Admin sees everyone's; a Developer sees their team's."""
    _close_stale(db)
    q = db.query(ScreenRecording)
    if actor.role == P.ADMIN:
        pass
    elif actor.role in P.LEADS:
        q = q.filter(ScreenRecording.user_id.in_(P.team_member_ids(db, actor.id) | {actor.id}))
    else:
        q = q.filter(ScreenRecording.user_id == actor.id)
    if user_id:
        q = q.filter(ScreenRecording.user_id == user_id)
    rows = q.order_by(ScreenRecording.id.desc()).limit(300).all()
    if day:
        from app.services.common import local_day
        rows = [r for r in rows if local_day(r.started_at).isoformat() == day]
    names = dict(db.query(User.id, User.full_name).filter(User.id.in_({r.user_id for r in rows} or {-1})).all())
    return [rec_dict(db, r, names) for r in rows]


@router.get("/policy")
def policy(actor: User = Depends(get_current_user)):
    """What the consent dialog promises: how long videos are kept and the size cap, plus how long a
    person may stay outside the workspace tab before its recording is closed (build 31)."""
    return {"retention_days": settings.RECORDING_RETENTION_DAYS, "max_bytes": settings.MAX_RECORDING_BYTES,
            "away_grace_seconds": settings.RECORDING_AWAY_GRACE_SECONDS,
            "storage": "Private storage on the company server; only you, your lead and Admins can watch."}


@router.post("/start", status_code=201)
def start(body: RecordingStart, request: Request, actor: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    if not body.consent:
        raise HTTPException(422, "Recording needs your explicit consent")
    if not body.mime_type.startswith("video/webm"):
        raise HTTPException(422, "Only WebM recordings are accepted")
    if body.task_id:
        t = db.get(Task, body.task_id)
        if not t or t.assigned_to != actor.id:
            raise HTTPException(422, "You can only link a recording to your own task")
    for r in db.query(ScreenRecording).filter_by(user_id=actor.id, status="recording"):
        r.status, r.ended_at = "interrupted", r.updated_at
    s = timer.current(db, actor.id)
    now = utcnow()
    rec = ScreenRecording(user_id=actor.id, session_id=s.id if s else None, task_id=body.task_id,
                          mime_type=body.mime_type[:60], status="recording", consent_at=now, started_at=now,
                          size_bytes=0,
                          retention_until=now + timedelta(days=settings.RECORDING_RETENTION_DAYS)
                          if settings.RECORDING_RETENTION_DAYS > 0 else None)
    db.add(rec)
    db.flush()
    rec.storage_path = "database"
    activity(db, actor.id, "recording.start", {"recording_id": rec.id}, ip=client_ip(request),
             session_id=rec.session_id)
    commit(db)
    return rec_dict(db, rec, {actor.id: actor.full_name})


@router.post("/{rec_id}/chunk")
async def chunk(rec_id: int, request: Request, actor: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    r = _mine(db, actor, rec_id)
    if r.status != "recording":
        raise HTTPException(409, f"This recording is {r.status}")
    data = await request.body()
    if not data:
        raise HTTPException(422, "Empty chunk")
    if len(data) > settings.MAX_CHUNK_BYTES or r.size_bytes + len(data) > settings.MAX_RECORDING_BYTES:
        raise HTTPException(413, "Recording is too large")
    if r.size_bytes == 0 and data[:4] != WEBM_MAGIC:
        raise HTTPException(422, "The upload is not a WebM video")
    last = db.query(func.max(RecordingChunk.seq)).filter_by(recording_id=r.id).scalar()
    db.add(RecordingChunk(recording_id=r.id, seq=(last or 0) + 1, size_bytes=len(data), data=data))
    r.size_bytes += len(data)
    r.updated_at = utcnow()
    db.commit()
    return {"size_bytes": r.size_bytes}


@router.post("/{rec_id}/stop")
def stop(rec_id: int, request: Request, failed: bool = False, actor: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    r = _mine(db, actor, rec_id)
    if r.status == "recording":
        r.status = "failed" if failed or r.size_bytes == 0 else "completed"
        r.ended_at = utcnow()
        activity(db, actor.id, "recording.stop", {"recording_id": r.id, "status": r.status},
                 ip=client_ip(request), session_id=r.session_id)
        commit(db)
    return rec_dict(db, r, {actor.id: actor.full_name})


@router.get("/{rec_id}/file")
def playback(rec_id: int, request: Request, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.get(ScreenRecording, rec_id)
    if not r or not _can_view(db, actor, r):
        raise HTTPException(404, "Recording not found")
    chunk_ids = [row[0] for row in db.query(RecordingChunk.id).filter_by(recording_id=r.id).order_by(RecordingChunk.seq)]
    path = _path(r)
    if not chunk_ids and not path.is_file():
        raise HTTPException(404, "The video file is missing")
    if actor.id != r.user_id:
        audit(db, actor, "recording.view", "screen_recordings", r.id, ip=client_ip(request))
        db.commit()
    headers = {"Cache-Control": "no-store", "Content-Disposition": "inline"}
    if not chunk_ids:                                   # recording from before build 20, still a file on disk
        return FileResponse(path, media_type="video/webm", headers=headers)
    total = db.query(func.sum(RecordingChunk.size_bytes)).filter_by(recording_id=r.id).scalar()
    headers["Content-Length"] = str(total)
    return StreamingResponse(_stream(chunk_ids), media_type="video/webm", headers=headers)


def _stream(chunk_ids: list[int]):
    """Send the video piece by piece, so a long recording is never held in memory as a whole."""
    db = SessionLocal()
    try:
        for chunk_id in chunk_ids:
            yield db.query(RecordingChunk.data).filter_by(id=chunk_id).scalar()
    finally:
        db.close()
